"""Per-protocol outbound builders, dispatched by Profile.protocol.

vless.apply is also the fallback for any protocol that isn't specially
handled, matching the pre-split behaviour where only wireguard branched off.
"""
from __future__ import annotations

from ..profiles import Profile
from . import vless, wireguard

_BUILDERS = {
    "wireguard": wireguard.apply,
}


def apply_profile(cfg: dict, p: Profile) -> None:
    proxy = next((o for o in cfg.get("outbounds", []) if o.get("tag") == "proxy"), None)
    if proxy is None:
        raise ValueError("template has no outbound tagged 'proxy'")
    builder = _BUILDERS.get((p.protocol or "").lower(), vless.apply)
    builder(proxy, p)
