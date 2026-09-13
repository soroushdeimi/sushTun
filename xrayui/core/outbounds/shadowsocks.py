"""Shadowsocks outbound builder."""
from __future__ import annotations

from ..profiles import Profile
from ._common import stream_settings


def apply(proxy: dict, p: Profile) -> None:
    proxy["protocol"] = "shadowsocks"
    proxy["settings"] = {"servers": [{
        "address": p.address, "port": p.port, "method": p.ss_method, "password": p.id,
    }]}
    proxy["streamSettings"] = stream_settings(p)
