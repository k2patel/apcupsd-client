"""Authentication: argon2 password hashing + signed session cookies.

Single-admin design for homelab use. Credentials set via env vars:
  ADMIN_USERNAME, ADMIN_PASSWORD_HASH, SESSION_SECRET

If ADMIN_PASSWORD_HASH is unset, the first-run setup page generates one
and stores it in Redis under the key ``ups:admin:hash``. The stored hash
takes precedence over env vars so the operator can change their password
via the UI.
"""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.hash import argon2

from .settings import settings
from .storage import get_redis

SESSION_COOKIE = "ups_session"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
ADMIN_HASH_KEY = "ups:admin:hash"
ADMIN_USER_KEY = "ups:admin:username"


def _serializer() -> URLSafeTimedSerializer:
    secret = settings.session_secret
    if not secret:
        # Best effort ephemeral secret so we don't crash at import time in dev
        secret = "dev-insecure-change-me-please"
    return URLSafeTimedSerializer(secret, salt="ups-session")


def hash_password(password: str) -> str:
    """Produce an argon2 hash of the given password."""
    return argon2.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return argon2.verify(password, hashed)
    except Exception:
        return False


def get_stored_admin() -> tuple[str | None, str | None]:
    """Return (username, password_hash) from Redis or settings.

    Redis-stored credentials take precedence when present.
    """
    try:
        r = get_redis()
        redis_hash = r.get(ADMIN_HASH_KEY)
        redis_user = r.get(ADMIN_USER_KEY)
    except Exception:
        redis_hash = None
        redis_user = None
    username = redis_user or settings.admin_username
    pw_hash = redis_hash or settings.admin_password_hash
    return username, pw_hash


def store_admin(username: str, password: str) -> None:
    """Persist admin credentials to Redis."""
    r = get_redis()
    r.set(ADMIN_USER_KEY, username)
    r.set(ADMIN_HASH_KEY, hash_password(password))


def is_admin_configured() -> bool:
    _, pw_hash = get_stored_admin()
    return bool(pw_hash)


def create_session_token(username: str) -> str:
    return _serializer().dumps({"u": username})


def verify_session_token(token: str) -> str | None:
    try:
        data = _serializer().loads(
            token, max_age=settings.session_max_age_seconds
        )
        if isinstance(data, dict):
            return data.get("u")
    except (BadSignature, SignatureExpired):
        return None
    return None


def make_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_auth_cookies(response: Response, username: str) -> str:
    """Set session + CSRF cookies on the response. Returns CSRF token."""
    session_token = create_session_token(username)
    csrf_token = make_csrf_token()
    secure = settings.trust_proxy
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=settings.session_max_age_seconds,
        httponly=False,  # JS needs to read this
        samesite="lax",
        secure=secure,
        path="/",
    )
    return csrf_token


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def current_user(request: Request) -> str | None:
    """Return current session username or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return verify_session_token(token)


def require_session(request: Request) -> str:
    """FastAPI dependency - 401 if not authenticated."""
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_csrf(request: Request) -> None:
    """Enforce double-submit CSRF token on mutating requests."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get(CSRF_HEADER)
    if not cookie_token or not header_token or cookie_token != header_token:
        raise HTTPException(status_code=403, detail="CSRF token invalid or missing")


def require_session_and_csrf(
    request: Request, user: str = Depends(require_session)
) -> str:
    require_csrf(request)
    return user
