from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional
from pathlib import Path
import os

CONFIG_PATH = Path(
    os.environ.get("UPS_CONFIG_PATH", "/config/ups.yaml")
)  # legacy path for migration


class UPSConfig(BaseModel):
    name: str = Field(..., description="Friendly UPS name")
    host: str = Field(..., description="apcupsd NIS host/IP")
    port: int = Field(3551, description="apcupsd NIS port")
    interval_seconds: int = Field(30, description="Polling interval")
    # Alert thresholds (any optional)
    alert_loadpct_high: Optional[float] = Field(
        None, description="Trigger if LOADPCT >= value"
    )
    alert_bcharge_low: Optional[float] = Field(
        None, description="Trigger if BCHARGE <= value"
    )
    alert_on_battery: bool = Field(
        False, description="Trigger when STATUS indicates on battery"
    )
    alert_runtime_low_minutes: Optional[float] = Field(
        None, description="Trigger if TIMELEFT <= minutes"
    )


class SMTPConfig(BaseModel):
    host: str = Field(..., description="SMTP server host/IP")
    port: int = Field(..., description="SMTP port")
    username: Optional[str] = Field(None)
    password: Optional[str] = Field(
        None, description="Plain password or set via env SMTP_PASSWORD"
    )
    use_tls: bool = Field(False, description="STARTTLS if true")
    use_ssl: bool = Field(False, description="SSL (smtplib.SMTP_SSL) if true")
    from_addr: Optional[str] = Field(None, description="From email address")
    to_addrs: List[str] = Field(
        default_factory=list, description="Recipient list"
    )
    subject_prefix: str = Field("[UPS]", description="Subject prefix")


class AppConfig(BaseModel):
    ups: List[UPSConfig]
    smtp: Optional[SMTPConfig] = None
    # UI feature flags (optional; default values used if missing)
    # Added for dashboard toggleable features
    class UIConfig(BaseModel):
        show_events: bool = True
        show_energy: bool = False
        color_badges: bool = True
        show_headroom: bool = True
        show_watts: bool = True
        show_runtime: bool = True
        allow_resize: bool = True
        enable_transfer_burst_alert: bool = False
        enable_voltage_deviation_alert: bool = False

    ui: UIConfig = UIConfig()


_cached: AppConfig | None = None


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    # Use redis store (lazy import to avoid circular)
    from .config_store import load_config_redis
    global _cached
    if _cached:
        return _cached
    cfg = load_config_redis()
    _cached = cfg
    return cfg
