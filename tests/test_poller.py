"""Connection health transitions + battery history append."""
from __future__ import annotations

import json
import time

from app.poller import (
    HEALTH_OFFLINE_MIN_SECONDS,
    _get_offline_threshold,
    _record_poll_failure,
    _record_poll_success,
)


def test_offline_threshold_floor():
    assert _get_offline_threshold(30) == HEALTH_OFFLINE_MIN_SECONDS
    assert _get_offline_threshold(60) == 180


def test_offline_threshold_scales_with_interval():
    assert _get_offline_threshold(120) == 360


def test_poll_success_sets_health_key(fake_redis):
    snap = {"BCHARGE": "100", "TIMELEFT": "45 Minutes", "BATTV": "13.5", "NOMBATTV": "12"}
    _record_poll_success("u1", snap, 30)
    assert fake_redis.get("ups:health:last_ok:u1") is not None
    assert fake_redis.get("ups:health:fail_count:u1") is None


def test_poll_success_clears_fail_count(fake_redis):
    fake_redis.set("ups:health:fail_count:u1", "5")
    _record_poll_success("u1", {}, 30)
    assert fake_redis.get("ups:health:fail_count:u1") is None


def test_poll_success_recovery_emits_info(fake_redis, clean_config_cache):
    from unittest.mock import patch
    fake_redis.set("ups:health:offline:u1", "1")
    with patch("app.alerts.dispatch_alerts"):
        _record_poll_success("u1", {}, 30)
    # Offline flag cleared
    assert fake_redis.get("ups:health:offline:u1") is None
    # History has recovery entry
    entries = fake_redis.lrange("ups:alerts:history:all", 0, -1)
    assert any("REACHABLE" in e for e in entries)


def test_battery_history_appended(fake_redis):
    snap = {"BCHARGE": "100", "TIMELEFT": "45 Minutes", "BATTV": "13.5", "NOMBATTV": "12"}
    _record_poll_success("u1", snap, 30)
    entries = fake_redis.lrange("ups:battery:history:u1", 0, -1)
    assert len(entries) == 1
    parsed = json.loads(entries[0])
    assert parsed["bcharge"] == 100.0
    assert parsed["battv"] == 13.5


def test_battery_history_throttled_at_60s(fake_redis):
    snap = {"BCHARGE": "100", "TIMELEFT": "45", "BATTV": "13", "NOMBATTV": "12"}
    _record_poll_success("u1", snap, 30)
    # Immediately call again: no new sample (60s gate)
    _record_poll_success("u1", snap, 30)
    entries = fake_redis.lrange("ups:battery:history:u1", 0, -1)
    assert len(entries) == 1


def test_poll_failure_increments_count(fake_redis):
    _record_poll_failure("u1", 30, "timeout")
    assert fake_redis.get("ups:health:fail_count:u1") == "1"
    _record_poll_failure("u1", 30, "timeout")
    assert fake_redis.get("ups:health:fail_count:u1") == "2"


def test_poll_failure_emits_offline_after_threshold(fake_redis, clean_config_cache):
    from unittest.mock import patch
    # Simulate an old last_ok so we cross the threshold
    fake_redis.set("ups:health:last_ok:u1", str(int(time.time()) - 1000))
    with patch("app.alerts.dispatch_alerts"):
        _record_poll_failure("u1", 30, "connection refused")
    # Offline flag now set
    assert fake_redis.get("ups:health:offline:u1") == "1"
    # Alert recorded in global history
    entries = fake_redis.lrange("ups:alerts:history:all", 0, -1)
    assert any("COMMLOST" in e for e in entries)


def test_poll_failure_idempotent_while_offline(fake_redis, clean_config_cache):
    from unittest.mock import patch
    fake_redis.set("ups:health:last_ok:u1", str(int(time.time()) - 1000))
    with patch("app.alerts.dispatch_alerts"):
        _record_poll_failure("u1", 30, "x")
        _record_poll_failure("u1", 30, "x")
    # Only one COMMLOST alert
    entries = fake_redis.lrange("ups:alerts:history:all", 0, -1)
    assert sum("COMMLOST" in e for e in entries) == 1


def test_poll_failure_below_threshold_no_alert(fake_redis, clean_config_cache):
    from unittest.mock import patch
    # Recent last_ok -> under threshold
    fake_redis.set("ups:health:last_ok:u1", str(int(time.time())))
    with patch("app.alerts.dispatch_alerts"):
        _record_poll_failure("u1", 30, "transient")
    assert fake_redis.get("ups:health:offline:u1") is None
    entries = fake_redis.lrange("ups:alerts:history:all", 0, -1)
    assert not any("COMMLOST" in e for e in entries)
