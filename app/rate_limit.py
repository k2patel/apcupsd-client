"""Rate limiting via slowapi with Redis-backed storage."""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from .settings import settings


def _enabled_swallow(f):
    """Return original limiter decorator or a no-op when rate limiting disabled."""
    if settings.rate_limit_enabled:
        return f

    def _noop(*args, **kwargs):
        def wrapper(fn):
            return fn
        return wrapper
    return _noop


limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    enabled=settings.rate_limit_enabled,
    default_limits=[],
)
