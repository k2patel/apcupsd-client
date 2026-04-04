"""CSV exports shape and content."""
from __future__ import annotations

import json
import time

import pytest

from app.exports import export_energy_csv, export_events_csv, export_history_csv


async def _collect(gen):
    return [chunk async for chunk in gen]


async def test_history_export_header_only_when_empty(fake_redis):
    rows = await _collect(export_history_csv("u1", since_days=1))
    assert len(rows) == 1
    assert rows[0].startswith("ts,status,loadpct,bcharge,timeleft,linev,derived_watts")


async def test_history_export_with_data(fake_redis):
    now = int(time.time())
    entry = {"ts": now, "data": {
        "STATUS": "ONLINE", "LOADPCT": "25.0",
        "BCHARGE": "100", "TIMELEFT": "45",
        "LINEV": "120", "DERIVED_WATTS": "225",
    }}
    fake_redis.rpush("ups:hist:u1", json.dumps(entry))
    rows = await _collect(export_history_csv("u1", since_days=1))
    assert len(rows) == 2  # header + 1
    data_row = rows[1]
    assert "ONLINE" in data_row
    assert "225" in data_row


async def test_events_export_header_only_empty(fake_redis):
    rows = await _collect(export_events_csv("u1", since_days=1))
    assert len(rows) == 1
    assert rows[0].startswith("ts,type,detail")


async def test_events_export_with_data(fake_redis):
    now = int(time.time())
    fake_redis.rpush("ups:event:list:u1", f"{now}|STATUS|ONBATT")
    fake_redis.rpush("ups:event:list:u1", f"{now}|XFER|Low voltage")
    rows = await _collect(export_events_csv("u1", since_days=1))
    assert len(rows) == 3
    body = "\n".join(rows)
    assert "STATUS" in body
    assert "ONBATT" in body
    assert "XFER" in body


async def test_events_export_applies_cutoff(fake_redis):
    # Event older than 1 day should be filtered out
    old_ts = int(time.time()) - (2 * 24 * 3600)
    fake_redis.rpush("ups:event:list:u1", f"{old_ts}|STATUS|OLD")
    rows = await _collect(export_events_csv("u1", since_days=1))
    assert len(rows) == 1  # header only


async def test_energy_export_header(fake_redis):
    rows = await _collect(export_energy_csv("u1", since_days=3))
    assert rows[0].startswith("date,kwh")


async def test_energy_export_with_data(fake_redis):
    day_str = time.strftime("%Y%m%d")
    fake_redis.set(f"ups:energy:u1:{day_str}", "3600000")  # 3,600,000 Ws = 1 kWh
    rows = await _collect(export_energy_csv("u1", since_days=1))
    # header + today's data
    assert len(rows) >= 2
    assert "1.0000" in "\n".join(rows)
