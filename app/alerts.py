"""Alert evaluation, coalescing, cooldown, silent-hours, and dispatch."""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .config import SMTPConfig, UPSConfig, load_config
from .notifications.email import EmailSendError, send_alert_email
from .storage import get_redis

logger = logging.getLogger(__name__)

ALERT_COOLDOWN_SECONDS = 1800  # 30 minutes per distinct alert per UPS
REDIS_ALERT_KEY_PREFIX = "ups:alert:last:"
REDIS_PENDING_KEY_PREFIX = "ups:alerts:pending:"  # list of deferred messages
REDIS_HISTORY_KEY_PREFIX = "ups:alerts:history:"  # global history
ALERT_HISTORY_MAX = 500
ALERT_HISTORY_TTL_SECONDS = 30 * 24 * 3600

STATUS_ON_BATTERY_KEYWORDS = {"ONBATT", "ON BATTERY"}
SELFTEST_FAIL_KEYWORDS = {"FAIL", "BADBATT"}

SEV_CRITICAL = "CRITICAL"
SEV_WARNING = "WARNING"
SEV_INFO = "INFO"

TEMP_HIGH_DEFAULT_C = 50.0


@dataclass
class Alert:
    severity: str
    message: str
    code: str
    ups: str
    ts: int

    def hash(self) -> str:
        h = hashlib.sha1(f"{self.ups}|{self.code}|{self.message}".encode()).hexdigest()
        return h[:16]

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.hash()
        return d


def _to_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _extract_leading_number(s: str) -> float | None:
    try:
        return float(s.strip().split()[0])
    except Exception:
        return None


