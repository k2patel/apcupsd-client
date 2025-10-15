from __future__ import annotations
import smtplib
import ssl
import os
import time
from email.message import EmailMessage
from typing import Dict, Any, List
from .config import load_config, SMTPConfig, UPSConfig
from .storage import get_redis

ALERT_COOLDOWN_SECONDS = 1800  # 30 minutes per distinct alert per UPS
REDIS_ALERT_KEY_PREFIX = "ups:alert:last:"

STATUS_ON_BATTERY_KEYWORDS = {"ONBATT", "ON BATTERY"}

 
def evaluate_alerts(ups_cfg: UPSConfig, snapshot: Dict[str, Any]) -> List[str]:
    messages: List[str] = []
    # Load % high
    if ups_cfg.alert_loadpct_high is not None:
        loadpct = _to_float(snapshot.get('LOADPCT'))
        if loadpct is not None and loadpct >= ups_cfg.alert_loadpct_high:
            messages.append(
                "Load percentage high: "
                f"{loadpct}% >= {ups_cfg.alert_loadpct_high}%"
            )
    # Battery charge low
    if ups_cfg.alert_bcharge_low is not None:
        bcharge = _to_float(snapshot.get('BCHARGE'))
        if bcharge is not None and bcharge <= ups_cfg.alert_bcharge_low:
            messages.append(
                "Battery charge low: "
                f"{bcharge}% <= {ups_cfg.alert_bcharge_low}%"
            )
    # On battery status
    if ups_cfg.alert_on_battery:
        status = str(snapshot.get('STATUS', '')).upper()
        if any(k in status for k in STATUS_ON_BATTERY_KEYWORDS):
            messages.append(f"UPS on battery: status={status}")
    # Runtime low
    if ups_cfg.alert_runtime_low_minutes is not None:
        timeleft = snapshot.get('TIMELEFT')
        # TIMELEFT often like '15.0 Minutes' -> attempt parse
        runtime = _extract_leading_number(str(timeleft))
        if (
            runtime is not None
            and runtime <= ups_cfg.alert_runtime_low_minutes
        ):
            messages.append(
                "Runtime low: "
                f"{runtime}m <= {ups_cfg.alert_runtime_low_minutes}m"
            )
    # Extended alerts based on global UI flags
    cfg = load_config()
    ui = cfg.ui if hasattr(cfg, 'ui') else None
    if ui:
        r = get_redis()
        # Transfer burst: count status ONBATT events in last hour
        if ui.enable_transfer_burst_alert:
            # We rely on event list already capturing STATUS transitions
            events = r.lrange(f"ups:event:list:{ups_cfg.name}", 0, 200)
            now = int(time.time())
            onbatt_count = 0
            for ev in events:
                parts = ev.split('|')
                if len(parts) >= 3:
                    try:
                        ts = int(parts[0])
                    except ValueError:
                        continue
                    if now - ts > 3600:
                        continue
                    if parts[1] == 'STATUS' and 'ONBATT' in parts[2]:
                        onbatt_count += 1
            if onbatt_count >= 3:  # threshold heuristically chosen
                messages.append(
                    f"Frequent battery events: {onbatt_count} in last hour"
                )
        # Voltage deviation: track LINEV vs nominal, average deviation window
        if ui.enable_voltage_deviation_alert:
            linev = _extract_leading_number(str(snapshot.get('LINEV', '')))
            nom = _extract_leading_number(
                str(snapshot.get('NOMINV', snapshot.get('NOMINPUT', '')))
            )
            if linev and nom:
                dev_pct = abs(linev - nom) / nom * 100.0
                dev_key = f"ups:volt:dev:samples:{ups_cfg.name}"
                r.lpush(dev_key, f"{dev_pct:.2f}")
                r.ltrim(dev_key, 0, 49)
                samples = r.lrange(dev_key, 0, -1)
                try:
                    avg_dev = sum(float(s) for s in samples) / max(
                        1, len(samples)
                    )
                    if avg_dev > 8.0 and len(samples) >= 10:
                        messages.append(
                            "High average voltage deviation: "
                            f"{avg_dev:.1f}% over {len(samples)} samples"
                        )
                except Exception:
                    pass
    return messages

 
def _to_float(val) -> float | None:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None

 
def _extract_leading_number(s: str) -> float | None:
    try:
        part = s.strip().split()[0]
        return float(part)
    except Exception:
        return None

 
def _cooldown_key(ups_name: str, msg: str) -> str:
    return f"{REDIS_ALERT_KEY_PREFIX}{ups_name}:{hash(msg)}"

 
def send_alert_email(smtp_cfg: SMTPConfig, ups_name: str, messages: List[str]):
    password = smtp_cfg.password or os.environ.get('SMTP_PASSWORD')
    if not smtp_cfg.to_addrs:
        return
    subject = f"{smtp_cfg.subject_prefix} {ups_name} alert"
    body = "\n".join(messages)
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = smtp_cfg.from_addr or (smtp_cfg.username or 'ups@example')
    msg['To'] = ", ".join(smtp_cfg.to_addrs)
    msg.set_content(body)

    if smtp_cfg.use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            smtp_cfg.host, smtp_cfg.port, context=context, timeout=30
        ) as server:
            if smtp_cfg.username and password:
                server.login(smtp_cfg.username, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_cfg.host, smtp_cfg.port, timeout=30) as server:
            if smtp_cfg.use_tls:
                server.starttls(context=ssl.create_default_context())
            if smtp_cfg.username and password:
                server.login(smtp_cfg.username, password)
            server.send_message(msg)

 
def process_alerts(ups_cfg: UPSConfig, snapshot: Dict[str, Any]):
    cfg = load_config()
    if not cfg.smtp:
        return
    msgs = evaluate_alerts(ups_cfg, snapshot)
    if not msgs:
        return
    r = get_redis()
    to_send: List[str] = []
    now = int(time.time())
    for m in msgs:
        key = _cooldown_key(ups_cfg.name, m)
        if not r.get(key):
            to_send.append(m)
            r.set(key, now, ex=ALERT_COOLDOWN_SECONDS)
    if to_send:
        # Store recent alerts with timestamp for health reporting
        recent_key = f"ups:alerts:recent:{ups_cfg.name}"
        pipe = r.pipeline()
        for m in to_send:
            pipe.lpush(recent_key, f"{now}|{m}")
        pipe.ltrim(recent_key, 0, 49)  # keep last 50
        pipe.execute()
        send_alert_email(cfg.smtp, ups_cfg.name, to_send)
