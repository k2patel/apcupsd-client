"""Liveness + readiness probes."""
from __future__ import annotations

from .config_store import load_config_redis
from .storage import get_redis


def liveness() -> dict:
    return {"status": "ok"}


def readiness() -> tuple[int, dict]:
    """Returns (http_status, payload)."""
    checks = {}
    ok = True
    try:
        r = get_redis()
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["redis"] = f"error: {e}"
        ok = False
    try:
        load_config_redis()
        checks["config"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["config"] = f"error: {e}"
        ok = False
    return (200 if ok else 503, {"status": "ok" if ok else "error", "checks": checks})
