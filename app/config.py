from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, field_validator

from .settings import settings

CONFIG_PATH = Path(settings.ups_config_path)  # legacy path for migration

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)

_BLOCKED_LITERALS = {"localhost", "localhost.localdomain"}


def _validate_host_string(host: str) -> str:
    """Validate a host field. Rejects loopback/link-local always; rejects
    private ranges when ALLOW_PRIVATE_IPS is false.
    """
    host = host.strip()
    if not host:
        raise ValueError("host must not be empty")
    if host.lower() in _BLOCKED_LITERALS:
        raise ValueError(f"host '{host}' is not permitted (loopback alias)")
    # Try as IP first
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise ValueError(f"host IP {host} is not a valid polling target")
        if ip.is_private and not settings.allow_private_ips:
            raise ValueError(
                f"private IP {host} not allowed (set ALLOW_PRIVATE_IPS=true)"
            )
        return host
    except ValueError as ip_err:
        # Fall through to hostname validation only when the string wasn't a
        # parseable IP address
        if "does not appear to be an IPv4 or IPv6 address" not in str(ip_err):
            raise
    # Validate as hostname
    if not _HOSTNAME_RE.match(host):
        raise ValueError(f"host '{host}' is not a valid hostname or IP")
    return host


class UPSConfig(BaseModel):
    name: str = Field(..., description="Friendly UPS name")
    host: str = Field(..., description="apcupsd NIS host/IP")
    port: int = Field(3551, ge=1, le=65535, description="apcupsd NIS port")
    interval_seconds: int = Field(
        30, ge=5, le=3600, description="Polling interval"
    )
    # Alert thresholds (any optional)
    alert_loadpct_high: float | None = Field(
        None, ge=0, le=100, description="Trigger if LOADPCT >= value"
    )
    alert_bcharge_low: float | None = Field(
        None, ge=0, le=100, description="Trigger if BCHARGE <= value"
    )
    alert_on_battery: bool = Field(
        False, description="Trigger when STATUS indicates on battery"
    )
    alert_runtime_low_minutes: float | None = Field(
        None, ge=0, description="Trigger if TIMELEFT <= minutes"
    )
    alert_itemp_high: float | None = Field(
        None, ge=0, le=120, description="Trigger if internal temp >= C"
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(
                "name must be 1-32 chars, alphanumeric / underscore / dash only"
            )
        return v

    @field_validator("host")
    @classmethod
    def _validate_host(cls, v: str) -> str:
        return _validate_host_string(v)


class SMTPConfig(BaseModel):
    host: str = Field(..., description="SMTP server host/IP")
    port: int = Field(..., ge=1, le=65535, description="SMTP port")
    username: str | None = Field(None)
    # password is never persisted in Redis; read from env SMTP_PASSWORD
    use_tls: bool = Field(False, description="STARTTLS if true")
    use_ssl: bool = Field(False, description="SSL (smtplib.SMTP_SSL) if true")
    from_addr: str | None = Field(None, description="From email address")
    to_addrs: list[str] = Field(
        default_factory=list, description="Recipient list"
    )
    subject_prefix: str = Field("[UPS]", description="Subject prefix")
    silent_hours_start: int | None = Field(
        None, ge=0, le=23, description="Silent window start hour (local time)"
    )
    silent_hours_end: int | None = Field(
        None, ge=0, le=23, description="Silent window end hour (local time)"
    )
    daily_summary_hour: int | None = Field(
        None, ge=0, le=23, description="Hour to send daily summary"
    )


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
    energy_cost_per_kwh: float = 0.0


class AppConfig(BaseModel):
    ups: list[UPSConfig] = Field(default_factory=list)
    smtp: SMTPConfig | None = None
    ui: UIConfig = Field(default_factory=UIConfig)

    # Backward-compat alias: older code references AppConfig.UIConfig
    UIConfig: ClassVar[type[UIConfig]] = UIConfig


_cached: AppConfig | None = None


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    """Load config from Redis, cached in-process.

    Invalidate via ``config_module._cached = None`` after any write.
    """
    from .config_store import load_config_redis
    global _cached
    if _cached:
        return _cached
    cfg = load_config_redis()
    _cached = cfg
    return cfg
