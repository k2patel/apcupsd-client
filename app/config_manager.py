from __future__ import annotations
from typing import List, Optional, Dict, Any
import asyncio
import logging
import socket

try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError:
    # Fallback for environments without pydantic
    BaseModel = object
    
    def Field(default=None, **kwargs):
        return default
    
    ValidationError = ValueError

from .config import UPSConfig, SMTPConfig, AppConfig
from .config_store import load_config_redis, save_config_redis

logger = logging.getLogger(__name__)

# Incremented every time configuration is modified so
# SSE clients can detect changes
_config_version: int = 0


def get_config_version() -> int:
    return _config_version


class ConfigWriteError(Exception):  # retained for API compatibility
    """Raised when configuration cannot be written (kept for compatibility)."""


class UPSConfigUpdate(BaseModel):
    """Model for updating UPS configuration"""
    name: Optional[str] = Field(None, description="Friendly UPS name")
    host: Optional[str] = Field(None, description="apcupsd NIS host/IP")
    port: Optional[int] = Field(None, description="apcupsd NIS port")
    interval_seconds: Optional[int] = Field(
        None, description="Polling interval"
    )
    alert_loadpct_high: Optional[float] = Field(
        None, description="Trigger if LOADPCT >= value"
    )
    alert_bcharge_low: Optional[float] = Field(
        None, description="Trigger if BCHARGE <= value"
    )
    alert_on_battery: Optional[bool] = Field(
        None, description="Trigger when STATUS indicates on battery"
    )
    alert_runtime_low_minutes: Optional[float] = Field(
        None, description="Trigger if TIMELEFT <= minutes"
    )


class ConfigManager:
    def __init__(self):
        self._lock = asyncio.Lock()
    
    async def load_config(self) -> AppConfig:
        async with self._lock:
            return load_config_redis()
    
    async def save_config(self, config: AppConfig) -> None:
        async with self._lock:
            save_config_redis(config)
            logger.info("Configuration saved to Redis")
            # Invalidate cached global config so subsequent
            # load_config() calls see changes
            try:
                from . import config as config_module
                config_module._cached = None
            except Exception:  # pragma: no cover - defensive
                logger.debug(
                    "Failed to invalidate config cache", exc_info=True
                )
            # bump config version
            global _config_version
            _config_version += 1
    
    async def get_ups_list(self) -> List[UPSConfig]:
        """Get list of all UPS configurations"""
        config = await self.load_config()
        return config.ups
    
    async def get_ups(self, name: str) -> Optional[UPSConfig]:
        """Get UPS configuration by name"""
        config = await self.load_config()
        for ups in config.ups:
            if ups.name == name:
                return ups
        return None
    
    async def add_ups(self, ups_config: UPSConfig) -> bool:
        """Add new UPS configuration"""
        config = await self.load_config()
        
        # Check if UPS with same name already exists
        if any(ups.name == ups_config.name for ups in config.ups):
            raise ValueError(
                f"UPS with name '{ups_config.name}' already exists"
            )
        
        config.ups.append(ups_config)
        await self.save_config(config)
        
    # No file cache now
        
        return True
    
    async def update_ups(self, name: str, updates: UPSConfigUpdate) -> bool:
        """Update existing UPS configuration"""
        config = await self.load_config()
        
        ups_index = None
        for i, ups in enumerate(config.ups):
            if ups.name == name:
                ups_index = i
                break
        
        if ups_index is None:
            return False
        
        # Apply updates
        ups_dict = config.ups[ups_index].model_dump()
        update_dict = updates.model_dump(exclude_none=True)
        ups_dict.update(update_dict)
        
        # Validate updated configuration
        try:
            updated_ups = UPSConfig(**ups_dict)
        except ValidationError as e:
            raise ValueError(f"Invalid configuration: {e}")
        
        config.ups[ups_index] = updated_ups
        await self.save_config(config)
        
    # No file cache now
        
        return True
    
    async def delete_ups(self, name: str) -> bool:
        """Delete UPS configuration"""
        config = await self.load_config()
        
        original_count = len(config.ups)
        config.ups = [ups for ups in config.ups if ups.name != name]
        
        if len(config.ups) == original_count:
            return False  # UPS not found
        
        await self.save_config(config)
        
    # No file cache now
        
        return True
    
    async def get_smtp_config(self) -> Optional[SMTPConfig]:
        """Get SMTP configuration"""
        config = await self.load_config()
        return config.smtp
    
    async def update_smtp_config(self, smtp_config: SMTPConfig) -> None:
        """Update SMTP configuration"""
        config = await self.load_config()
        config.smtp = smtp_config
        await self.save_config(config)
        
        # Clear cached config
        from . import config as config_module
        config_module._cached = None
    
    async def validate_ups_connection(
        self, ups_config: UPSConfig, timeout: float = 3.0
    ) -> Dict[str, Any]:
        """Port-only connectivity test (no protocol / CLI call)."""

        result: Dict[str, Any] = {
            "success": False,
            "message": "",
            "connectivity": {"ok": False, "error": None},
            "protocol": {"ok": False, "error": None},
            "data": None,
        }

        # Raw TCP connectivity test
        try:
            # Use low-level socket to distinguish DNS/timeouts
            with socket.create_connection(
                (ups_config.host, ups_config.port), timeout=timeout
            ):
                result["connectivity"]["ok"] = True
        except Exception as e:  # broad to surface any network issue
            result["connectivity"]["error"] = str(e)
            result["message"] = f"TCP connectivity failed: {e}"
            return result

        # For port-only test we just mirror connectivity result
        if result["connectivity"]["ok"]:
            result["protocol"]["ok"] = True
            result["success"] = True
            result["message"] = "TCP port reachable"
        else:
            result["message"] = result["message"] or "TCP port unreachable"
        return result


# Global instance
config_manager = ConfigManager()
