"""Centralized settings loaded once at startup via pydantic-settings.

Reads environment variables once and exposes a cached Settings() instance.
Replaces scattered os.environ.get() calls throughout the codebase.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings pulled from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Redis
    redis_url: str = Field(
        default="redis://redis:6379/0", description="Redis connection URL"
    )

    # Auth
    admin_username: str = Field(default="admin", description="Admin username")
    admin_password_hash: str | None = Field(
        default=None,
        description="Argon2 password hash. If unset, first-run setup is required.",
    )
    session_secret: str | None = Field(
        default=None,
        description="Signing secret for session cookies (required in prod).",
    )
    session_max_age_seconds: int = Field(
        default=14 * 24 * 3600, description="Session cookie max age"
    )
    trust_proxy: bool = Field(
        default=False,
        description="Set true when behind HTTPS reverse proxy (enables Secure cookie + HSTS)",
    )

    # SMTP
    smtp_password: str | None = Field(
        default=None, description="SMTP password (not stored in Redis)"
    )

    # Network validation
    allow_private_ips: bool = Field(
        default=True,
        description="Allow private/RFC1918 hosts in UPSConfig.host. Default true for homelab.",
    )

    # Legacy / migration
    ups_config_path: str = Field(
        default="/config/ups.yaml",
        description="Legacy YAML path (migration-only).",
    )

    # Logging
    log_level: str = Field(default="INFO", description="Python log level")

    # Timezone
    tz: str = Field(default="UTC", description="Server timezone")

    # Rate limit toggle (disable in tests)
    rate_limit_enabled: bool = Field(
        default=True, description="Enable slowapi rate limiting"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
