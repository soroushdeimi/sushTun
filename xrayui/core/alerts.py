"""Quota/expiry alert evaluation with a persistent anti-spam throttle."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .. import paths
from .subscription import Subscription


@dataclass
class Alert:
    level: str  # "warning" | "critical"
    message: str
    key: str


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
            alerts.append(Alert("critical",
                                f"Critical: only {human_bytes(u.remaining)} data left",
                                f"data:crit:{sub.uid}"))
        elif pct * 100 <= cfg.get("data_percent", 10) or gb_left <= cfg.get("data_gb", 1.0):
            alerts.append(Alert("warning",
                                f"Low data: {human_bytes(u.remaining)} left ({pct:.0%})",
                                f"data:warn:{sub.uid}"))
    days = u.days_left
    if days is not None:
        if days <= 1:
            alerts.append(Alert("critical", f"Subscription expires in {max(days, 0):.1f} days",
                                f"exp:crit:{sub.uid}"))
        elif days <= cfg.get("expiry_days", 3):
            alerts.append(Alert("warning", f"Subscription expires in {days:.1f} days",
                                f"exp:warn:{sub.uid}"))
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
