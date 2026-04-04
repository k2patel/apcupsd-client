"""Liveness, readiness, and Prometheus metrics endpoints (unauthenticated)."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from ..health import liveness, readiness
from ..metrics import render_metrics

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return liveness()


@router.get("/readyz")
async def readyz():
    status, payload = readiness()
    return JSONResponse(payload, status_code=status)


@router.get("/metrics")
async def metrics():
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
