"""Server-Sent Events stream with snapshots + fleet overview."""
import asyncio

import orjson
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..auth import require_session
from ..config import load_config
from ..config_manager import get_config_version
from ..storage import get_latest, get_redis

router = APIRouter()


@router.get("/api/stream")
async def stream(user=Depends(require_session)):
    async def event_gen():
        while True:
            cfg = load_config()
            r = get_redis()
            payload = {"snapshots": {}, "cfgVersion": get_config_version()}
            for u in cfg.ups:
                snap = await get_latest(u.name)
                if snap:
                    payload["snapshots"][u.name] = snap
            payload["upsMeta"] = [
                {
                    "name": u.name,
                    "host": u.host,
                    "port": u.port,
                    "offline": bool(r.get(f"ups:health:offline:{u.name}")),
                }
                for u in cfg.ups
            ]
            for name, snap in payload["snapshots"].items():
                payload.setdefault(name, snap)
            yield f"data: {orjson.dumps(payload).decode()}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
