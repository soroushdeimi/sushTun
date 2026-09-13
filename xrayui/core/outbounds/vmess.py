"""VMess outbound builder. AEAD-only: no alterId -- Xray 26.3 has none."""
from __future__ import annotations

from ..profiles import Profile
from ._common import stream_settings


def apply(proxy: dict, p: Profile) -> None:
    user: dict = {"id": p.id, "security": p.vmess_security or "auto"}
    proxy["protocol"] = "vmess"
    proxy["settings"] = {"vnext": [{"address": p.address, "port": p.port, "users": [user]}]}
    proxy["streamSettings"] = stream_settings(p)
