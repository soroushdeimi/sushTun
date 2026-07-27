"""Central app settings persisted to settings.json (deep-merged with defaults)."""
from __future__ import annotations

import copy
import json

from .. import paths

DEFAULTS: dict = {
    "ping_target": "1.1.1.1",
    "sample_seconds": 5,
    "routing": {
        "low_usage": False,
        "block_ads": True,
        "direct_iran": True,
        "direct_russia": False,
        "direct_china": False,
        "direct_private": True,
        "bypass_domains": [],
        "bypass_ips": [],
        "proxy_domains": [],
    },
    "gateway": {
        "enabled": False,
        "start_hotspot": True,
    },
    "alerts": {
        "data_percent": 10,
        "data_gb": 1.0,
        "expiry_days": 3,
        "auto_refresh_hours": 6,
    },
}


def _merge(base: dict, over: dict) -> dict:
    """Overlay saved values on the defaults, dropping keys we no longer define."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k not in out:
            continue  # stale key from an older version
        if isinstance(v, dict) and isinstance(out[k], dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _path():
    return paths.base_dir() / "settings.json"


def load() -> dict:
    p = _path()
    if p.exists():
        try:
            return _merge(DEFAULTS, json.loads(p.read_text(encoding="utf-8")))
        except ValueError:
            pass
    return copy.deepcopy(DEFAULTS)


def save(data: dict) -> None:
    _path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
