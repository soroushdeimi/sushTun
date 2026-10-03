"""HTTP outbound builder."""
from __future__ import annotations

from ..profiles import Profile
from ._common import stream_settings


def apply(proxy: dict, p: Profile) -> None:
    proxy["protocol"] = "http"
    settings = {"address": p.address, "port": p.port}
    if p.username:
        settings["user"] = p.username
        settings["pass"] = p.id
    proxy["settings"] = settings
    if p.security == "tls":
        proxy["streamSettings"] = stream_settings(p)
    else:
        proxy["streamSettings"] = {"network": "tcp"}
