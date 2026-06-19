"""Per-UPS data APIs: status, history, metric, events, energy, health, battery health, export, debug, tiles."""
import json
import time

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..apc_cli import APCStatusError, fetch_status
from ..auth import require_session, require_session_and_csrf
from ..config import load_config
from ..exports import export_energy_csv, export_events_csv, export_history_csv
from ..storage import get_history, get_latest, get_redis

router = APIRouter(prefix="/api/ups")


@router.get("")
async def list_ups(user=Depends(require_session)):
    cfg = load_config()
    return [{"name": u.name, "host": u.host, "port": u.port} for u in cfg.ups]


@router.get("/fleet/overview")
async def fleet_overview(user=Depends(require_session)):
    """Aggregate summary across all UPS."""
    cfg = load_config()
    r = get_redis()
    total = len(cfg.ups)
    counts = {"online": 0, "on_battery": 0, "warning": 0, "offline": 0, "unknown": 0}
    total_watts = 0.0
    min_timeleft = None
    rows = []
    for ups in cfg.ups:
        snap = r.hgetall(f"ups:snap:{ups.name}") or {}
        is_offline = bool(r.get(f"ups:health:offline:{ups.name}"))
        status = str(snap.get("STATUS", "")).upper()
        state = "unknown"
        if is_offline:
            state = "offline"
        elif "ONBATT" in status:
            state = "on_battery"
        elif "ONLINE" in status:
            state = "online"
        counts[state] = counts.get(state, 0) + 1
        try:
            w = float(snap.get("DERIVED_WATTS", 0) or 0)
            total_watts += w
        except ValueError:
            pass
        try:
            tl = float(str(snap.get("TIMELEFT", "")).split()[0])
            if min_timeleft is None or tl < min_timeleft:
                min_timeleft = tl
        except Exception:
            pass
        rows.append({"name": ups.name, "state": state, "status": status})
    return {
        "total": total,
        "counts": counts,
        "total_watts": round(total_watts, 1),
        "min_timeleft_minutes": min_timeleft,
        "rows": rows,
    }


@router.get("/{ups_name}")
async def ups_status(ups_name: str, user=Depends(require_session)):
    snap = await get_latest(ups_name)
    return snap or {"error": "not found"}


@router.get("/{ups_name}/history")
async def ups_history(ups_name: str, user=Depends(require_session)):
    return await get_history(ups_name)


@router.get("/{ups_name}/metric/{metric}")
async def metric_history(
    ups_name: str, metric: str, limit: int = 120, user=Depends(require_session)
):
    limit = max(1, min(limit, 500))
    all_hist = await get_history(ups_name)
    recent = all_hist[-limit:]
    out = []
    for item in recent:
        data = item.get("data", {})
        raw_val = data.get(metric)
        if raw_val is None:
            continue
        try:
            val = float(str(raw_val).split()[0])
        except Exception:
            continue
        out.append({"ts": item.get("ts"), "value": val})
    return out


@router.get("/{ups_name}/events")
async def ups_events(ups_name: str, user=Depends(require_session)):
    r = get_redis()
    raw = r.lrange(f"ups:event:list:{ups_name}", 0, 99)
    parsed = []
    for item in raw:
        if "|" in item:
            try:
                ts_s, kind, rest = item.split("|", 2)
                parsed.append({"ts": int(ts_s), "type": kind, "detail": rest})
                continue
            except Exception:
                pass
        parsed.append({"raw": item})
    return parsed


@router.get("/{ups_name}/energy")
async def ups_energy(ups_name: str, user=Depends(require_session)):
    r = get_redis()
    day_str = time.strftime("%Y%m%d")
    key = f"ups:energy:{ups_name}:{day_str}"
    watt_seconds = r.get(key)
    cfg = load_config()
    rate = cfg.ui.energy_cost_per_kwh if hasattr(cfg.ui, "energy_cost_per_kwh") else 0.0
    if watt_seconds:
        try:
            ws = float(watt_seconds)
            kwh = ws / 3600.0 / 1000.0
            return {"kwh_today": round(kwh, 4), "cost_today": round(kwh * rate, 4)}
        except ValueError:
            pass
    return {"kwh_today": None, "cost_today": None}


