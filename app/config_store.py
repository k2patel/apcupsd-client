"""Redis-backed configuration storage.

Key ``ups:config:json`` holds JSON: ``{"ups": [...], "smtp": {...}|null, "ui": {...}}``.
Legacy YAML import runs once if Redis is empty.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from .config import CONFIG_PATH, AppConfig
from .storage import get_redis

logger = logging.getLogger(__name__)

REDIS_CONFIG_KEY = "ups:config:json"


def _strip_smtp_password(data: dict) -> dict:
    """Strip persisted SMTP passwords (migration from older schema)."""
    smtp = data.get("smtp")
    if isinstance(smtp, dict) and "password" in smtp:
        smtp.pop("password", None)
    return data


def _load_legacy_yaml(path: Path) -> AppConfig | None:
    if not path.exists():
        return None
    try:
        with path.open() as f:
            raw = yaml.safe_load(f) or {}
        raw = _strip_smtp_password(raw)
        return AppConfig(**raw)
    except Exception as e:  # pragma: no cover
        logger.warning("Failed to import legacy YAML config: %s", e)
        return None


def load_config_redis() -> AppConfig:
    r = get_redis()
    raw = r.get(REDIS_CONFIG_KEY)
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        data = _strip_smtp_password(data)
        return AppConfig(**data)
    legacy = _load_legacy_yaml(CONFIG_PATH)
    if legacy:
        save_config_redis(legacy)
        logger.info("Imported legacy YAML config into Redis")
        return legacy
    empty = AppConfig(ups=[], smtp=None)
    save_config_redis(empty)
    return empty


def save_config_redis(cfg: AppConfig) -> None:
    r = get_redis()
    data = cfg.model_dump(exclude_none=True)
    data = _strip_smtp_password(data)
    r.set(REDIS_CONFIG_KEY, json.dumps(data))
