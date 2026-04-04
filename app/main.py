"""FastAPI application entry point.

Assembles middleware, lifespan (poller start/stop), auth, routes.
All request handlers live in app/routes/*.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .logging_config import RequestIdMiddleware, configure_logging
from .poller import cancel_all_tasks, poll_loop
from .rate_limit import limiter
from .routes import api_alerts, api_auth, api_config, api_events, api_health, api_ups, pages, sse
from .security import SecurityHeadersMiddleware
from .settings import settings

logger = logging.getLogger(__name__)

_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    if not settings.session_secret:
        logger.warning(
            "SESSION_SECRET not set; using insecure ephemeral secret. "
            "Set SESSION_SECRET in your environment for production."
        )
    task = asyncio.create_task(poll_loop())
    _background_tasks.append(task)
    logger.info("Poller started")
    try:
        yield
    finally:
        logger.info("Shutting down: cancelling background tasks")
        for t in _background_tasks:
            t.cancel()
        for t in _background_tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        await cancel_all_tasks()
        logger.info("Shutdown complete")


def create_app() -> FastAPI:
    application = FastAPI(title="APC UPS Dashboard", lifespan=lifespan)
    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Middleware (outermost first in registration; Starlette wraps inside-out)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RequestIdMiddleware)

    application.mount(
        "/static", StaticFiles(directory="app/static"), name="static"
    )

    # Routers
    application.include_router(pages.router)
    application.include_router(api_auth.router)
    application.include_router(api_health.router)
    application.include_router(api_config.router)
    application.include_router(api_ups.router)
    application.include_router(api_alerts.router)
    application.include_router(api_events.router)
    application.include_router(sse.router)

    @application.exception_handler(Exception)
    async def unhandled_exc(request: Request, exc: Exception):  # noqa: ARG001
        logger.exception("Unhandled error", extra={"path": request.url.path})
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    return application


app = create_app()