@router.get("/{ups_name}/watts_per_minute")
async def ups_watts_per_minute(ups_name: str, user=Depends(require_session)):
    r = get_redis()
    raw = r.lrange(f"ups:watts:permin:{ups_name}", 0, 1440)
    out = []
    for item in raw:
        if "|" in item:
            minute, avg = item.split("|", 1)
            try:
                out.append({"minute": minute, "avg_watts": float(avg)})
            except ValueError:
                continue
    out.reverse()
    return out


@router.get("/{ups_name}/health")
async def ups_health(ups_name: str, user=Depends(require_session)):
    r = get_redis()
    alert_raw = r.lrange(f"ups:alerts:recent:{ups_name}", 0, 19)
    alerts = []
    for a in alert_raw:
        parts = a.split("|", 2)
        if len(parts) == 3:
            try:
                alerts.append({"ts": int(parts[0]), "severity": parts[1], "msg": parts[2]})
                continue
            except ValueError:
                pass
        if "|" in a:
            ts_s, msg = a.split("|", 1)
            try:
                alerts.append({"ts": int(ts_s), "msg": msg})
                continue
            except ValueError:
                pass
        alerts.append({"raw": a})
    dev_samples = r.lrange(f"ups:volt:dev:samples:{ups_name}", 0, 49)
    dev_vals = []
    for d in dev_samples:
        try:
            dev_vals.append(float(d))
        except ValueError:
            continue
    dev_avg = sum(dev_vals) / len(dev_vals) if dev_vals else None
    dev_max = max(dev_vals) if dev_vals else None
    last_ok = r.get(f"ups:health:last_ok:{ups_name}")
    is_offline = bool(r.get(f"ups:health:offline:{ups_name}"))
    fail_count = r.get(f"ups:health:fail_count:{ups_name}")
    events = r.lrange(f"ups:event:list:{ups_name}", 0, 200)
    now = int(time.time())
    onbatt_hour = 0
    for ev in events:
        parts = ev.split("|")
        if len(parts) >= 3:
            try:
                ts_e = int(parts[0])
            except ValueError:
                continue
            if now - ts_e > 3600:
                continue
            if parts[1] == "STATUS" and "ONBATT" in parts[2]:
                onbatt_hour += 1
    return {
        "online": not is_offline,
        "last_ok_ts": int(last_ok) if last_ok else None,
        "fail_count": int(fail_count) if fail_count else 0,
        "alerts": alerts,
        "voltage_deviation": {
            "avg_pct": round(dev_avg, 2) if dev_avg is not None else None,
            "max_pct": round(dev_max, 2) if dev_max is not None else None,
            "samples": len(dev_vals),
        },
        "onbatt_last_hour": onbatt_hour,
    }


@router.get("/{ups_name}/battery_health")
async def battery_health(ups_name: str, user=Depends(require_session)):
    """Return battery-health trend from sampled history."""
    r = get_redis()
    raw = r.lrange(f"ups:battery:history:{ups_name}", 0, -1)
    samples = []
    for item in raw:
        try:
            samples.append(json.loads(item))
        except Exception:
            continue
    samples.sort(key=lambda s: s.get("ts", 0))
    # Estimate runtime-at-full-charge: TIMELEFT * (100 / BCHARGE) when BCHARGE>0
    normalized = []
    for s in samples:
        bc = s.get("bcharge")
        tl = s.get("timeleft")
        if bc and tl and bc > 10:
            normalized.append({"ts": s["ts"], "est_full_runtime_min": tl * 100.0 / bc})
    slope_per_day = None
    decline_pct_14d = None
    if len(normalized) >= 10:
        first = normalized[0]
        last = normalized[-1]
        span_days = max(1e-6, (last["ts"] - first["ts"]) / 86400.0)
        slope_per_day = (last["est_full_runtime_min"] - first["est_full_runtime_min"]) / span_days
        # Compute 14d decline as % of initial runtime
        cutoff_14d = last["ts"] - 14 * 86400
        older = [n for n in normalized if n["ts"] <= cutoff_14d]
        if older:
            baseline = older[0]["est_full_runtime_min"]
            if baseline > 0:
                decline_pct_14d = (
                    (baseline - last["est_full_runtime_min"]) / baseline * 100.0
                )
    return {
        "samples": len(samples),
        "estimated_full_runtime_samples": normalized[-200:],
        "slope_per_day": round(slope_per_day, 3) if slope_per_day is not None else None,
        "decline_pct_14d": round(decline_pct_14d, 2) if decline_pct_14d is not None else None,
    }


