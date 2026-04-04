"""Consolidated events log across all UPS."""

from fastapi import APIRouter, Depends, Query

from ..auth import require_session
from ..config import load_config
from ..storage import get_redis

router = APIRouter(prefix="/api/events")


@router.get("")
async def list_events(
    ups: str | None = Query(None),
    kind: str | None = Query(None, description="STATUS|XFER"),
    limit: int = Query(200, ge=1, le=1000),
    user=Depends(require_session),
):
    r = get_redis()
    cfg = load_config()
    target_upses = [ups] if ups else [u.name for u in cfg.ups]
    out = []
    for name in target_upses:
        raw = r.lrange(f"ups:event:list:{name}", 0, limit)
        for item in raw:
            parts = item.split("|", 2)
            if len(parts) != 3:
                continue
            try:
                ts = int(parts[0])
            except ValueError:
                continue
            if kind and parts[1] != kind.upper():
                continue
            out.append({"ts": ts, "type": parts[1], "detail": parts[2], "ups": name})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:limit]
