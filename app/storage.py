from __future__ import annotations
import asyncio
import time
from typing import Dict, Any, List
import redis
import json
import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
RETENTION_SECONDS = 7 * 24 * 3600
MAX_SAMPLES_PER_UPS = 7 * 24 * 60 * 2  # assume worst-case 30s interval -> ~20160 entries

_redis: redis.Redis | None = None

def get_redis() -> redis.Redis:
    global _redis
    if _redis:
        return _redis
    _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis

SNAP_KEY_PREFIX = "ups:snap:"  # latest hash per ups
HIST_KEY_PREFIX = "ups:hist:"  # time-series list per ups (append JSON)

async def store_snapshot(ups_name: str, data: Dict[str, Any]):
    r = get_redis()
    ts = int(time.time())
    pipe = r.pipeline()
    # store latest snapshot (hash)
    pipe.hset(f"{SNAP_KEY_PREFIX}{ups_name}", mapping={**data, "_ts": ts})
    # append to history list
    hist_key = f"{HIST_KEY_PREFIX}{ups_name}"
    pipe.rpush(hist_key, json.dumps({"ts": ts, "data": data}))
    pipe.ltrim(hist_key, -MAX_SAMPLES_PER_UPS, -1)
    # add pruning via async task (length-based + time-based)
    pipe.execute()

async def get_latest(ups_name: str) -> Dict[str, Any] | None:
    r = get_redis()
    h = r.hgetall(f"{SNAP_KEY_PREFIX}{ups_name}")
    return h or None

async def get_history(ups_name: str, since_seconds: int = RETENTION_SECONDS) -> List[Dict[str, Any]]:
    r = get_redis()
    key = f"{HIST_KEY_PREFIX}{ups_name}"
    raw = r.lrange(key, 0, -1)
    now = int(time.time())
    out: List[Dict[str, Any]] = []
    for item in raw:
        try:
            obj = json.loads(item)
        except json.JSONDecodeError:
            continue
        if now - obj.get("ts", 0) <= since_seconds:
            out.append(obj)
    return out

async def prune_old():
    r = get_redis()
    now = int(time.time())
    cutoff = now - RETENTION_SECONDS
    for key in r.scan_iter(f"{HIST_KEY_PREFIX}*"):
        # prune from left while older than cutoff
        while True:
            item = r.lindex(key, 0)
            if not item:
                break
            try:
                obj = json.loads(item)
            except json.JSONDecodeError:
                r.lpop(key)
                continue
            if obj.get("ts", 0) < cutoff:
                r.lpop(key)
            else:
                break
