"""HTML page routes (dashboard, config, login, setup, events, alerts, settings)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import CSRF_COOKIE, current_user, is_admin_configured, make_csrf_token
from ..config import load_config

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _ensure_csrf(request: Request, response):
    token = request.cookies.get(CSRF_COOKIE)
    if not token:
        token = make_csrf_token()
        response.set_cookie(
            CSRF_COOKIE, token, httponly=False, samesite="lax", path="/"
        )
    return token


def _session_or_setup_redirect(request: Request):
    if not is_admin_configured():
        return RedirectResponse("/setup", status_code=302)
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return None


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    redirect = _session_or_setup_redirect(request)
    if redirect:
        return redirect
    cfg = load_config()
    user = current_user(request)
    response = templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "ups_list": cfg.ups,
            "ui_cfg": cfg.ui.model_dump(),
            "current_user": user,
            "active_nav": "dashboard",
        },
    )
    _ensure_csrf(request, response)
    return response


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    redirect = _session_or_setup_redirect(request)
    if redirect:
        return redirect
    response = templates.TemplateResponse(
        request,
        "config.html",
        {"current_user": current_user(request), "active_nav": "config"},
    )
    _ensure_csrf(request, response)
    return response


@router.get("/events", response_class=HTMLResponse)
async def events_page(request: Request):
    redirect = _session_or_setup_redirect(request)
    if redirect:
        return redirect
    response = templates.TemplateResponse(
        request,
        "events.html",
        {"current_user": current_user(request), "active_nav": "events"},
    )
    _ensure_csrf(request, response)
    return response


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request):
    redirect = _session_or_setup_redirect(request)
    if redirect:
        return redirect
    response = templates.TemplateResponse(
        request,
        "alerts.html",
        {"current_user": current_user(request), "active_nav": "alerts"},
    )
    _ensure_csrf(request, response)
    return response


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    redirect = _session_or_setup_redirect(request)
    if redirect:
        return redirect
    response = templates.TemplateResponse(
        request,
        "settings.html",
        {"current_user": current_user(request), "active_nav": "settings"},
    )
    _ensure_csrf(request, response)
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not is_admin_configured():
        return RedirectResponse("/setup", status_code=302)
    if current_user(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html")


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    if is_admin_configured():
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "setup.html")
