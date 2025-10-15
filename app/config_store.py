"""Redis-backed configuration storage replacing YAML file.

Schema:
  Key ups:config:json -> JSON object: {"ups": [...], "smtp": {...}|null}

Migration:
  On first load if redis key missing and legacy YAML present, import it.
"""
from __future__ import annotations
from typing import Optional
from pathlib import Path
import json
import logging
from .storage import get_redis
from .config import AppConfig, CONFIG_PATH
import yaml

logger = logging.getLogger(__name__)

REDIS_CONFIG_KEY = "ups:config:json"


def _load_legacy_yaml(path: Path) -> Optional[AppConfig]:
    if not path.exists():
        return None
    try:
        with path.open() as f:
            raw = yaml.safe_load(f) or {}
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
        return AppConfig(**data)
    # Migration path
    legacy = _load_legacy_yaml(CONFIG_PATH)
    if legacy:
        save_config_redis(legacy)
        logger.info("Imported legacy YAML config into Redis")
        return legacy
    # If nothing exists, create empty scaffold
    empty = AppConfig(ups=[], smtp=None)
    save_config_redis(empty)
    return empty


def save_config_redis(cfg: AppConfig) -> None:
    r = get_redis()
    r.set(REDIS_CONFIG_KEY, json.dumps(cfg.model_dump(exclude_none=True)))
