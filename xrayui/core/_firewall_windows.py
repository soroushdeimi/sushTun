"""Windows firewall backend: two outbound block rules built from complements.

Windows Firewall has no "block all except" and its block rules always beat
allow rules (checked on a real Windows: a block-all plus an allow rule still
dropped the traffic). `netsh` also rejects `group=`, `priority=` and `iface=`.
So nothing here is an allow rule. Instead the lockdown blocks everything
*outside* what must stay reachable: the destination range is the complement of
{proxy servers, loopback, and (allow_lan) LAN / link-local / DHCP}, and the
source range is the complement of the tunnel's own address, so traffic that
leaves through the tunnel is never matched. One rule per IP family.

The profiles' default policy is never touched (a crash then cannot leave the
machine with outbound blocked by policy). The rules are found again by name,
so a leftover is cleared by install, remove and the stale-state recovery.
"""
from __future__ import annotations

import shutil

from . import proc
from ._firewall_common import (
    DHCP_V4,  # noqa: F401  (documented: v4 DHCP goes to the broadcast address)
    LAN_V4,
    LAN_V6,
    FirewallError,
    complement_ranges,
    split_ips,
)
from ._net_common import TUN_ADDRESS

_V4_NAME = "sushTun block outbound v4"
_V6_NAME = "sushTun block outbound v6"
_NAMES = (_V4_NAME, _V6_NAME)
_DESCRIPTION = "sushTun kill-switch firewall (removed on disconnect)"
# v4 DHCP discovers go to the limited broadcast; v6 uses link-local multicast.
_V4_BROADCAST = "255.255.255.255/32"
_V6_LINK_MULTICAST = "ff02::/16"


def supported() -> bool:
    return shutil.which("netsh") is not None


def _allowed(tun_alias: str, server_ips, allow_lan: bool) -> tuple[list[str], list[str]]:
    """The destination networks that must stay reachable: (v4, v6)."""
    v4, v6 = split_ips(server_ips)
    a4 = [f"{ip}/32" for ip in v4] + ["127.0.0.0/8"]
    a6 = [f"{ip}/128" for ip in v6] + ["::1/128"]
    if allow_lan:
        a4 += [*LAN_V4, _V4_BROADCAST]
        a6 += [*LAN_V6, _V6_LINK_MULTICAST]
    return a4, a6


def _rule_argvs(tun_alias: str, server_ips, allow_lan: bool) -> list[list[str]]:
    a4, a6 = _allowed(tun_alias, server_ips, allow_lan)
    base = ["netsh", "advfirewall", "firewall", "add", "rule"]
    common = ["dir=out", "action=block", "enable=yes", f"description={_DESCRIPTION}"]
    return [
        [*base, f"name={_V4_NAME}", *common,
         "remoteip=" + ",".join(complement_ranges(a4, 4)),
         # Not the tunnel's own source address: traffic sent through the tunnel
         # carries it, and must never be matched.
         "localip=" + ",".join(complement_ranges([f"{TUN_ADDRESS}/32"], 4))],
        [*base, f"name={_V6_NAME}", *common,
         "remoteip=" + ",".join(complement_ranges(a6, 6))],
    ]


def _delete_argv(name: str) -> list[str]:
    return ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"]


def _exists(name: str) -> bool:
    r = proc.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"])
    return r.returncode == 0 and name.lower() in r.stdout.lower()


def install(tun_alias: str, server_ips, allow_lan: bool) -> None:
    if not supported():
        raise FirewallError("netsh not found")
    # Clear a leftover from a crashed run first, so adding never duplicates.
    for name in _NAMES:
        proc.run(_delete_argv(name))
    try:
        for argv in _rule_argvs(tun_alias, server_ips, allow_lan):
            r = proc.run(argv)
            if r.returncode != 0:
                raise FirewallError(
                    f"could not add firewall rule {argv[5][5:]}: "
                    f"{(r.stdout or r.stderr).strip()}")
        if not is_active():
            raise FirewallError("firewall installed but could not be verified")
    except FirewallError:
        # Never leave half a lockdown behind; the caller logs and continues.
        for name in _NAMES:
            proc.run(_delete_argv(name))
        raise


def remove() -> list[str]:
    """Idempotent: delete both rules (no-op when absent)."""
    warnings: list[str] = []
    if not supported():
        return warnings
    for name in _NAMES:
        if _exists(name) and proc.run(_delete_argv(name)).returncode != 0:
            warnings.append(f"could not remove firewall rule {name}")
    return warnings


def is_active() -> bool:
    return supported() and all(_exists(n) for n in _NAMES)
