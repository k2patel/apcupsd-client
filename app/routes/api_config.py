"""Configuration CRUD endpoints (UPS, SMTP, UI). All require session+CSRF for writes."""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_session, require_session_and_csrf
from ..config import SMTPConfig, UIConfig, UPSConfig
from ..config_manager import (
    ConfigWriteError,
    UPSConfigUpdate,
    config_manager,
    smtp_redacted_dict,
)
from ..notifications.email import EmailSendError, send_test_email
from ..rate_limit import limiter

router = APIRouter(prefix="/api/config")


@router.get("/ups")
async def get_ups_configs(user=Depends(require_session)):
    try:
        ups_list = await config_manager.get_ups_list()
        return [ups.model_dump() for ups in ups_list]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ups/{ups_name}")
async def get_ups_config(ups_name: str, user=Depends(require_session)):
    ups = await config_manager.get_ups(ups_name)
    if not ups:
        raise HTTPException(status_code=404, detail="UPS not found")
    return ups.model_dump()


@router.post("/ups")
@limiter.limit("30/minute")
async def add_ups_config(
    request: Request, ups_config: UPSConfig, user=Depends(require_session_and_csrf)
):
    try:
        await config_manager.add_ups(ups_config)
        return {"message": "UPS configuration added successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ConfigWriteError as e:
        raise HTTPException(status_code=507, detail=str(e))


@router.put("/ups/{ups_name}")
@limiter.limit("30/minute")
async def update_ups_config(
    request: Request,
    ups_name: str,
    updates: UPSConfigUpdate,
    user=Depends(require_session_and_csrf),
):
    try:
        success = await config_manager.update_ups(ups_name, updates)
        if not success:
            raise HTTPException(status_code=404, detail="UPS not found")
        return {"message": "UPS configuration updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ConfigWriteError as e:
        raise HTTPException(status_code=507, detail=str(e))


@router.delete("/ups/{ups_name}")
@limiter.limit("30/minute")
async def delete_ups_config(
    request: Request, ups_name: str, user=Depends(require_session_and_csrf)
):
    success = await config_manager.delete_ups(ups_name)
    if not success:
        raise HTTPException(status_code=404, detail="UPS not found")
    return {"message": "UPS configuration deleted successfully"}


@router.post("/ups/{ups_name}/test")
@limiter.limit("5/minute")
async def test_ups_connection(
    request: Request, ups_name: str, user=Depends(require_session_and_csrf)
):
    ups = await config_manager.get_ups(ups_name)
    if not ups:
        raise HTTPException(status_code=404, detail="UPS not found")
    return await config_manager.validate_ups_connection(ups)


@router.post("/ups/test")
@limiter.limit("5/minute")
async def test_new_ups_connection(
    request: Request, ups_config: UPSConfig, user=Depends(require_session_and_csrf)
):
    return await config_manager.validate_ups_connection(ups_config)


@router.get("/smtp")
async def get_smtp_config(user=Depends(require_session)):
    smtp = await config_manager.get_smtp_config()
    return smtp_redacted_dict(smtp)


@router.put("/smtp")
@limiter.limit("30/minute")
async def update_smtp_config(
    request: Request, smtp_config: SMTPConfig, user=Depends(require_session_and_csrf)
):
    await config_manager.update_smtp_config(smtp_config)
    return {"message": "SMTP configuration updated"}


@router.post("/smtp/test")
@limiter.limit("5/minute")
async def test_smtp(request: Request, user=Depends(require_session_and_csrf)):
    smtp = await config_manager.get_smtp_config()
    if not smtp:
        raise HTTPException(status_code=400, detail="SMTP not configured")
    try:
        send_test_email(smtp)
    except EmailSendError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"message": "Test email sent"}


@router.get("/ui")
async def get_ui_config(user=Depends(require_session)):
    from ..config import load_config
    cfg = load_config()
    return cfg.ui.model_dump()


@router.put("/ui")
@limiter.limit("30/minute")
async def update_ui_config(
    request: Request, payload: dict, user=Depends(require_session_and_csrf)
):
    from ..config import load_config
    cfg = load_config()
    ui_dict = cfg.ui.model_dump()
    for k, v in payload.items():
        if k in ui_dict:
            ui_dict[k] = v
    new_ui = UIConfig(**ui_dict)
    await config_manager.update_ui_config(new_ui)
    return {"message": "UI config updated", "ui": new_ui.model_dump()}
