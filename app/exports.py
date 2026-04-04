"""CSV export helpers."""
from __future__ import annotations

import csv
import io
import time
from collections.abc import AsyncIterator, Iterable

from .storage import get_history, get_redis


def _csv_row(writer_buf: io.StringIO, writer: csv.writer, row: Iterable) -> str:
    writer.writerow(row)
    out = writer_buf.getvalue()
    writer_buf.seek(0)
    writer_buf.truncate()
    return out


async def export_history_csv(ups_name: str, since_days: int = 7) -> AsyncIterator[str]:
    history = await get_history(ups_name, since_seconds=since_days * 24 * 3600)
    buf = io.StringIO()
    writer = csv.writer(buf)
    yield _csv_row(buf, writer, ["ts", "status", "loadpct", "bcharge", "timeleft", "linev", "derived_watts"])
    for item in history:
        d = item.get("data", {})
        yield _csv_row(
            buf,
            writer,
            [
                item.get("ts"),
                d.get("STATUS", ""),
                d.get("LOADPCT", ""),
                d.get("BCHARGE", ""),
                d.get("TIMELEFT", ""),
                d.get("LINEV", ""),
                d.get("DERIVED_WATTS", ""),
            ],
        )


async def export_events_csv(ups_name: str, since_days: int = 7) -> AsyncIterator[str]:
    r = get_redis()
    raw = r.lrange(f"ups:event:list:{ups_name}", 0, -1)
    cutoff = int(time.time()) - since_days * 24 * 3600
    buf = io.StringIO()
    writer = csv.writer(buf)
    yield _csv_row(buf, writer, ["ts", "type", "detail"])
    for item in raw:
        parts = item.split("|", 2)
        if len(parts) != 3:
            continue
        try:
            ts = int(parts[0])
        except ValueError:
            continue
        if ts < cutoff:
            continue
        yield _csv_row(buf, writer, [ts, parts[1], parts[2]])


async def export_energy_csv(ups_name: str, since_days: int = 7) -> AsyncIterator[str]:
    r = get_redis()
    buf = io.StringIO()
    writer = csv.writer(buf)
    yield _csv_row(buf, writer, ["date", "kwh"])
    now = time.time()
    for i in range(since_days):
        day_ts = now - i * 86400
        day_str = time.strftime("%Y%m%d", time.localtime(day_ts))
        date_disp = time.strftime("%Y-%m-%d", time.localtime(day_ts))
        watt_seconds = r.get(f"ups:energy:{ups_name}:{day_str}")
        if watt_seconds:
            try:
                kwh = float(watt_seconds) / 3600.0 / 1000.0
                yield _csv_row(buf, writer, [date_disp, f"{kwh:.4f}"])
            except ValueError:
                continue
