"""Per-UPS async polling, event/energy/battery-history tracking.

Connection health:
  ups:health:last_ok:<name>     - unix ts of last successful poll
  ups:health:fail_count:<name>  - consecutive failures
  ups:health:offline:<name>     - "1" if we've emitted a COMMLOST alert

Battery history:
  ups:battery:history:<name>    - JSON {ts,bcharge,timeleft,battv,nombattv}
                                  capped at 10080 entries (~7d @ 1/min)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from .alerts import Alert, dispatch_alerts, emit_info, process_alerts
from .apc_cli import APCStatusError, fetch_status
from .config import load_config
from .storage import get_redis, prune_old, store_snapshot

logger = logging.getLogger(__name__)

_ACTIVE_TASKS: dict[str, asyncio.Task] = {}
_RELOADER_LOCK = asyncio.Lock()

BATTERY_HISTORY_MAX = 10080  # 7 days @ 1/minute
HEALTH_OFFLINE_MIN_SECONDS = 180


def _get_offline_threshold(interval_seconds: int) -> int:
    return max(HEALTH_OFFLINE_MIN_SECONDS, 3 * interval_seconds)


def _record_poll_success(name: str, snapshot: dict, interval_seconds: int) -> None:
    r = get_redis()
    now = int(time.time())
    r.set(f"ups:health:last_ok:{name}", now)
    r.delete(f"ups:health:fail_count:{name}")
    was_offline = r.get(f"ups:health:offline:{name}")
    if was_offline:
        r.delete(f"ups:health:offline:{name}")
        emit_info(name, "REACHABLE", f"UPS {name} reachable again")
    # Battery history append (sample every ~60s to keep list bounded)
    last_sample_key = f"ups:battery:history:last_ts:{name}"
    last_ts_raw = r.get(last_sample_key)
    try:
        last_ts = int(last_ts_raw) if last_ts_raw else 0
    except ValueError:
        last_ts = 0
    if now - last_ts >= 60:
        try:
            sample = {
                "ts": now,
                "bcharge": _f(snapshot.get("BCHARGE")),
                "timeleft": _f(snapshot.get("TIMELEFT")),
                "battv": _f(snapshot.get("BATTV")),
                "nombattv": _f(snapshot.get("NOMBATTV")),
            }
            r.lpush(f"ups:battery:history:{name}", json.dumps(sample))
            r.ltrim(f"ups:battery:history:{name}", 0, BATTERY_HISTORY_MAX - 1)
            r.set(last_sample_key, now)
        except Exception:  # pragma: no cover
            pass


def _record_poll_failure(name: str, interval_seconds: int, reason: str) -> None:
    r = get_redis()
    now = int(time.time())
    r.incr(f"ups:health:fail_count:{name}")
    last_ok = r.get(f"ups:health:last_ok:{name}")
    try:
        last_ok_ts = int(last_ok) if last_ok else 0
    except ValueError:
        last_ok_ts = 0
    threshold = _get_offline_threshold(interval_seconds)
    # If we never succeeded, base threshold on process start (use last_ok=0 => big delta)
    if now - last_ok_ts > threshold:
        offline_flag = r.get(f"ups:health:offline:{name}")
        if not offline_flag:
            r.set(f"ups:health:offline:{name}", "1")
            alert = Alert(
                "CRITICAL",
                f"UPS {name} unreachable ({reason})",
                "COMMLOST",
                name,
                now,
            )
            cfg = load_config()
            r.lpush(
                "ups:alerts:history:all",
                f"{alert.ts}|CRITICAL|{alert.ups}|COMMLOST|{alert.message}|{alert.hash()}",
            )
            r.ltrim("ups:alerts:history:all", 0, 499)
            r.lpush(
                f"ups:alerts:recent:{name}",
                f"{alert.ts}|CRITICAL|{alert.message}",
            )
            r.ltrim(f"ups:alerts:recent:{name}", 0, 49)
            if cfg.smtp:
                dispatch_alerts(cfg.smtp, name, [alert])


def _f(v):
    try:
        return float(str(v).split()[0]) if v is not None else None
    except Exception:
        return None


async def _poll_one(ups):
    r = get_redis()
    minute_bucket_key = f"ups:watts:minute:last:{ups.name}"
    series_key = f"ups:watts:permin:{ups.name}"
    while True:
        try:
            data = await fetch_status(ups.host, ups.port)
            data['UPSNAME'] = ups.name
            try:
                loadpct = float(str(data.get('LOADPCT', '0')).split()[0])
            except Exception:
                loadpct = 0.0
            nompower = None
            try:
                nompower = float(str(data.get('NOMPOWER', '')).split()[0])
            except Exception:
                pass
            if nompower and loadpct >= 0:
                watts = nompower * loadpct / 100.0
                data['DERIVED_WATTS'] = f"{watts:.0f}"
                data['HEADROOM_PCT'] = f"{max(0.0, 100.0 - loadpct):.0f}"
            timeleft_raw = str(data.get('TIMELEFT', '')).strip()
            try:
                runtime_min = float(timeleft_raw.split()[0])
                data['RUNTIME_MINUTES'] = f"{runtime_min:.1f}"
            except Exception:
                pass
            wall_ts = int(time.time())
            status_key = f"ups:event:status:last:{ups.name}"
            lastxfer_key = f"ups:event:lastxfer:last:{ups.name}"
            events_list_key = f"ups:event:list:{ups.name}"
            max_events = 100
            status_now = str(data.get('STATUS', '')).upper()
            prev_status = r.get(status_key)
            if prev_status != status_now and status_now:
                r.set(status_key, status_now)
                r.lpush(events_list_key, f"{wall_ts}|STATUS|{status_now}")
                # Transition from ONBATT -> ONLINE: info alert
                if prev_status and "ONBATT" in str(prev_status) and "ONLINE" in status_now:
                    emit_info(
                        ups.name,
                        "LINE_RESTORED",
                        f"UPS {ups.name} returned to line power",
                    )
            lastxfer_now = str(data.get('LASTXFER', '')).strip()
            prev_lastxfer = r.get(lastxfer_key)
            if lastxfer_now and lastxfer_now != prev_lastxfer:
                r.set(lastxfer_key, lastxfer_now)
                r.lpush(events_list_key, f"{wall_ts}|XFER|{lastxfer_now}")
            r.ltrim(events_list_key, 0, max_events - 1)
            if 'DERIVED_WATTS' in data:
                try:
                    watts = float(data['DERIVED_WATTS'])
                    day_str = time.strftime('%Y%m%d')
                    energy_key = f"ups:energy:{ups.name}:{day_str}"
                    r.incrbyfloat(energy_key, watts * ups.interval_seconds)
                    r.expire(energy_key, 3 * 24 * 3600)
                    minute = time.strftime('%Y%m%d%H%M')
                    mb = r.hgetall(minute_bucket_key)
                    if not mb or mb.get('minute') != minute:
                        if mb and 'sum' in mb and 'count' in mb and 'minute' in mb:
                            try:
                                avg = float(mb['sum']) / max(1, int(mb['count']))
                                r.lpush(series_key, f"{mb['minute']}|{avg:.2f}")
                                r.ltrim(series_key, 0, 1439)
                            except Exception:
                                pass
                        r.hset(
                            minute_bucket_key,
                            mapping={'minute': minute, 'sum': watts, 'count': 1},
                        )
                        r.expire(minute_bucket_key, 26 * 3600)
                    else:
                        try:
                            new_sum = float(mb.get('sum', '0')) + watts
                            new_count = int(mb.get('count', '0')) + 1
                            r.hset(
                                minute_bucket_key,
                                mapping={
                                    'minute': minute,
                                    'sum': new_sum,
                                    'count': new_count,
                                },
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
            await store_snapshot(ups.name, data)
            _record_poll_success(ups.name, data, ups.interval_seconds)
            process_alerts(ups, data)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            reason = str(e) if not isinstance(e, APCStatusError) else str(e)
            if isinstance(e, APCStatusError):
                logger.warning("apcaccess error for %s: %s", ups.name, e)
            else:
                logger.warning("Polling error for %s: %s", ups.name, e)
            _record_poll_failure(ups.name, ups.interval_seconds, reason)
        await asyncio.sleep(ups.interval_seconds)


async def _reconcile_tasks():
    async with _RELOADER_LOCK:
        cfg = load_config()
        current = {u.name: (u.host, u.port, u.interval_seconds) for u in cfg.ups}
        # cancel removed or changed
        for name in list(_ACTIVE_TASKS.keys()):
            if name not in current:
                _ACTIVE_TASKS[name].cancel()
                del _ACTIVE_TASKS[name]
        for ups in cfg.ups:
            if ups.name not in _ACTIVE_TASKS:
                _ACTIVE_TASKS[ups.name] = asyncio.create_task(_poll_one(ups))


async def cancel_all_tasks() -> None:
    """Cancel all running poller tasks (used on shutdown)."""
    for t in _ACTIVE_TASKS.values():
        t.cancel()
    for _name, t in list(_ACTIVE_TASKS.items()):
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    _ACTIVE_TASKS.clear()


async def poll_loop():
    await _reconcile_tasks()

    async def prune_loop():
        while True:
            try:
                await prune_old()
            except Exception as e:
                logger.warning("Prune error: %s", e)
            await asyncio.sleep(3600)

    async def config_watch_loop():
        last_fingerprint = None
        while True:
            try:
                cfg = load_config()
                fingerprint = tuple(
                    sorted(
                        (u.name, u.host, u.port, u.interval_seconds)
                        for u in cfg.ups
                    )
                )
                if fingerprint != last_fingerprint:
                    await _reconcile_tasks()
                    last_fingerprint = fingerprint
            except Exception as e:
                logger.debug("Config watch error: %s", e)
            await asyncio.sleep(15)

    await asyncio.gather(
        prune_loop(),
        config_watch_loop(),
        return_exceptions=True,
    )
