from __future__ import annotations
import asyncio
import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import orjson
from .config import load_config, UPSConfig
from .storage import get_latest, get_history
from .poller import poll_loop
from .config_manager import (
    config_manager,
    UPSConfigUpdate,
    ConfigWriteError,
    get_config_version,
)
from .storage import get_redis
from .apc_cli import fetch_status, APCStatusError

app = FastAPI(title="APC UPS Dashboard")
app.mount('/static', StaticFiles(directory='app/static'), name='static')
templates = Jinja2Templates(directory='app/templates')


@app.on_event("startup")
async def startup():
    asyncio.create_task(poll_loop())


@app.get('/', response_class=HTMLResponse)
async def dashboard(request: Request):
    cfg = load_config()
    return templates.TemplateResponse(
        'dashboard.html', {
            "request": request,
            "ups_list": cfg.ups,
            "ui_cfg": cfg.ui.model_dump(),
        }
    )


@app.get('/config', response_class=HTMLResponse)
async def config_page(request: Request):
    return templates.TemplateResponse('config.html', {"request": request})


@app.get('/api/ups')
async def list_ups():
    cfg = load_config()
    return [{"name": u.name, "host": u.host, "port": u.port} for u in cfg.ups]


@app.get('/api/ups/{ups_name}')
async def ups_status(ups_name: str):
    snap = await get_latest(ups_name)
    return snap or {"error": "not found"}


@app.get('/api/ups/{ups_name}/history')
async def ups_history(ups_name: str):
    hist = await get_history(ups_name)
    return hist


@app.get('/api/ups/{ups_name}/metric/{metric}')
async def metric_history(ups_name: str, metric: str, limit: int = 120):
    """Return recent numeric history samples for a single metric.

    Limit capped at 500 to avoid large payloads.
    """
    limit = max(1, min(limit, 500))
    all_hist = await get_history(ups_name)
    # Use only most recent entries
    recent = all_hist[-limit:]
    out = []
    for item in recent:
        data = item.get('data', {})
        raw_val = data.get(metric)
        if raw_val is None:
            continue
        # Extract leading number
        try:
            val = float(str(raw_val).split()[0])
        except Exception:
            continue
        out.append({'ts': item.get('ts'), 'value': val})
    return out


@app.get('/api/ups/{ups_name}/events')
async def ups_events(ups_name: str):
    """Return recent status/transfer events for a UPS."""
    r = get_redis()
    key = f"ups:event:list:{ups_name}"
    raw = r.lrange(key, 0, 99)
    parsed = []
    for item in raw:
        if '|' in item:
            try:
                ts_s, kind, rest = item.split('|', 2)
                parsed.append({
                    'ts': int(ts_s),
                    'type': kind,
                    'detail': rest
                })
                continue
            except Exception:
                pass
        parsed.append({'raw': item})
    return parsed


@app.get('/api/ups/{ups_name}/energy')
async def ups_energy(ups_name: str):
    """Return today's accumulated energy (approx kWh) if available."""
    r = get_redis()
    day_str = time.strftime('%Y%m%d')  # type: ignore
    key = f"ups:energy:{ups_name}:{day_str}"
    watt_seconds = r.get(key)
    if watt_seconds:
        try:
            ws = float(watt_seconds)
            kwh = ws / 3600.0 / 1000.0
            return {'kwh_today': round(kwh, 4)}
        except ValueError:
            pass
    return {'kwh_today': None}


@app.get('/api/ups/{ups_name}/watts_per_minute')
async def ups_watts_per_minute(ups_name: str):
    """Return recent per-minute average watts for a UPS (last 24h)."""
    r = get_redis()
    key = f"ups:watts:permin:{ups_name}"
    raw = r.lrange(key, 0, 1440)
    out = []
    for item in raw:
        if '|' in item:
            minute, avg = item.split('|', 1)
            try:
                out.append({'minute': minute, 'avg_watts': float(avg)})
            except ValueError:
                continue
    # list stored newest-first; reverse to chronological
    out.reverse()
    return out


