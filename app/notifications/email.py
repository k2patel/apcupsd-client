"""SMTP email sending with retry, batching, and HTML templates."""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import SMTPConfig
from ..settings import settings

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "emails"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

SEVERITY_COLORS = {
    "CRITICAL": "#c0392b",
    "WARNING": "#e67e22",
    "INFO": "#2980b9",
}


class EmailSendError(Exception):
    pass


def _resolve_password(smtp_cfg: SMTPConfig) -> str | None:
    # Password is never stored in Redis; always from env var
    return settings.smtp_password


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((smtplib.SMTPException, OSError)),
)
def _send_raw(smtp_cfg: SMTPConfig, msg: EmailMessage) -> None:
    password = _resolve_password(smtp_cfg)
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


def send_alert_email(
    smtp_cfg: SMTPConfig,
    ups_name: str,
    alerts: list[dict[str, Any]],
    dashboard_url: str = "http://localhost:8000/",
) -> None:
    """Send a single HTML email coalescing multiple alerts for a UPS."""
    if not smtp_cfg.to_addrs or not alerts:
        return
    top_severity = _pick_top_severity(alerts)
    subject = f"{smtp_cfg.subject_prefix} [{top_severity}] {ups_name}"
    template = _env.get_template("alert.html")
    html = template.render(
        ups_name=ups_name,
        alerts=alerts,
        top_severity=top_severity,
        color=SEVERITY_COLORS.get(top_severity, "#555"),
        dashboard_url=dashboard_url,
        sent_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    text_body = "\n".join(
        f"[{a.get('severity', 'INFO')}] {a.get('message', '')}" for a in alerts
    )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_cfg.from_addr or (smtp_cfg.username or "ups@example.local")
    msg["To"] = ", ".join(smtp_cfg.to_addrs)
    msg.set_content(text_body)
    msg.add_alternative(html, subtype="html")
    try:
        _send_raw(smtp_cfg, msg)
    except RetryError as e:
        raise EmailSendError(f"SMTP send failed after retries: {e}") from e
    except Exception as e:  # noqa: BLE001 - surface as domain error
        raise EmailSendError(f"SMTP send failed: {e}") from e


def send_test_email(smtp_cfg: SMTPConfig) -> None:
    if not smtp_cfg.to_addrs:
        raise EmailSendError("No recipients configured")
    msg = EmailMessage()
    msg["Subject"] = f"{smtp_cfg.subject_prefix} Test email"
    msg["From"] = smtp_cfg.from_addr or (smtp_cfg.username or "ups@example.local")
    msg["To"] = ", ".join(smtp_cfg.to_addrs)
    msg.set_content(
        "This is a test message from your APC UPS Dashboard.\n"
        f"Sent at {datetime.now().isoformat()}"
    )
    try:
        _send_raw(smtp_cfg, msg)
    except Exception as e:  # noqa: BLE001
        raise EmailSendError(str(e)) from e


def send_daily_summary(
    smtp_cfg: SMTPConfig,
    summary: dict[str, Any],
) -> None:
    if not smtp_cfg.to_addrs:
        return
    template = _env.get_template("summary.html")
    html = template.render(summary=summary, sent_at=datetime.now().isoformat())
    msg = EmailMessage()
    msg["Subject"] = f"{smtp_cfg.subject_prefix} Daily summary"
    msg["From"] = smtp_cfg.from_addr or (smtp_cfg.username or "ups@example.local")
    msg["To"] = ", ".join(smtp_cfg.to_addrs)
    msg.set_content(str(summary))
    msg.add_alternative(html, subtype="html")
    try:
        _send_raw(smtp_cfg, msg)
    except Exception as e:  # noqa: BLE001
        logger.warning("Daily summary send failed: %s", e)


def _pick_top_severity(alerts: list[dict[str, Any]]) -> str:
    order = {"CRITICAL": 3, "WARNING": 2, "INFO": 1}
    best = "INFO"
    best_rank = 0
    for a in alerts:
        sev = a.get("severity", "INFO")
        rank = order.get(sev, 0)
        if rank > best_rank:
            best = sev
            best_rank = rank
    return best
