"""Alert rules, cooldown, silent hours, deferred drain."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from app.alerts import (
    SEV_CRITICAL,
    SEV_INFO,
    SEV_WARNING,
    Alert,
    _defer_for_silent_hours,
    _in_silent_hours,
    drain_deferred,
    emit_info,
    evaluate_alerts,
    process_alerts,
)
from app.config import SMTPConfig, UPSConfig


def _ups(**overrides):
    base = dict(
        name="u1", host="192.168.1.10", port=3551, interval_seconds=30,
        alert_on_battery=True,
        alert_runtime_low_minutes=10.0,
        alert_bcharge_low=20.0,
        alert_loadpct_high=80.0,
        alert_itemp_high=45.0,
    )
    base.update(overrides)
    return UPSConfig(**base)


def _snap(**overrides):
    base = dict(
        STATUS="ONLINE", LOADPCT="25.0", BCHARGE="100.0",
        TIMELEFT="60.0 Minutes", ITEMP="30.0",
        SELFTEST="NO", REPLACEBATT="NO",
    )
    base.update(overrides)
    return base


def test_no_alerts_normal_state(fake_redis, clean_config_cache):
    alerts = evaluate_alerts(_ups(), _snap())
    assert alerts == []


def test_onbatt_critical(fake_redis, clean_config_cache):
    alerts = evaluate_alerts(_ups(), _snap(STATUS="ONBATT"))
    assert any(a.code == "ONBATT" and a.severity == SEV_CRITICAL for a in alerts)


def test_runtime_low_critical(fake_redis, clean_config_cache):
    alerts = evaluate_alerts(_ups(), _snap(TIMELEFT="5.0 Minutes"))
    assert any(a.code == "RUNTIME_LOW" and a.severity == SEV_CRITICAL for a in alerts)


def test_bcharge_low_critical(fake_redis, clean_config_cache):
    alerts = evaluate_alerts(_ups(), _snap(BCHARGE="15.0"))
    assert any(a.code == "BCHARGE_LOW" and a.severity == SEV_CRITICAL for a in alerts)


def test_load_high_warning(fake_redis, clean_config_cache):
    alerts = evaluate_alerts(_ups(), _snap(LOADPCT="90.0"))
    assert any(a.code == "LOAD_HIGH" and a.severity == SEV_WARNING for a in alerts)


def test_replacebatt_warning(fake_redis, clean_config_cache):
    alerts = evaluate_alerts(_ups(), _snap(REPLACEBATT="YES"))
    assert any(a.code == "REPLACEBATT" and a.severity == SEV_WARNING for a in alerts)


def test_selftest_fail_warning(fake_redis, clean_config_cache):
    alerts = evaluate_alerts(_ups(), _snap(SELFTEST="FAIL"))
    assert any(a.code == "SELFTEST_FAIL" and a.severity == SEV_WARNING for a in alerts)


def test_temp_high_warning(fake_redis, clean_config_cache):
    alerts = evaluate_alerts(_ups(), _snap(ITEMP="55.0"))
    assert any(a.code == "TEMP_HIGH" and a.severity == SEV_WARNING for a in alerts)


def test_multiple_alerts_coalesced(fake_redis, clean_config_cache):
    alerts = evaluate_alerts(
        _ups(),
        _snap(STATUS="ONBATT", BCHARGE="10.0", LOADPCT="95.0"),
    )
    codes = {a.code for a in alerts}
    assert "ONBATT" in codes
    assert "BCHARGE_LOW" in codes
    assert "LOAD_HIGH" in codes


def test_alert_hash_stable():
    a1 = Alert(SEV_CRITICAL, "msg", "CODE", "u1", 100)
    a2 = Alert(SEV_CRITICAL, "msg", "CODE", "u1", 999)
    assert a1.hash() == a2.hash()  # hash doesn't depend on ts


def test_silent_hours_same_day():
    smtp = SMTPConfig(host="x", port=25, silent_hours_start=22, silent_hours_end=23)
    now = datetime(2024, 1, 1, 22, 30)
    assert _in_silent_hours(smtp, now) is True
    now2 = datetime(2024, 1, 1, 23, 30)
    assert _in_silent_hours(smtp, now2) is False


def test_silent_hours_wrap_midnight():
    smtp = SMTPConfig(host="x", port=25, silent_hours_start=22, silent_hours_end=7)
    assert _in_silent_hours(smtp, datetime(2024, 1, 1, 23, 0)) is True
    assert _in_silent_hours(smtp, datetime(2024, 1, 1, 3, 0)) is True
    assert _in_silent_hours(smtp, datetime(2024, 1, 1, 10, 0)) is False


def test_silent_hours_unset():
    smtp = SMTPConfig(host="x", port=25)
    assert _in_silent_hours(smtp) is False


def test_defer_and_drain(fake_redis):
    a = Alert(SEV_WARNING, "msg1", "CODE1", "u1", 100)
    b = Alert(SEV_WARNING, "msg2", "CODE2", "u1", 101)
    _defer_for_silent_hours([a, b])
    drained = drain_deferred("u1")
    assert len(drained) == 2
    codes = {x.code for x in drained}
    assert codes == {"CODE1", "CODE2"}
    # Second drain is empty
    assert drain_deferred("u1") == []


def test_cooldown_suppresses_second_call(fake_redis, clean_config_cache):
    # Avoid real SMTP: no smtp in config
    with patch("app.alerts.dispatch_alerts"):
        fresh = process_alerts(_ups(), _snap(STATUS="ONBATT"))
        assert any(a.code == "ONBATT" for a in fresh)
        # Immediate second call: cooled down
        fresh2 = process_alerts(_ups(), _snap(STATUS="ONBATT"))
        assert all(a.code != "ONBATT" for a in fresh2)


def test_emit_info_writes_history(fake_redis, clean_config_cache):
    with patch("app.alerts.dispatch_alerts"):
        emit_info("u1", "REACHABLE", "u1 came back online")
        entries = fake_redis.lrange("ups:alerts:history:all", 0, -1)
        assert any("REACHABLE" in e for e in entries)
