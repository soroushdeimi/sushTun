"""Names and types shared by the Windows backend (network.py) and _net_posix.

Their own module because network imports _net_posix at its bottom: were they
defined in network, importing _net_posix first would find network half
initialised and fail.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TUN_NAME = "xray0"

# The TUN adapter must own a global-scope address. Left on DHCP it falls back
# to APIPA (169.254.x.x), and Windows source-address selection then prefers the
# physical adapter's global address for global destinations — so the tunnel's
# default route is never chosen and traffic leaves in the clear.
TUN_ADDRESS = "172.19.0.2"
TUN_NETMASK = "255.255.255.252"


@dataclass
class Interface:
    alias: str
    ipv4: str
    gateway: str
    index: int | None = None


@dataclass
class DnsState:
    mode: str = "DHCP"  # DHCP | STATIC | RESOLVED | FILE | MACOS
    servers: list[str] = field(default_factory=list)
