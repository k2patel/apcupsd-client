"""Integration tests for UPS/alerts/events API routes."""
from __future__ import annotations

import json
import time


def _add_ups(client, name="u1", host="192.168.1.10"):
    return client.post(
        "/api/config/ups",
        json={"name": name, "host": host, "port": 3551, "interval_seconds": 30},
    )


def test_ups_list_empty(authed_client):
    r = authed_client.get("/api/ups")
    assert r.status_code == 200
    assert r.json() == []


def test_ups_list_after_add(authed_client):
    _add_ups(authed_client)
    r = authed_client.get("/api/ups")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "u1"


def test_fleet_overview_empty(authed_client):
    r = authed_client.get("/api/ups/fleet/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["counts"]["online"] == 0


def test_fleet_overview_with_data(authed_client, fake_redis):
    _add_ups(authed_client, name="u1")
    _add_ups(authed_client, name="u2", host="192.168.1.20")
    fake_redis.hset("ups:snap:u1", mapping={"STATUS": "ONLINE", "DERIVED_WATTS": "200", "TIMELEFT": "40"})
    fake_redis.hset("ups:snap:u2", mapping={"STATUS": "ONBATT", "DERIVED_WATTS": "150", "TIMELEFT": "10"})
    r = authed_client.get("/api/ups/fleet/overview")
    body = r.json()
    assert body["total"] == 2
    assert body["counts"]["online"] == 1
    assert body["counts"]["on_battery"] == 1
    assert body["total_watts"] == 350.0
    assert body["min_timeleft_minutes"] == 10.0


def test_fleet_overview_detects_offline(authed_client, fake_redis):
    _add_ups(authed_client, name="u1")
    fake_redis.set("ups:health:offline:u1", "1")
    fake_redis.hset("ups:snap:u1", mapping={"STATUS": "ONLINE"})
    r = authed_client.get("/api/ups/fleet/overview")
    body = r.json()
    assert body["counts"]["offline"] == 1


def test_ups_status(authed_client, fake_redis):
    _add_ups(authed_client)
    fake_redis.hset("ups:snap:u1", mapping={"STATUS": "ONLINE", "_ts": "100"})
    r = authed_client.get("/api/ups/u1")
    assert r.status_code == 200
    body = r.json()
    assert body["STATUS"] == "ONLINE"


def test_ups_history(authed_client, fake_redis):
    _add_ups(authed_client)
    now = int(time.time())
    fake_redis.rpush(
        "ups:hist:u1",
        json.dumps({"ts": now, "data": {"STATUS": "ONLINE", "LOADPCT": "50"}}),
    )
    r = authed_client.get("/api/ups/u1/history")
    body = r.json()
    assert len(body) == 1
    assert body[0]["data"]["STATUS"] == "ONLINE"


def test_ups_metric(authed_client, fake_redis):
    _add_ups(authed_client)
    now = int(time.time())
    for v in (10, 20, 30):
        fake_redis.rpush(
            "ups:hist:u1",
            json.dumps({"ts": now, "data": {"LOADPCT": str(v)}}),
        )
    r = authed_client.get("/api/ups/u1/metric/LOADPCT")
    body = r.json()
    assert len(body) == 3
    assert body[0]["value"] == 10.0


def test_ups_events(authed_client, fake_redis):
    _add_ups(authed_client)
    fake_redis.lpush("ups:event:list:u1", f"{int(time.time())}|STATUS|ONLINE")
    r = authed_client.get("/api/ups/u1/events")
    body = r.json()
    assert len(body) == 1
    assert body[0]["type"] == "STATUS"


def test_ups_energy_empty(authed_client):
    _add_ups(authed_client)
    r = authed_client.get("/api/ups/u1/energy")
    assert r.status_code == 200
    body = r.json()
    assert body["kwh_today"] is None


def test_ups_energy_with_data(authed_client, fake_redis):
    _add_ups(authed_client)
    day_str = time.strftime("%Y%m%d")
    fake_redis.set(f"ups:energy:u1:{day_str}", "3600000")  # 1 kWh
    r = authed_client.get("/api/ups/u1/energy")
    body = r.json()
    assert body["kwh_today"] == 1.0


def test_ups_energy_uses_four_decimal_cost_rate(authed_client, fake_redis):
    _add_ups(authed_client)
    authed_client.put(
        "/api/config/ui",
        json={"show_energy": True, "energy_cost_per_kwh": 0.1365},
    )
    day_str = time.strftime("%Y%m%d")
    fake_redis.set(f"ups:energy:u1:{day_str}", "7200000")  # 2 kWh

    r = authed_client.get("/api/ups/u1/energy")

    assert r.status_code == 200
    body = r.json()
    assert body["kwh_today"] == 2.0
    assert body["cost_today"] == 0.273


def test_ups_health(authed_client, fake_redis):
    _add_ups(authed_client)
    fake_redis.set("ups:health:last_ok:u1", "12345")
    r = authed_client.get("/api/ups/u1/health")
    body = r.json()
    assert body["online"] is True
    assert body["last_ok_ts"] == 12345


def test_ups_health_offline(authed_client, fake_redis):
    _add_ups(authed_client)
    fake_redis.set("ups:health:offline:u1", "1")
    fake_redis.set("ups:health:fail_count:u1", "3")
    r = authed_client.get("/api/ups/u1/health")
    body = r.json()
    assert body["online"] is False
    assert body["fail_count"] == 3


def test_ui_tile_layout_preserves_tile_and_card_sizes(authed_client):
    payload = {
        "types": {"watts_usage": "line"},
        "order": ["load_pct", "watts_usage"],
        "hidden": [],
        "custom": [],
        "positions": {
            "load_pct": {"left": 20, "top": 40, "width": 260, "height": 180},
            "watts_usage": {"left": 320, "top": 40, "width": 520, "height": 260},
        },
        "card_size": {"width": 900, "height": 460},
    }

    r = authed_client.post("/api/ups/u1/ui_tiles", json=payload)
    assert r.status_code == 200

    r = authed_client.get("/api/ups/u1/ui_tiles")
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["positions"]["load_pct"]["width"] == 260
    assert body["positions"]["load_pct"]["height"] == 180
    assert body["positions"]["watts_usage"]["width"] == 520
    assert body["positions"]["watts_usage"]["height"] == 260
    assert body["card_size"] == {"width": 900, "height": 460}


def test_ui_tile_layout_reports_missing_server_config(authed_client):
    r = authed_client.get("/api/ups/u1/ui_tiles")

    assert r.status_code == 200
    assert r.json()["exists"] is False


def test_battery_health_empty(authed_client):
    _add_ups(authed_client)
    r = authed_client.get("/api/ups/u1/battery_health")
    assert r.status_code == 200


def test_events_list_empty(authed_client):
    r = authed_client.get("/api/events")
    assert r.status_code == 200
    assert r.json() == []


def test_events_list_all(authed_client, fake_redis):
    _add_ups(authed_client, name="u1")
    _add_ups(authed_client, name="u2", host="192.168.1.20")
    now = int(time.time())
    fake_redis.lpush("ups:event:list:u1", f"{now}|STATUS|ONLINE")
    fake_redis.lpush("ups:event:list:u2", f"{now - 10}|XFER|Low voltage")
    r = authed_client.get("/api/events")
    body = r.json()
    assert len(body) == 2
    # Sorted by ts desc
    assert body[0]["ts"] >= body[1]["ts"]


def test_events_filter_by_ups(authed_client, fake_redis):
    _add_ups(authed_client, name="u1")
    _add_ups(authed_client, name="u2", host="192.168.1.20")
    now = int(time.time())
    fake_redis.lpush("ups:event:list:u1", f"{now}|STATUS|ONLINE")
    fake_redis.lpush("ups:event:list:u2", f"{now}|STATUS|ONBATT")
    r = authed_client.get("/api/events?ups=u1")
    body = r.json()
    assert all(e["ups"] == "u1" for e in body)


def test_events_filter_by_kind(authed_client, fake_redis):
    _add_ups(authed_client)
    now = int(time.time())
    fake_redis.lpush("ups:event:list:u1", f"{now}|STATUS|ONLINE")
    fake_redis.lpush("ups:event:list:u1", f"{now}|XFER|Low voltage")
    r = authed_client.get("/api/events?kind=XFER")
    body = r.json()
    assert all(e["type"] == "XFER" for e in body)


def test_alerts_list_empty(authed_client):
    r = authed_client.get("/api/alerts")
    assert r.status_code == 200
    assert r.json() == []


def test_alerts_list_with_data(authed_client, fake_redis):
    now = int(time.time())
    fake_redis.lpush(
        "ups:alerts:history:all",
        f"{now}|CRITICAL|u1|ONBATT|On battery power|abc123",
    )
    r = authed_client.get("/api/alerts")
    body = r.json()
    assert len(body) == 1
    assert body[0]["severity"] == "CRITICAL"
    assert body[0]["ups"] == "u1"
    assert body[0]["acked_ts"] is None


def test_alerts_filter_by_severity(authed_client, fake_redis):
    now = int(time.time())
    fake_redis.lpush("ups:alerts:history:all", f"{now}|CRITICAL|u1|C|x|a")
    fake_redis.lpush("ups:alerts:history:all", f"{now}|WARNING|u1|W|y|b")
    r = authed_client.get("/api/alerts?severity=warning")
    body = r.json()
    assert all(a["severity"] == "WARNING" for a in body)


def test_alerts_active_filters_acked(authed_client, fake_redis):
    now = int(time.time())
    fake_redis.lpush(
        "ups:alerts:history:all",
        f"{now}|CRITICAL|u1|A|msg|alert1",
    )
    fake_redis.lpush(
        "ups:alerts:history:all",
        f"{now}|CRITICAL|u1|B|msg2|alert2",
    )
    fake_redis.set("ups:alerts:ack:alert1", str(now))
    r = authed_client.get("/api/alerts/active")
    body = r.json()
    assert all(a["id"] != "alert1" for a in body)


def test_alerts_ack(authed_client, fake_redis):
    r = authed_client.post("/api/alerts/myid/ack")
    assert r.status_code == 200
    assert fake_redis.get("ups:alerts:ack:myid") is not None


def test_healthz_no_auth_required(app_client):
    r = app_client.get("/healthz")
    assert r.status_code == 200


def test_readyz_reports_redis_status(app_client, fake_redis):
    r = app_client.get("/readyz")
    assert r.status_code in (200, 503)


def test_metrics_endpoint(app_client, fake_redis):
    r = app_client.get("/metrics")
    assert r.status_code == 200
    assert "ups_" in r.text or "# HELP" in r.text