@router.get("/{ups_name}/export")
async def export_ups(
    ups_name: str,
    format: str = Query("csv"),
    since_days: int = Query(7, ge=1, le=30),
    kind: str = Query("history"),
    user=Depends(require_session),
):
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only csv format is supported")
    if kind == "history":
        gen = export_history_csv(ups_name, since_days)
        filename = f"{ups_name}_history_{since_days}d.csv"
    elif kind == "events":
        gen = export_events_csv(ups_name, since_days)
        filename = f"{ups_name}_events_{since_days}d.csv"
    elif kind == "energy":
        gen = export_energy_csv(ups_name, since_days)
        filename = f"{ups_name}_energy_{since_days}d.csv"
    else:
        raise HTTPException(status_code=400, detail="kind must be history|events|energy")
    return StreamingResponse(
        gen,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{ups_name}/debug")
async def ups_debug(ups_name: str, user=Depends(require_session)):
    cfg = load_config()
    target = next((u for u in cfg.ups if u.name == ups_name), None)
    if not target:
        raise HTTPException(status_code=404, detail="UPS not found")
    try:
        return await fetch_status(target.host, target.port)
    except APCStatusError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ups_name}/ui_tiles")
async def get_ups_ui_tiles(ups_name: str, user=Depends(require_session)):
    r = get_redis()
    raw = r.get(f"ups:ui:tiles:{ups_name}")
    default = {
        "types": {}, "order": [], "hidden": [], "custom": [],
        "positions": {}, "card_size": None, "exists": False,
    }
    if not raw:
        return default
    try:
        data = orjson.loads(raw)
        return {
            "types": data.get("types", {}),
            "order": data.get("order", []),
            "hidden": data.get("hidden", []),
            "custom": data.get("custom", []),
            "positions": data.get("positions", {}),
            "card_size": data.get("card_size"),
            "exists": True,
        }
    except Exception:
        return default


@router.post("/{ups_name}/ui_tiles")
async def save_ups_ui_tiles(
    ups_name: str, payload: dict, user=Depends(require_session_and_csrf)
):
    types = payload.get("types") if isinstance(payload.get("types"), dict) else {}
    order = payload.get("order") if isinstance(payload.get("order"), list) else []
    hidden = payload.get("hidden") if isinstance(payload.get("hidden"), list) else []
    custom = payload.get("custom") if isinstance(payload.get("custom"), list) else []
    positions = payload.get("positions") if isinstance(payload.get("positions"), dict) else {}
    raw_card_size = payload.get("card_size")
    card_size = None
    if isinstance(raw_card_size, dict):
        try:
            w = int(raw_card_size.get("width") or 0)
            h = int(raw_card_size.get("height") or 0)
            # Clamp to sane bounds matching the frontend resize limits
            if 200 <= w <= 2000 and 200 <= h <= 2000:
                card_size = {"width": w, "height": h}
        except (TypeError, ValueError):
            card_size = None
    norm_custom = []
    for c in custom or []:
        if not isinstance(c, dict):
            continue
        metric = c.get("metric")
        chart = c.get("chart")
        if not metric or not chart:
            continue
        norm_custom.append({
            "id": c.get("id") or "",
            "metric": metric,
            "chart": chart,
            "source": c.get("source", "live"),
        })
    doc = {
        "types": types,
        "order": order,
        "hidden": hidden,
        "custom": norm_custom,
        "positions": positions,
        "card_size": card_size,
        "saved_ts": int(time.time()),
    }
    r = get_redis()
    r.set(f"ups:ui:tiles:{ups_name}", orjson.dumps(doc))
    return {"message": "saved", "count_custom": len(norm_custom)}


@router.delete("/{ups_name}/ui_tiles")
async def clear_ups_ui_tiles(ups_name: str, user=Depends(require_session_and_csrf)):
    r = get_redis()
    r.delete(f"ups:ui:tiles:{ups_name}")
    return {"message": "cleared"}
