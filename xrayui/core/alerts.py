"""Quota/expiry alert evaluation with a persistent anti-spam throttle."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .. import paths
from . import leakcheck
from .subscription import Subscription


@dataclass
class Alert:
    level: str  # "warning" | "critical"
    message: str  # pre-formatted English -- a fallback for any non-UI consumer
    key: str
    # `template` (still carrying {placeholder}s) + `params`: core stays
    # English-only, so the UI translates via i18n.tr(template, **params)
    # instead of consuming `message` directly. Both empty means "no
    # translatable template" (there always is one here, but this keeps the
    # dataclass usable if a future alert has no good one).
    template: str = ""
    params: dict = field(default_factory=dict)


def human_bytes(n: int) -> str:
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < step:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= step
    return f"{n:.1f} PB"


def evaluate(sub: Subscription, cfg: dict) -> list[Alert]:
    alerts: list[Alert] = []
    u = sub.usage
    pct = u.percent_left
    if pct is not None:
        gb_left = u.remaining / 1e9
        if pct <= 0.03 or gb_left <= 0.2:
            amount = human_bytes(u.remaining)
            alerts.append(Alert("critical",
                                f"Critical: only {amount} data left",
                                f"data:crit:{sub.uid}",
                                template="Critical: only {amount} data left",
                                params={"amount": amount}))
        elif pct * 100 <= cfg.get("data_percent", 10) or gb_left <= cfg.get("data_gb", 1.0):
            amount = human_bytes(u.remaining)
            percent = f"{pct:.0%}"
            alerts.append(Alert("warning",
                                f"Low data: {amount} left ({percent})",
                                f"data:warn:{sub.uid}",
                                template="Low data: {amount} left ({percent})",
                                params={"amount": amount, "percent": percent}))
    days = u.days_left
    if days is not None:
        if days <= 1:
            n = f"{max(days, 0):.1f}"
            alerts.append(Alert("critical", f"Subscription expires in {n} days",
                                f"exp:crit:{sub.uid}",
                                template="Subscription expires in {n} days", params={"n": n}))
        elif days <= cfg.get("expiry_days", 3):
            n = f"{days:.1f}"
            alerts.append(Alert("warning", f"Subscription expires in {n} days",
                                f"exp:warn:{sub.uid}",
                                template="Subscription expires in {n} days", params={"n": n}))
    return alerts


def tunnel_lost(state_connected: bool, xray_running: bool) -> bool:
    """True if the app believes it is connected but the xray process is gone.

    A dead xray under a "connected" flag means traffic is no longer in the
    tunnel, so this is a safety alert, not a leak check.
    """
    return bool(state_connected) and not bool(xray_running)


def current_alerts(
    *,
    state_connected: bool,
    xray_running: bool,
    verdict: leakcheck.Verdict | None = None,
    dns_audit: leakcheck.DnsAudit | None = None,
    ipv6_audit: leakcheck.Ipv6Audit | None = None,
) -> list[Alert]:
    """The alerts whose conditions currently hold. Pure: inputs -> list.

    The UI shows these every tick (so they clear the moment the condition is
    fixed) and uses Throttle.allow(alert.key) to decide whether to push a
    fresh OS notification, so each fires once per incident rather than every
    15 s. The caller controls what is passed: a disabled leak check simply
    passes no verdict, an unrun diagnostic passes no audit.
    """
    alerts: list[Alert] = []
    if tunnel_lost(state_connected, xray_running):
        alerts.append(Alert(
            "critical",
            "VPN dropped: the tunnel is down but the app still shows connected.",
            "vpn:dropped",
            template="VPN dropped: the tunnel is down but the app still shows connected."))
    if verdict is not None:
        if verdict.status == leakcheck.EXIT_IS_IRAN:
            alerts.append(Alert("critical", leakcheck.MSG_EXIT_IRAN,
                                "leak:ip:iran", template=leakcheck.MSG_EXIT_IRAN))
        elif verdict.status == leakcheck.IP_MATCHES_REAL:
            alerts.append(Alert("critical", leakcheck.MSG_IP_REAL,
                                "leak:ip:real", template=leakcheck.MSG_IP_REAL))
    if dns_audit is not None and dns_audit.leaks:
        alerts.append(Alert(
            "warning",
            "DNS may leak: some resolvers are still outside the tunnel.",
            "leak:dns",
            template="DNS may leak: some resolvers are still outside the tunnel."))
    if ipv6_audit is not None and ipv6_audit.leaks:
        alerts.append(Alert(
            "warning",
            "IPv6 may leak: an IPv6 default route is outside the tunnel.",
            "leak:ipv6",
            template="IPv6 may leak: an IPv6 default route is outside the tunnel."))
    return alerts


class Throttle:
    """Fire each alert key at most once per interval, persisted across restarts."""

    def __init__(self) -> None:
        self._file = paths.base_dir() / "alert-state.json"
        try:
            self._data = json.loads(self._file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            self._data = {}

    def allow(self, key: str, interval: float = 86400.0) -> bool:
        now = time.time()
        if now - self._data.get(key, 0) < interval:
            return False
        self._data[key] = now
        try:
            self._file.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass
        return True