def evaluate_alerts(ups_cfg: UPSConfig, snapshot: dict[str, Any]) -> list[Alert]:
    msgs: list[Alert] = []
    now = int(time.time())
    name = ups_cfg.name

    def add(sev: str, code: str, message: str) -> None:
        msgs.append(Alert(sev, message, code, name, now))

    status = str(snapshot.get("STATUS", "")).upper()
    # ONBATT
    if ups_cfg.alert_on_battery and any(k in status for k in STATUS_ON_BATTERY_KEYWORDS):
        add(SEV_CRITICAL, "ONBATT", f"UPS on battery: status={status}")
    # Runtime low
    if ups_cfg.alert_runtime_low_minutes is not None:
        runtime = _extract_leading_number(str(snapshot.get("TIMELEFT", "")))
        if runtime is not None and runtime <= ups_cfg.alert_runtime_low_minutes:
            add(
                SEV_CRITICAL,
                "RUNTIME_LOW",
                f"Runtime low: {runtime}m <= {ups_cfg.alert_runtime_low_minutes}m",
            )
    # Battery charge low
    if ups_cfg.alert_bcharge_low is not None:
        bcharge = _extract_leading_number(str(snapshot.get("BCHARGE", "")))
        if bcharge is not None and bcharge <= ups_cfg.alert_bcharge_low:
            add(
                SEV_CRITICAL,
                "BCHARGE_LOW",
                f"Battery charge low: {bcharge}% <= {ups_cfg.alert_bcharge_low}%",
            )
    # Load high
    if ups_cfg.alert_loadpct_high is not None:
        loadpct = _extract_leading_number(str(snapshot.get("LOADPCT", "")))
        if loadpct is not None and loadpct >= ups_cfg.alert_loadpct_high:
            add(
                SEV_WARNING,
                "LOAD_HIGH",
                f"Load high: {loadpct}% >= {ups_cfg.alert_loadpct_high}%",
            )
    # REPLACEBATT flag
    replacebatt = str(snapshot.get("REPLACEBATT", "")).upper()
    if replacebatt and replacebatt not in {"NO", "", "0"}:
        add(SEV_WARNING, "REPLACEBATT", "UPS reports battery needs replacement")
    # SELFTEST fail
    selftest = str(snapshot.get("SELFTEST", "")).upper()
    if any(k in selftest for k in SELFTEST_FAIL_KEYWORDS):
        add(SEV_WARNING, "SELFTEST_FAIL", f"Self-test failure: {selftest}")
    # Temperature high
    threshold = ups_cfg.alert_itemp_high or TEMP_HIGH_DEFAULT_C
    itemp = _extract_leading_number(str(snapshot.get("ITEMP", "")))
    if itemp is not None and itemp >= threshold:
        add(
            SEV_WARNING,
            "TEMP_HIGH",
            f"Internal temperature high: {itemp}C >= {threshold}C",
        )

    # Extended alerts based on UI flags
    cfg = load_config()
    ui = cfg.ui if hasattr(cfg, "ui") else None
    if ui:
        r = get_redis()
        if ui.enable_transfer_burst_alert:
            events = r.lrange(f"ups:event:list:{name}", 0, 200)
            onbatt_count = 0
            for ev in events:
                parts = ev.split("|")
                if len(parts) >= 3:
                    try:
                        ts = int(parts[0])
                    except ValueError:
                        continue
                    if now - ts > 3600:
                        continue
                    if parts[1] == "STATUS" and "ONBATT" in parts[2]:
                        onbatt_count += 1
            if onbatt_count >= 3:
                add(
                    SEV_WARNING,
                    "XFER_BURST",
                    f"Frequent battery events: {onbatt_count} in last hour",
                )
        if ui.enable_voltage_deviation_alert:
            linev = _extract_leading_number(str(snapshot.get("LINEV", "")))
            nom = _extract_leading_number(
                str(snapshot.get("NOMINV", snapshot.get("NOMINPUT", "")))
            )
            if linev and nom:
                dev_pct = abs(linev - nom) / nom * 100.0
                dev_key = f"ups:volt:dev:samples:{name}"
                r.lpush(dev_key, f"{dev_pct:.2f}")
                r.ltrim(dev_key, 0, 49)
                samples = r.lrange(dev_key, 0, -1)
                try:
                    avg_dev = sum(float(s) for s in samples) / max(1, len(samples))
                    if avg_dev > 8.0 and len(samples) >= 10:
                        add(
                            SEV_WARNING,
                            "VOLT_DEV",
                            f"High voltage deviation: {avg_dev:.1f}% over {len(samples)} samples",
                        )
                except Exception:
                    pass
    return msgs


def _cooldown_key(alert: Alert) -> str:
    return f"{REDIS_ALERT_KEY_PREFIX}{alert.ups}:{alert.hash()}"


def _in_silent_hours(smtp_cfg: SMTPConfig, now: datetime | None = None) -> bool:
    if smtp_cfg.silent_hours_start is None or smtp_cfg.silent_hours_end is None:
        return False
    if smtp_cfg.silent_hours_start == smtp_cfg.silent_hours_end:
        return False
    if now is None:
        now = datetime.now()
    h = now.hour
    s = smtp_cfg.silent_hours_start
    e = smtp_cfg.silent_hours_end
    if s < e:
        return s <= h < e
    # Wraps past midnight
    return h >= s or h < e


def _persist_history(alerts: list[Alert]) -> None:
    if not alerts:
        return
    r = get_redis()
    pipe = r.pipeline()
    for a in alerts:
        pipe.lpush(
            REDIS_HISTORY_KEY_PREFIX + "all",
            f"{a.ts}|{a.severity}|{a.ups}|{a.code}|{a.message}|{a.hash()}",
        )
        pipe.lpush(
            f"ups:alerts:recent:{a.ups}", f"{a.ts}|{a.severity}|{a.message}"
        )
    pipe.ltrim(REDIS_HISTORY_KEY_PREFIX + "all", 0, ALERT_HISTORY_MAX - 1)
    pipe.expire(REDIS_HISTORY_KEY_PREFIX + "all", ALERT_HISTORY_TTL_SECONDS)
    for a in alerts:
        pipe.ltrim(f"ups:alerts:recent:{a.ups}", 0, 49)
    pipe.execute()


