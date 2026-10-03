"""SOCKS outbound builder."""
from __future__ import annotations

from ..profiles import Profile


def apply(proxy: dict, p: Profile) -> None:
    proxy["protocol"] = "socks"
    settings = {"address": p.address, "port": p.port}
    if p.username:
        settings["user"] = p.username
        settings["pass"] = p.id
    proxy["settings"] = settings
    proxy["streamSettings"] = {"network": "tcp"}
