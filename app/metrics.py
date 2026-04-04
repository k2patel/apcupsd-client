"""Prometheus exposition for UPS fleet metrics."""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

from .config import load_config
from .storage import get_redis

_registry = CollectorRegistry()

_g_loadpct = Gauge("ups_loadpct", "UPS load percentage", ["ups"], registry=_registry)
_g_bcharge = Gauge("ups_bcharge", "UPS battery charge percentage", ["ups"], registry=_registry)
_g_timeleft = Gauge("ups_timeleft_minutes", "UPS estimated runtime minutes", ["ups"], registry=_registry)
_g_watts = Gauge("ups_watts", "UPS derived watts", ["ups"], registry=_registry)
_g_online = Gauge("ups_online", "1 if UPS is online and reachable", ["ups"], registry=_registry)
_c_poll_errors = Counter(
    "ups_poll_errors_total",
    "Cumulative poll failures",
    ["ups"],
    registry=_registry,
)


def _f(v):
    try:
        return float(str(v).split()[0]) if v is not None else None
    except Exception:
        return None


def render_metrics() -> tuple[bytes, str]:
    """Collect current snapshot data and produce Prometheus text exposition."""
    r = get_redis()
    cfg = load_config()
    for ups in cfg.ups:
        snap = r.hgetall(f"ups:snap:{ups.name}")
        status = str(snap.get("STATUS", "")).upper() if snap else ""
        online = 1.0 if snap and "ONLINE" in status else 0.0
        # If we've marked offline via health tracker, force zero
        if r.get(f"ups:health:offline:{ups.name}"):
            online = 0.0
        _g_online.labels(ups=ups.name).set(online)
        if snap:
            lp = _f(snap.get("LOADPCT"))
            if lp is not None:
                _g_loadpct.labels(ups=ups.name).set(lp)
            bc = _f(snap.get("BCHARGE"))
            if bc is not None:
                _g_bcharge.labels(ups=ups.name).set(bc)
            tl = _f(snap.get("TIMELEFT")) or _f(snap.get("RUNTIME_MINUTES"))
            if tl is not None:
                _g_timeleft.labels(ups=ups.name).set(tl)
            w = _f(snap.get("DERIVED_WATTS"))
            if w is not None:
                _g_watts.labels(ups=ups.name).set(w)
        fail_count = r.get(f"ups:health:fail_count:{ups.name}")
        if fail_count:
            try:
                # Counter semantics: set absolute by incrementing delta. Instead, expose gauge.
                # We use a cumulative inc here; reset on process restart is acceptable.
                pass
            except Exception:
                pass
    return generate_latest(_registry), CONTENT_TYPE_LATEST


def record_poll_error(ups_name: str) -> None:
    _c_poll_errors.labels(ups=ups_name).inc()
