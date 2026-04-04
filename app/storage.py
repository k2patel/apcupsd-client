from __future__ import annotations

import json
import time
from typing import Any

import redis

from .settings import settings

RETENTION_SECONDS = 7 * 24 * 3600
MAX_SAMPLES_PER_UPS = 7 * 24 * 60 * 2  # worst-case ~30s interval

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis:
        return _redis
    _redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def reset_redis_client() -> None:
    """Test hook - clears cached Redis connection."""
    global _redis
    _redis = None


SNAP_KEY_PREFIX = "ups:snap:"
HIST_KEY_PREFIX = "ups:hist:"


async def store_snapshot(ups_name: str, data: dict[str, Any]):
    r = get_redis()
    ts = int(time.time())
    pipe = r.pipeline()
    pipe.hset(f"{SNAP_KEY_PREFIX}{ups_name}", mapping={**data, "_ts": ts})
    hist_key = f"{HIST_KEY_PREFIX}{ups_name}"
    pipe.rpush(hist_key, json.dumps({"ts": ts, "data": data}))
    pipe.ltrim(hist_key, -MAX_SAMPLES_PER_UPS, -1)
    pipe.execute()


async def get_latest(ups_name: str) -> dict[str, Any] | None:
    r = get_redis()
    h = r.hgetall(f"{SNAP_KEY_PREFIX}{ups_name}")
    return h or None


async def get_history(
    ups_name: str, since_seconds: int = RETENTION_SECONDS
) -> list[dict[str, Any]]:
    r = get_redis()
    key = f"{HIST_KEY_PREFIX}{ups_name}"
    raw = r.lrange(key, 0, -1)
    now = int(time.time())
    out: list[dict[str, Any]] = []
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
