"""SSRF / config validators + SMTP password redaction."""
from __future__ import annotations

import pytest

from app.config import SMTPConfig, UPSConfig
from app.config_manager import smtp_redacted_dict
from app.settings import settings


def test_valid_ups_config():
    u = UPSConfig(name="rack1", host="192.168.1.10", port=3551, interval_seconds=30)
    assert u.host == "192.168.1.10"
    assert u.interval_seconds == 30


def test_reject_loopback_literal():
    with pytest.raises(Exception, match="loopback"):
        UPSConfig(name="bad", host="localhost")


def test_reject_loopback_ip():
    with pytest.raises(Exception, match="not a valid polling target"):
        UPSConfig(name="bad", host="127.0.0.1")


def test_reject_ipv6_loopback():
    with pytest.raises(Exception, match="not a valid polling target"):
        UPSConfig(name="bad", host="::1")


def test_reject_link_local():
    with pytest.raises(Exception, match="not a valid polling target"):
        UPSConfig(name="bad", host="169.254.1.1")


def test_reject_private_ip_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_ips", False)
    with pytest.raises(Exception, match="private IP"):
        UPSConfig(name="bad", host="10.0.0.5")


def test_accept_private_ip_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "allow_private_ips", True)
    u = UPSConfig(name="good", host="10.0.0.5")
    assert u.host == "10.0.0.5"


def test_reject_empty_name():
    with pytest.raises(Exception):
        UPSConfig(name="", host="192.168.1.10")


def test_reject_name_too_long():
    with pytest.raises(Exception):
        UPSConfig(name="a" * 33, host="192.168.1.10")


def test_reject_bad_name_chars():
    with pytest.raises(Exception, match="letters, digits"):
        UPSConfig(name="bad/name!", host="192.168.1.10")


def test_accept_valid_name_chars():
    u = UPSConfig(name="ups_rack-01", host="192.168.1.10")
    assert u.name == "ups_rack-01"


def test_accept_name_with_space_and_dot():
    u = UPSConfig(name="APC UPS", host="192.168.1.10")
    assert u.name == "APC UPS"
    u2 = UPSConfig(name="Server.Room.UPS", host="192.168.1.10")
    assert u2.name == "Server.Room.UPS"


def test_reject_invalid_port():
    with pytest.raises(Exception):
        UPSConfig(name="x", host="192.168.1.10", port=0)
    with pytest.raises(Exception):
        UPSConfig(name="x", host="192.168.1.10", port=70000)


def test_reject_invalid_interval():
    with pytest.raises(Exception):
        UPSConfig(name="x", host="192.168.1.10", interval_seconds=1)
    with pytest.raises(Exception):
        UPSConfig(name="x", host="192.168.1.10", interval_seconds=99999)


def test_accept_valid_hostname():
    u = UPSConfig(name="dns", host="ups.lan.example.com")
    assert u.host == "ups.lan.example.com"


def test_reject_bad_hostname():
    with pytest.raises(Exception):
        UPSConfig(name="x", host="not valid host")


def test_smtp_model_has_no_password_field():
    s = SMTPConfig(host="smtp.example.com", port=587)
    assert not hasattr(s, "password")


def test_smtp_redacted_none():
    assert smtp_redacted_dict(None) is None


def test_smtp_redacted_env_set(monkeypatch):
    monkeypatch.setattr(settings, "smtp_password", "secret")
    s = SMTPConfig(host="smtp.example.com", port=587)
    d = smtp_redacted_dict(s)
    assert d["password"] == "***"


def test_smtp_redacted_env_unset(monkeypatch):
    monkeypatch.setattr(settings, "smtp_password", None)
    s = SMTPConfig(host="smtp.example.com", port=587)
    d = smtp_redacted_dict(s)
    assert d["password"] is None
