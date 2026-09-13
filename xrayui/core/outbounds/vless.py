"""VLESS outbound builder."""
from __future__ import annotations

from ..profiles import Profile
from ._common import stream_settings


def apply(proxy: dict, p: Profile) -> None:
    user: dict = {"id": p.id, "encryption": p.encryption}
    if p.flow:
        user["flow"] = p.flow
    proxy["protocol"] = p.protocol
    proxy["settings"] = {"vnext": [{"address": p.address, "port": p.port, "users": [user]}]}
    proxy["streamSettings"] = stream_settings(p)
