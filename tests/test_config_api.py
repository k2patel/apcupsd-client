"""Config CRUD API: auth, CSRF, create/list/update/delete."""
from __future__ import annotations


def test_unauthed_cannot_list_ups(app_client):
    r = app_client.get("/api/config/ups")
    assert r.status_code == 401


def test_unauthed_cannot_add_ups(app_client):
    r = app_client.post(
        "/api/config/ups",
        json={"name": "u1", "host": "192.168.1.10"},
    )
    assert r.status_code == 401


def test_add_and_list_ups(authed_client):
    r = authed_client.post(
        "/api/config/ups",
        json={"name": "u1", "host": "192.168.1.10", "port": 3551, "interval_seconds": 30},
    )
    assert r.status_code == 200
    r2 = authed_client.get("/api/config/ups")
    assert r2.status_code == 200
    body = r2.json()
    assert len(body) == 1
    assert body[0]["name"] == "u1"
    assert body[0]["host"] == "192.168.1.10"


def test_add_duplicate_rejects(authed_client):
    authed_client.post(
        "/api/config/ups",
        json={"name": "u1", "host": "192.168.1.10"},
    )
    r = authed_client.post(
        "/api/config/ups",
        json={"name": "u1", "host": "192.168.1.11"},
    )
    assert r.status_code == 400


def test_add_ssrf_host_rejected(authed_client):
    r = authed_client.post(
        "/api/config/ups",
        json={"name": "bad", "host": "127.0.0.1"},
    )
    assert r.status_code == 422


def test_update_ups(authed_client):
    authed_client.post(
        "/api/config/ups",
        json={"name": "u1", "host": "192.168.1.10"},
    )
    r = authed_client.put(
        "/api/config/ups/u1",
        json={"host": "192.168.2.20", "interval_seconds": 60},
    )
    assert r.status_code == 200
    r2 = authed_client.get("/api/config/ups/u1")
    body = r2.json()
    assert body["host"] == "192.168.2.20"
    assert body["interval_seconds"] == 60


def test_update_nonexistent(authed_client):
    r = authed_client.put(
        "/api/config/ups/missing",
        json={"host": "192.168.2.20"},
    )
    assert r.status_code == 404


def test_delete_ups(authed_client):
    authed_client.post(
        "/api/config/ups",
        json={"name": "u1", "host": "192.168.1.10"},
    )
    r = authed_client.delete("/api/config/ups/u1")
    assert r.status_code == 200
    r2 = authed_client.get("/api/config/ups")
    assert r2.json() == []


def test_delete_nonexistent(authed_client):
    r = authed_client.delete("/api/config/ups/missing")
    assert r.status_code == 404


def test_get_smtp_none(authed_client):
    r = authed_client.get("/api/config/smtp")
    assert r.status_code == 200
    assert r.json() is None


def test_smtp_password_always_redacted(authed_client, monkeypatch):
    from app import settings as settings_mod
    monkeypatch.setattr(settings_mod.settings, "smtp_password", "supersecret")
    r = authed_client.put(
        "/api/config/smtp",
        json={
            "host": "smtp.example.com",
            "port": 587,
            "username": "user@example.com",
            "use_tls": True,
            "from_addr": "alerts@example.com",
            "to_addrs": ["ops@example.com"],
        },
    )
    assert r.status_code == 200
    r2 = authed_client.get("/api/config/smtp")
    body = r2.json()
    # Never raw password
    assert body.get("password") in ("***", None)
    assert body["host"] == "smtp.example.com"


def test_ui_config_default(authed_client):
    r = authed_client.get("/api/config/ui")
    assert r.status_code == 200
    body = r.json()
    assert "show_events" in body


def test_ui_config_update(authed_client):
    r = authed_client.put(
        "/api/config/ui",
        json={"show_energy": True, "energy_cost_per_kwh": 0.15},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ui"]["show_energy"] is True
    assert body["ui"]["energy_cost_per_kwh"] == 0.15


def test_ui_config_energy_cost_keeps_four_decimal_rate(authed_client):
    r = authed_client.put(
        "/api/config/ui",
        json={"show_energy": True, "energy_cost_per_kwh": 0.13654},
    )

    assert r.status_code == 200
    assert r.json()["ui"]["energy_cost_per_kwh"] == 0.1365


def test_ui_config_rejects_negative_energy_cost(authed_client):
    r = authed_client.put(
        "/api/config/ui",
        json={"energy_cost_per_kwh": -0.1},
    )

    assert r.status_code == 422
