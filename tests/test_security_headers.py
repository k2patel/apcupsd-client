"""Security header behavior."""

from __future__ import annotations

from app import security


def test_csp_does_not_upgrade_http_when_proxy_not_trusted(app_client, monkeypatch):
    monkeypatch.setattr(security.settings, "trust_proxy", False)

    response = app_client.get("/healthz")

    csp = response.headers["content-security-policy"]
    assert "upgrade-insecure-requests" not in csp


def test_csp_upgrades_requests_when_proxy_is_trusted(app_client, monkeypatch):
    monkeypatch.setattr(security.settings, "trust_proxy", True)

    response = app_client.get("/healthz")

    csp = response.headers["content-security-policy"]
    assert "upgrade-insecure-requests" in csp
