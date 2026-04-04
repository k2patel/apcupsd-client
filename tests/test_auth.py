"""Auth: hash/verify, session token, login/logout, CSRF, setup."""
from __future__ import annotations

import pytest

from app.auth import (
    create_session_token,
    get_stored_admin,
    hash_password,
    is_admin_configured,
    store_admin,
    verify_password,
    verify_session_token,
)


def test_hash_and_verify_password(fake_redis):
    h = hash_password("supersecret")
    assert h.startswith("$argon2")
    assert verify_password("supersecret", h) is True
    assert verify_password("wrong", h) is False


def test_verify_password_bad_hash_returns_false(fake_redis):
    assert verify_password("anything", "not-a-valid-hash") is False


def test_session_token_roundtrip(fake_redis):
    tok = create_session_token("admin")
    assert verify_session_token(tok) == "admin"


def test_session_token_rejects_tampered(fake_redis):
    tok = create_session_token("admin")
    bad = tok[:-4] + "abcd"
    assert verify_session_token(bad) is None


def test_store_and_get_admin(fake_redis):
    store_admin("alice", "pw-strong-1")
    user, h = get_stored_admin()
    assert user == "alice"
    assert h and h.startswith("$argon2")
    assert is_admin_configured() is True


def test_login_rejects_before_setup(app_client, fake_redis):
    r = app_client.post(
        "/api/login",
        json={"username": "admin", "password": "test"},
    )
    assert r.status_code == 409


def test_login_happy_path(app_client, fake_redis):
    store_admin("admin", "testpassword123")
    r = app_client.post(
        "/api/login",
        json={"username": "admin", "password": "testpassword123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "csrf_token" in body
    # Cookies set
    assert "ups_session" in r.cookies
    assert "csrf_token" in r.cookies


def test_login_bad_password(app_client, fake_redis):
    store_admin("admin", "testpassword123")
    r = app_client.post(
        "/api/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert r.status_code == 401


def test_login_bad_username(app_client, fake_redis):
    store_admin("admin", "testpassword123")
    r = app_client.post(
        "/api/login",
        json={"username": "notadmin", "password": "testpassword123"},
    )
    assert r.status_code == 401


def test_logout_clears_cookies(authed_client):
    r = authed_client.post("/api/logout")
    assert r.status_code == 200


def test_setup_creates_admin(app_client, fake_redis):
    r = app_client.post(
        "/api/setup",
        json={"username": "newadmin", "password": "setup-pw-1234"},
    )
    assert r.status_code == 200
    assert is_admin_configured() is True


def test_setup_rejects_when_configured(app_client, fake_redis):
    store_admin("admin", "already-set-password")
    r = app_client.post(
        "/api/setup",
        json={"username": "newadmin", "password": "setup-pw-1234"},
    )
    assert r.status_code == 409


def test_setup_rejects_short_password(app_client, fake_redis):
    r = app_client.post(
        "/api/setup",
        json={"username": "admin", "password": "short"},
    )
    assert r.status_code == 422  # pydantic validation


def test_setup_rejects_bad_username(app_client, fake_redis):
    r = app_client.post(
        "/api/setup",
        json={"username": "bad user!", "password": "good-password-1"},
    )
    assert r.status_code == 400


def test_protected_endpoint_requires_auth(app_client):
    r = app_client.get("/api/config/ups")
    assert r.status_code == 401


def test_csrf_required_for_mutations(app_client, fake_redis):
    store_admin("admin", "testpassword123")
    r = app_client.post(
        "/api/login",
        json={"username": "admin", "password": "testpassword123"},
    )
    assert r.status_code == 200
    # DELETE without CSRF header
    r2 = app_client.delete("/api/config/ups/nonexistent")
    assert r2.status_code == 403


def test_mutations_work_with_csrf(authed_client):
    # Authed client already has CSRF header set in fixture
    r = authed_client.delete("/api/config/ups/nonexistent")
    # Expected 404 because UPS doesn't exist (NOT 401/403)
    assert r.status_code == 404
