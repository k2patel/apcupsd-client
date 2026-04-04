"""Alert history and acknowledgement endpoints."""
import time

from fastapi import APIRouter, Depends, Query

from ..auth import require_session, require_session_and_csrf
from ..storage import get_redis

router = APIRouter(prefix="/api/alerts")


@router.get("")
async def list_alerts(
    ups: str | None = Query(None),
    severity: str | None = Query(None),
    days: int = Query(30, ge=1, le=90),
    user=Depends(require_session),
):
    r = get_redis()
    raw = r.lrange("ups:alerts:history:all", 0, -1)
    cutoff = int(time.time()) - days * 86400
    out = []
    for item in raw:
        parts = item.split("|", 5)
        if len(parts) < 5:
            continue
        try:
            ts = int(parts[0])
        except ValueError:
            continue
        if ts < cutoff:
            continue
        row = {
            "ts": ts,
            "severity": parts[1],
            "ups": parts[2],
            "code": parts[3],
            "message": parts[4],
            "id": parts[5] if len(parts) > 5 else "",
        }
        if ups and row["ups"] != ups:
            continue
        if severity and row["severity"] != severity.upper():
            continue
        ack = r.get(f"ups:alerts:ack:{row['id']}")
        row["acked_ts"] = int(ack) if ack else None
        out.append(row)
    return out


@router.get("/active")
async def list_active(user=Depends(require_session)):
    """Active alerts = history entries not yet acknowledged, most recent first."""
    all_alerts = await list_alerts(days=7, user=user)
    return [a for a in all_alerts if not a.get("acked_ts")]


@router.post("/{alert_id}/ack")
async def ack_alert(alert_id: str, user=Depends(require_session_and_csrf)):
    r = get_redis()
    r.set(f"ups:alerts:ack:{alert_id}", int(time.time()), ex=30 * 86400)
    return {"message": "acknowledged"}
