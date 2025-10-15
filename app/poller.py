from __future__ import annotations
import asyncio
import time
import logging
from .config import load_config
from .apc_cli import fetch_status, APCStatusError
from .storage import store_snapshot, prune_old, get_redis
from .alerts import process_alerts

logger = logging.getLogger(__name__)

_ACTIVE_TASKS: dict[str, asyncio.Task] = {}
_RELOADER_LOCK = asyncio.Lock()


async def _poll_one(ups):
    r = get_redis()
    minute_bucket_key = f"ups:watts:minute:last:{ups.name}"
    series_key = f"ups:watts:permin:{ups.name}"
    while True:
        try:
            data = await fetch_status(ups.host, ups.port)
            data['UPSNAME'] = ups.name
            # Derived metrics
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
                data['DERIVED_WATTS'] = f"{watts:.0f}"  # integer string
                data['HEADROOM_PCT'] = f"{max(0.0, 100.0 - loadpct):.0f}"
            # Runtime minutes (normalize TIMELEFT like '15.0 Minutes')
            timeleft_raw = str(data.get('TIMELEFT', '')).strip()
            try:
                runtime_min = float(timeleft_raw.split()[0])
                data['RUNTIME_MINUTES'] = f"{runtime_min:.1f}"
            except Exception:
                pass
            # Event detection (status changes, last transfer changes)
            # Reuse redis handle r
            now_ts = asyncio.get_event_loop().time()
            wall_ts = int(now_ts)
            status_key = f"ups:event:status:last:{ups.name}"
            lastxfer_key = f"ups:event:lastxfer:last:{ups.name}"
            events_list_key = f"ups:event:list:{ups.name}"
            max_events = 100
            status_now = str(data.get('STATUS', '')).upper()
            prev_status = r.get(status_key)
            if prev_status != status_now and status_now:
                r.set(status_key, status_now)
                r.lpush(events_list_key, f"{wall_ts}|STATUS|{status_now}")
            lastxfer_now = str(data.get('LASTXFER', '')).strip()
            prev_lastxfer = r.get(lastxfer_key)
            if lastxfer_now and lastxfer_now != prev_lastxfer:
                r.set(lastxfer_key, lastxfer_now)
                r.lpush(events_list_key, f"{wall_ts}|XFER|{lastxfer_now}")
            # Trim events
            r.ltrim(events_list_key, 0, max_events - 1)
            # Energy accumulation (watt-seconds)
            if 'DERIVED_WATTS' in data:
                try:
                    watts = float(data['DERIVED_WATTS'])
                    day_str = time.strftime('%Y%m%d')
                    energy_key = f"ups:energy:{ups.name}:{day_str}"
                    # increment by watts * interval_seconds (approx)
                    r.incrbyfloat(energy_key, watts * ups.interval_seconds)
                    r.expire(energy_key, 3 * 24 * 3600)
                    # Per-minute accumulation
                    minute = time.strftime('%Y%m%d%H%M')
                    # Running sum and count in a hash
                    mb = r.hgetall(minute_bucket_key)
                    if not mb or mb.get('minute') != minute:
                        # finalize previous bucket
                        if (
                            mb
                            and 'sum' in mb
                            and 'count' in mb
                            and 'minute' in mb
                        ):
                            try:
                                avg = float(mb['sum']) / max(
                                    1, int(mb['count'])
                                )
                                r.lpush(
                                    series_key,
                                    f"{mb['minute']}|{avg:.2f}"
                                )
                                # keep up to 24h of minutes
                                r.ltrim(series_key, 0, 1439)
                            except Exception:
                                pass
                        r.hset(
                            minute_bucket_key,
                            mapping={
                                'minute': minute,
                                'sum': watts,
                                'count': 1,
                            },
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
            process_alerts(ups, data)
        except Exception as e:
            if isinstance(e, APCStatusError):
                logger.warning("apcaccess error for %s: %s", ups.name, e)
            else:
                logger.warning("Polling error for %s: %s", ups.name, e)
        await asyncio.sleep(ups.interval_seconds)


async def _reconcile_tasks():
    """Ensure a polling task exists per configured UPS and remove stale ones.

    Creates tasks for new UPS entries and cancels tasks whose UPS were removed.
    """
    async with _RELOADER_LOCK:
        cfg = load_config()
        current_names = {u.name for u in cfg.ups}
        # cancel removed
        for name in list(_ACTIVE_TASKS.keys()):
            if name not in current_names:
                _ACTIVE_TASKS[name].cancel()
                del _ACTIVE_TASKS[name]
        # add new
        for ups in cfg.ups:
            if ups.name not in _ACTIVE_TASKS:
                _ACTIVE_TASKS[ups.name] = asyncio.create_task(_poll_one(ups))


async def poll_loop():
    # initial reconcile
    await _reconcile_tasks()

    async def prune_loop():
        while True:
            try:
                await prune_old()
            except Exception as e:
                logger.warning("Prune error: %s", e)
            await asyncio.sleep(3600)

    async def config_watch_loop():
        """Periodically re-read config to capture UPS CRUD changes."""
        last_fingerprint = None
        while True:
            try:
                cfg = load_config()
                fingerprint = tuple(
                    sorted(
                        (
                            u.name,
                            u.host,
                            u.port,
                            u.interval_seconds,
                        )
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
        *(_ACTIVE_TASKS.values()),
    )