@app.get('/api/ups/{ups_name}/health')
async def ups_health(ups_name: str):
    """Return aggregated health indicators.

    Includes recent alerts, voltage deviation stats, and ONBATT event count.
    """
    r = get_redis()
    # Recent alerts
    alerts_key = f"ups:alerts:recent:{ups_name}"
    alert_raw = r.lrange(alerts_key, 0, 19)
    alerts = []
    for a in alert_raw:
        if '|' in a:
            ts_s, msg = a.split('|', 1)
            try:
                alerts.append({'ts': int(ts_s), 'msg': msg})
            except ValueError:
                alerts.append({'raw': a})
        else:
            alerts.append({'raw': a})
    # Voltage deviation samples
    dev_key = f"ups:volt:dev:samples:{ups_name}"
    dev_samples = r.lrange(dev_key, 0, 49)
    dev_vals = []
    for d in dev_samples:
        try:
            dev_vals.append(float(d))
        except ValueError:
            continue
    dev_avg = sum(devVals := dev_vals) / len(devVals) if dev_vals else None
    dev_max = max(dev_vals) if dev_vals else None
    # Transfer burst count (recent hour ONBATT events)
    events_key = f"ups:event:list:{ups_name}"
    now = int(time.time())
    events = r.lrange(events_key, 0, 200)
    onbatt_hour = 0
    for ev in events:
        parts = ev.split('|')
        if len(parts) >= 3:
            try:
                ts_e = int(parts[0])
            except ValueError:
                continue
            if now - ts_e > 3600:
                continue
            if parts[1] == 'STATUS' and 'ONBATT' in parts[2]:
                onbatt_hour += 1
    return {
        'alerts': alerts,
        'voltage_deviation': {
            'avg_pct': round(dev_avg, 2) if dev_avg is not None else None,
            'max_pct': round(dev_max, 2) if dev_max is not None else None,
            'samples': len(dev_vals)
        },
        'onbatt_last_hour': onbatt_hour
    }


@app.get('/api/ups/{ups_name}/debug')
async def ups_debug(ups_name: str):
    """Return current apcaccess CLI status for a UPS."""
    cfg = load_config()
    target = next((u for u in cfg.ups if u.name == ups_name), None)
    if not target:
        raise HTTPException(status_code=404, detail='UPS not found')
    try:
        data = await fetch_status(target.host, target.port)
        return data
    except APCStatusError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/stream')
async def stream():
    # simple Server Sent Events stream of snapshots (polling redis every 5s)
    async def event_gen():
        while True:
            cfg = load_config()
            payload = {"snapshots": {}, "cfgVersion": get_config_version()}
            for u in cfg.ups:
                snap = await get_latest(u.name)
                if snap:
                    payload["snapshots"][u.name] = snap
            # include simple config metadata to help client reconcile
            payload["upsMeta"] = [
                {"name": u.name, "host": u.host, "port": u.port}
                for u in cfg.ups
            ]
            # Backward compatibility: also flatten UPS snapshots at top level
            for name, snap in payload["snapshots"].items():
                payload.setdefault(name, snap)
            yield f"data: {orjson.dumps(payload).decode()}\n\n"
            await asyncio.sleep(5)
    return StreamingResponse(event_gen(), media_type='text/event-stream')


# Configuration management endpoints
@app.get('/api/config/ups')
async def get_ups_configs():
    """Get all UPS configurations"""
    try:
        ups_list = await config_manager.get_ups_list()
        return [ups.model_dump() for ups in ups_list]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/config/ups/{ups_name}')
async def get_ups_config(ups_name: str):
    """Get specific UPS configuration"""
    try:
        ups = await config_manager.get_ups(ups_name)
        if not ups:
            raise HTTPException(status_code=404, detail="UPS not found")
        return ups.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/api/config/ups')
