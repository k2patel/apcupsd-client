"""Shared pytest fixtures: fakeredis + app overrides.

Sets env vars before app modules import settings, swaps the Redis
client in app.storage for a fakeredis instance, and mocks apcaccess.
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterator
from unittest.mock import patch

import pytest

# Configure env BEFORE importing any app modules
os.environ.setdefault("SESSION_SECRET", "test-session-secret-for-pytest-use-only-32bytes")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("ALLOW_PRIVATE_IPS", "true")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import fakeredis  # noqa: E402

# Ensure fresh settings after env vars set
from app import settings as settings_mod  # noqa: E402

settings_mod.get_settings.cache_clear()
settings_mod.settings = settings_mod.get_settings()

from app import storage as storage_mod  # noqa: E402


@pytest.fixture
def fake_redis():
    """Provide a clean fakeredis client installed into storage module."""
    client = fakeredis.FakeRedis(decode_responses=True)
    storage_mod._redis = client
    yield client
    client.flushall()
    storage_mod._redis = None


@pytest.fixture
def clean_config_cache():
    """Reset module-level config cache to force reload from (fake) Redis."""
    from app import config as config_mod
    config_mod._cached = None
    yield
    config_mod._cached = None


@pytest.fixture
def app_client(fake_redis, clean_config_cache):
    """FastAPI TestClient with fakeredis wired in."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def authed_client(app_client, fake_redis):
    """Test client with admin set up and logged in."""
    from app.auth import store_admin
    store_admin("admin", "testpassword123")
    r = app_client.post(
        "/api/login",
        json={"username": "admin", "password": "testpassword123"},
    )
    assert r.status_code == 200
    csrf = r.json()["csrf_token"]
    app_client.headers.update({"X-CSRF-Token": csrf})
    return app_client


@pytest.fixture
def mock_apcaccess():
    """Patch apc_cli.fetch_status to return a canned snapshot."""
    from app import apc_cli

    async def _fake_fetch(host, port):
        return {
            "STATUS": "ONLINE",
            "LOADPCT": "25.0",
            "NOMPOWER": "900",
            "BCHARGE": "100.0",
            "TIMELEFT": "45.0 Minutes",
            "LINEV": "120.0",
            "NOMINV": "120",
            "ITEMP": "30.5",
            "BATTV": "13.5",
            "NOMBATTV": "12.0",
            "SELFTEST": "NO",
            "REPLACEBATT": "NO",
            "LASTXFER": "No transfers since turnon",
        }

    with patch.object(apc_cli, "fetch_status", _fake_fetch):
        yield _fake_fetch


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Mark all async tests as asyncio automatically."""
    for item in items:
        if asyncio.iscoroutinefunction(item.function):
            item.add_marker(pytest.mark.asyncio)
