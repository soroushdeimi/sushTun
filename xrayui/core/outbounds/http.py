"""HTTP outbound builder."""
from __future__ import annotations

from dataclasses import replace

from ..profiles import Profile
from ._common import stream_settings


def apply(proxy: dict, p: Profile) -> None:
    proxy["protocol"] = "http"
    settings = {"address": p.address, "port": p.port}
    if p.username:
        settings["user"] = p.username
        settings["pass"] = p.id
    proxy["settings"] = settings
    proxy["streamSettings"] = stream_settings(replace(p, network="tcp"))
