"""Authentication endpoints: login, logout, first-run setup."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..auth import (
    clear_auth_cookies,
    get_stored_admin,
    is_admin_configured,
    require_session_and_csrf,
    set_auth_cookies,
    store_admin,
    verify_password,
)
from ..rate_limit import limiter

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class SetupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=256)


_PW_POLICY_MSG = "Password must be at least 8 characters"


@router.post("/api/login")
@limiter.limit("5/minute")
async def api_login(request: Request, response: Response, payload: LoginRequest):
    username, pw_hash = get_stored_admin()
    if not pw_hash:
        raise HTTPException(status_code=409, detail="Admin not configured; run setup")
    if payload.username != username or not verify_password(payload.password, pw_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    csrf = set_auth_cookies(response, username)
    return {"ok": True, "csrf_token": csrf}


@router.post("/api/logout")
async def api_logout(response: Response, user=Depends(require_session_and_csrf)):
    clear_auth_cookies(response)
    return {"ok": True}


@router.post("/api/setup")
@limiter.limit("3/minute")
async def api_setup(request: Request, response: Response, payload: SetupRequest):
    if is_admin_configured():
        raise HTTPException(status_code=409, detail="Admin already configured")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail=_PW_POLICY_MSG)
    if not re.match(r"^[a-zA-Z0-9_.@-]+$", payload.username):
        raise HTTPException(status_code=400, detail="Invalid username characters")
    store_admin(payload.username, payload.password)
    csrf = set_auth_cookies(response, payload.username)
    return {"ok": True, "csrf_token": csrf}
