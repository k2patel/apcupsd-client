from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .config import AppConfig, SMTPConfig, UIConfig, UPSConfig
from .config_store import load_config_redis, save_config_redis
from .settings import settings

logger = logging.getLogger(__name__)

# Incremented every time configuration is modified so SSE clients can
# detect changes
_config_version: int = 0


def get_config_version() -> int:
    return _config_version


class ConfigWriteError(Exception):
    """Raised when configuration cannot be written (kept for compatibility)."""


class UPSConfigUpdate(BaseModel):
    """Model for updating UPS configuration."""
    name: str | None = None
    host: str | None = None
    port: int | None = Field(None, ge=1, le=65535)
    interval_seconds: int | None = Field(None, ge=5, le=3600)
    alert_loadpct_high: float | None = Field(None, ge=0, le=100)
    alert_bcharge_low: float | None = Field(None, ge=0, le=100)
    alert_on_battery: bool | None = None
    alert_runtime_low_minutes: float | None = Field(None, ge=0)
    alert_itemp_high: float | None = Field(None, ge=0, le=120)


class ConfigManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def load_config(self) -> AppConfig:
        async with self._lock:
            return load_config_redis()

    async def save_config(self, config: AppConfig) -> None:
        async with self._lock:
            save_config_redis(config)
            logger.info("Configuration saved to Redis")
            try:
                from . import config as config_module
                config_module._cached = None
            except Exception:  # pragma: no cover - defensive
                logger.debug("Failed to invalidate config cache", exc_info=True)
            global _config_version
            _config_version += 1

    async def get_ups_list(self) -> list[UPSConfig]:
        config = await self.load_config()
        return config.ups

    async def get_ups(self, name: str) -> UPSConfig | None:
        config = await self.load_config()
        for ups in config.ups:
            if ups.name == name:
                return ups
        return None

    async def add_ups(self, ups_config: UPSConfig) -> bool:
        config = await self.load_config()
        if any(ups.name == ups_config.name for ups in config.ups):
            raise ValueError(
                f"UPS with name '{ups_config.name}' already exists"
            )
        config.ups.append(ups_config)
        await self.save_config(config)
        return True

    async def update_ups(self, name: str, updates: UPSConfigUpdate) -> bool:
        config = await self.load_config()
        ups_index = None
        for i, ups in enumerate(config.ups):
            if ups.name == name:
                ups_index = i
                break
        if ups_index is None:
            return False
        ups_dict = config.ups[ups_index].model_dump()
        update_dict = updates.model_dump(exclude_none=True)
        ups_dict.update(update_dict)
        try:
            updated_ups = UPSConfig(**ups_dict)
        except ValidationError as e:
            raise ValueError(f"Invalid configuration: {e}")
        config.ups[ups_index] = updated_ups
        await self.save_config(config)
        return True

    async def delete_ups(self, name: str) -> bool:
        config = await self.load_config()
        original_count = len(config.ups)
        config.ups = [ups for ups in config.ups if ups.name != name]
        if len(config.ups) == original_count:
            return False
        await self.save_config(config)
        return True

    async def get_smtp_config(self) -> SMTPConfig | None:
        config = await self.load_config()
        return config.smtp

    async def update_smtp_config(self, smtp_config: SMTPConfig) -> None:
        config = await self.load_config()
        config.smtp = smtp_config
        await self.save_config(config)

    async def update_ui_config(self, ui: UIConfig) -> None:
        config = await self.load_config()
        config.ui = ui
        await self.save_config(config)

    async def validate_ups_connection(
        self, ups_config: UPSConfig, timeout: float = 3.0
    ) -> dict[str, Any]:
        """Port-only connectivity test (no protocol / CLI call)."""
        result: dict[str, Any] = {
            "success": False,
            "message": "",
            "connectivity": {"ok": False, "error": None},
            "protocol": {"ok": False, "error": None},
            "data": None,
        }
        try:
            with socket.create_connection(
                (ups_config.host, ups_config.port), timeout=timeout
            ):
                result["connectivity"]["ok"] = True
        except Exception as e:
            result["connectivity"]["error"] = str(e)
            result["message"] = f"TCP connectivity failed: {e}"
            return result
        if result["connectivity"]["ok"]:
            result["protocol"]["ok"] = True
            result["success"] = True
            result["message"] = "TCP port reachable"
        else:
            result["message"] = result["message"] or "TCP port unreachable"
        return result


def smtp_redacted_dict(smtp: SMTPConfig | None) -> dict[str, Any] | None:
    """Return SMTP config dict with password redacted from env."""
    if smtp is None:
        return None
    d = smtp.model_dump()
    d["password"] = "***" if settings.smtp_password else None
    return d


config_manager = ConfigManager()