def _defer_for_silent_hours(alerts: list[Alert]) -> None:
    r = get_redis()
    for a in alerts:
        key = REDIS_PENDING_KEY_PREFIX + a.ups
        r.lpush(key, f"{a.ts}|{a.severity}|{a.code}|{a.message}")
    # Keep at most 200 deferred
    for ups in {a.ups for a in alerts}:
        r.ltrim(REDIS_PENDING_KEY_PREFIX + ups, 0, 199)


def drain_deferred(ups_name: str) -> list[Alert]:
    r = get_redis()
    key = REDIS_PENDING_KEY_PREFIX + ups_name
    raw = r.lrange(key, 0, -1)
    r.delete(key)
    out: list[Alert] = []
    for item in raw:
        parts = item.split("|", 3)
        if len(parts) == 4:
            try:
                ts = int(parts[0])
            except ValueError:
                continue
            out.append(Alert(parts[1], parts[3], parts[2], ups_name, ts))
    return out


def dispatch_alerts(
    smtp_cfg: SMTPConfig | None,
    ups_name: str,
    alerts: list[Alert],
    dashboard_url: str = "http://localhost:8000/",
) -> None:
    """Send a coalesced email containing all alerts for one UPS."""
    if not smtp_cfg or not alerts:
        return
    payload = [
        {"severity": a.severity, "message": a.message, "code": a.code}
        for a in alerts
    ]
    try:
        send_alert_email(smtp_cfg, ups_name, payload, dashboard_url=dashboard_url)
    except EmailSendError as e:
        logger.warning("Alert email failed for %s: %s", ups_name, e)


def process_alerts(ups_cfg: UPSConfig, snapshot: dict[str, Any]) -> list[Alert]:
    """Evaluate alerts, apply cooldown + silent hours, dispatch email.

    Returns the list of alerts that were considered fresh (not cooled down).
    """
    cfg = load_config()
    all_alerts = evaluate_alerts(ups_cfg, snapshot)
    if not all_alerts:
        return []
    r = get_redis()
    fresh: list[Alert] = []
    now = int(time.time())
    for a in all_alerts:
        key = _cooldown_key(a)
        if not r.get(key):
            fresh.append(a)
            r.set(key, now, ex=ALERT_COOLDOWN_SECONDS)
    if not fresh:
        return []
    _persist_history(fresh)
    if not cfg.smtp:
        return fresh
    # Silent hours filter: keep CRITICAL, defer others
    if _in_silent_hours(cfg.smtp):
        critical = [a for a in fresh if a.severity == SEV_CRITICAL]
        deferred = [a for a in fresh if a.severity != SEV_CRITICAL]
        if deferred:
            _defer_for_silent_hours(deferred)
        if critical:
            dispatch_alerts(cfg.smtp, ups_cfg.name, critical)
    else:
        # Also flush any deferred alerts for this UPS
        deferred = drain_deferred(ups_cfg.name)
        dispatch_alerts(cfg.smtp, ups_cfg.name, fresh + deferred)
    return fresh


def emit_info(ups_name: str, code: str, message: str) -> None:
    """Record and dispatch a single INFO alert (e.g. recovery events)."""
    alert = Alert(SEV_INFO, message, code, ups_name, int(time.time()))
    r = get_redis()
    if r.get(_cooldown_key(alert)):
        return
    r.set(_cooldown_key(alert), int(time.time()), ex=ALERT_COOLDOWN_SECONDS)
    _persist_history([alert])
    cfg = load_config()
    if cfg.smtp:
        if _in_silent_hours(cfg.smtp):
            _defer_for_silent_hours([alert])
        else:
            dispatch_alerts(cfg.smtp, ups_name, [alert])