async def add_ups_config(ups_config: UPSConfig):
    """Add new UPS configuration"""
    try:
        await config_manager.add_ups(ups_config)
        return {"message": "UPS configuration added successfully"}
    except ConfigWriteError as e:
        raise HTTPException(status_code=507, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put('/api/config/ups/{ups_name}')
async def update_ups_config(ups_name: str, updates: UPSConfigUpdate):
    """Update UPS configuration"""
    try:
        success = await config_manager.update_ups(ups_name, updates)
        if not success:
            raise HTTPException(status_code=404, detail="UPS not found")
        return {"message": "UPS configuration updated successfully"}
    except ConfigWriteError as e:
        raise HTTPException(status_code=507, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete('/api/config/ups/{ups_name}')
async def delete_ups_config(ups_name: str):
    """Delete UPS configuration"""
    try:
        success = await config_manager.delete_ups(ups_name)
        if not success:
            raise HTTPException(status_code=404, detail="UPS not found")
        return {"message": "UPS configuration deleted successfully"}
    except ConfigWriteError as e:
        raise HTTPException(status_code=507, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/api/config/ups/{ups_name}/test')
async def test_ups_connection(ups_name: str):
    """Test UPS connection"""
    try:
        ups = await config_manager.get_ups(ups_name)
        if not ups:
            raise HTTPException(status_code=404, detail="UPS not found")
        
        result = await config_manager.validate_ups_connection(ups)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/api/config/ups/test')
async def test_new_ups_connection(ups_config: UPSConfig):
    """Test new UPS configuration connection"""
    try:
        result = await config_manager.validate_ups_connection(ups_config)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/config/smtp')
async def get_smtp_config():
    """Get SMTP configuration"""
    try:
        smtp = await config_manager.get_smtp_config()
        return smtp.model_dump() if smtp else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/config/ui')
async def get_ui_config():
    cfg = load_config()
    return cfg.ui.model_dump()


@app.put('/api/config/ui')
async def update_ui_config(payload: dict):
    # Simple partial update of UI flags
    from .config import AppConfig
    cfg = load_config()
    ui_dict = cfg.ui.model_dump()
    allowed = set(ui_dict.keys())
    for k, v in payload.items():
        if k in allowed and isinstance(v, bool):
            ui_dict[k] = v
    # Reconstruct full config and save via manager
    new_cfg = AppConfig(
        ups=cfg.ups, smtp=cfg.smtp, ui=cfg.ui.__class__(**ui_dict)
    )
    await config_manager.save_config(new_cfg)
    return {"message": "UI config updated", "ui": ui_dict}


# --- UI Tile Layout Persistence ---
@app.get('/api/ups/{ups_name}/ui_tiles')
async def get_ups_ui_tiles(ups_name: str):
    """Return persisted UI tile settings for a UPS.

    Includes: types, order, hidden, custom. Falls back to empty defaults if
    not stored yet.
    """
    r = get_redis()
    key = f"ups:ui:tiles:{ups_name}"
    raw = r.get(key)
    if not raw:
        return {
            "types": {},
            "order": [],
            "hidden": [],
            "custom": [],
            "positions": {}
        }
    try:
        data = orjson.loads(raw)
        # Basic shape validation
        if not isinstance(data, dict):
            raise ValueError
        return {
            "types": data.get("types", {}),
            "order": data.get("order", []),
            "hidden": data.get("hidden", []),
            "custom": data.get("custom", []),
            "positions": data.get("positions", {}),
        }
    except Exception:
        return {
            "types": {},
            "order": [],
            "hidden": [],
            "custom": [],
            "positions": {}
        }


@app.post('/api/ups/{ups_name}/ui_tiles')
async def save_ups_ui_tiles(ups_name: str, payload: dict):
    """Persist UI tile settings for a UPS.

    Expects JSON: { types: {...}, order: [...], hidden: [...], custom: [...] }
    """
    # Light validation / sanitization
    types = (payload.get('types')
             if isinstance(payload.get('types'), dict) else {})
    order = (payload.get('order')
             if isinstance(payload.get('order'), list) else [])
    hidden = (payload.get('hidden')
              if isinstance(payload.get('hidden'), list) else [])
    custom = (payload.get('custom')
              if isinstance(payload.get('custom'), list) else [])
    positions = (payload.get('positions')
                 if isinstance(payload.get('positions'), dict) else {})
    # Ensure custom entries minimally formed
    norm_custom = []
    for c in custom or []:
        if not isinstance(c, dict):
            continue
        metric = c.get('metric')
        chart = c.get('chart')
        cid = c.get('id') or ''
        source = c.get('source', 'live')
        if not metric or not chart:
            continue
        norm_custom.append({
            'id': cid,
            'metric': metric,
            'chart': chart,
            'source': source
        })
    doc = {
        'types': types,
        'order': order,
        'hidden': hidden,
        'custom': norm_custom,
        'positions': positions,
        'saved_ts': int(time.time())
    }
    r = get_redis()
    key = f"ups:ui:tiles:{ups_name}"
    r.set(key, orjson.dumps(doc))
    return {"message": "saved", "count_custom": len(norm_custom)}


@app.delete('/api/ups/{ups_name}/ui_tiles')
async def clear_ups_ui_tiles(ups_name: str):
    """Delete stored UI tile layout/settings for a UPS (full reset)."""
    r = get_redis()
    key = f"ups:ui:tiles:{ups_name}"
    r.delete(key)
    return {"message": "cleared"}
