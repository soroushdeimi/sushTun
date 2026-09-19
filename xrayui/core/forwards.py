"""Port forwarding: a local port that always reaches one fixed host:port.

Off by default (an empty list). Each forward is a dokodemo-door inbound
(127.0.0.1, or the whole network when the user shares that one) plus a routing
rule that sends it through the tunnel or directly, placed before every user
rule so the choice holds whatever the routing mode. A forward switched off in
Settings is skipped silently.

Forwards are independent: a bad or busy one is dropped on its own with a
warning, and none of them can keep the main connection from starting.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from . import exits

VIAS = ("proxy", "direct")
NETWORKS = ("tcp", "udp", "tcp,udp")
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


@dataclass
class Forward:
    port: int
    host: str
    target_port: int
    via: str
    network: str
    lan: bool = False

    @property
    def listen(self) -> str:
        # Sharing one is opt-in per forward: on the LAN anyone can use it.
        return "0.0.0.0" if self.lan else "127.0.0.1"

    @property
    def tag(self) -> str:
        return f"fwd-{self.port}"


def _parse_target(target: str) -> tuple[str, int] | None:
    """ "host:port" or "[v6]:port" -> (host, port), or None."""
    text = (target or "").strip()
    if text.startswith("["):
        host, sep, rest = text[1:].partition("]:")
        if not sep:
            return None
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return None
    else:
        host, sep, rest = text.rpartition(":")
        if not sep or not (_HOST_RE.match(host) or _is_ipv4(host)):
            return None
    if not rest.isdigit() or not 1 <= int(rest) <= 65535:
        return None
    return host, int(rest)


def _is_ipv4(text: str) -> bool:
    try:
        ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return True


def item_problem(item, taken: set[int]) -> str | None:
    """Why one forward can't be used, or None. `taken` holds ports already in use
    by sushTun (and by the forwards before this one)."""
    if not isinstance(item, dict):
        return "not a forward"
    port = item.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        return "the local port must be between 1024 and 65535"
    if port in taken:
        return f"port {port} is already used by sushTun"
    if _parse_target(str(item.get("target") or "")) is None:
        return f"'{item.get('target')}' is not host:port"
    if item.get("via") not in VIAS:
        return "choose through the tunnel or direct"
    if item.get("network", "tcp") not in NETWORKS:
        return "choose TCP, UDP or both"
    return None


def taken_ports(core_cfg: dict | None, exits_cfg: dict | None) -> set[int]:
    taken = exits.reserved_ports(core_cfg or {})
    if (exits_cfg or {}).get("enabled") is True and isinstance((exits_cfg or {}).get("port"), int):
        taken.add(exits_cfg["port"])
    return taken


def prepare(forwards_cfg, core_cfg: dict | None,
            exits_cfg: dict | None) -> tuple[list[Forward], list[str]]:
    """The forwards to render, and one warning per forward that was dropped."""
    if not isinstance(forwards_cfg, list) or not forwards_cfg:
        return [], []
    taken = taken_ports(core_cfg, exits_cfg)
    kept: list[Forward] = []
    warnings: list[str] = []
    for item in forwards_cfg:
        if isinstance(item, dict) and item.get("enabled", True) is False:
            continue  # switched off in Settings: not an error, just skipped
        why = item_problem(item, taken)
        if why is None and not exits.port_is_free(item["port"]):
            why = f"port {item['port']} is in use by another program"
        if why is not None:
            warnings.append(f"Port forward skipped: {why}.")
            continue
        host, target_port = _parse_target(item["target"])
        kept.append(Forward(item["port"], host, target_port, item["via"],
                            item.get("network", "tcp"), item.get("lan") is True))
        taken.add(item["port"])
    return kept, warnings


def apply(cfg: dict, forwards: list[Forward]) -> list[dict]:
    """Add one inbound per forward; return their routing rules."""
    rules: list[dict] = []
    for f in forwards:
        cfg.setdefault("inbounds", []).append({
            "tag": f.tag, "listen": f.listen, "port": f.port,
            "protocol": "dokodemo-door",
            "settings": {"address": f.host, "port": f.target_port, "network": f.network},
        })
        rules.append({"type": "field", "inboundTag": [f.tag], "outboundTag": f.via})
    return rules
