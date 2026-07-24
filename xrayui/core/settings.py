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
        "app_presets": [],
    },
    "alerts": {
        "data_percent": 10,
        "data_gb": 1.0,
        "expiry_days": 3,
        "auto_refresh_hours": 6,
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
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
