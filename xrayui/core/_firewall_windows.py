"""Windows firewall backend: netsh advfirewall rules in one named group.

Windows Firewall has no "block all" profile switch to toggle, so the lockdown
is a set of named rules in a single group: allow rules for the tunnel
interface, the proxy server IPs, loopback, and (when allow_lan) the LAN /
link-local / DHCP, plus one block-all outbound rule. The profile defaults are
never changed.

netsh evaluates rules by priority (higher first; ties by creation order), so
the allow rules carry a high priority and the block-all rule a low one: the
allows always win, and there is never a moment with a block and no allows.
Everything is removed by group name, so a leftover is found and cleared.
"""
from __future__ import annotations

import shutil

from . import proc
from ._firewall_common import (
    DHCP_V4,
    LAN_V4,
    LAN_V6,
    FirewallError,
    split_ips,
)

GROUP = "sushTun Firewall"
# Allow rules must be evaluated before the block-all rule. netsh orders by
# priority (lower value = higher priority = evaluated first), so the allows get
# a low number and the block a high one; creation order is then irrelevant.
_ALLOW_PRIORITY = 1
_BLOCK_PRIORITY = 100
_BLOCK_NAME = "sushTun block all outbound"


def supported() -> bool:
    return shutil.which("netsh") is not None


def _rule_specs(tun_alias: str, server_ips, allow_lan: bool) -> list[dict]:
    """The allow rules, in order. Each is a netsh advfirewall rule spec."""
    v4, v6 = split_ips(server_ips)
    specs: list[dict] = [
        {"name": "sushTun tunnel", "remoteip": "any", "iface": tun_alias},
    ]
    for ip in v4 + v6:
        specs.append({"name": f"sushTun server {ip}", "remoteip": ip})
    specs.append({"name": "sushTun loopback", "remoteip": "localhost"})
    if allow_lan:
        specs.append({"name": "sushTun dhcp", "remoteip": "any",
                      "proto": "UDP", "rport": str(DHCP_V4[1])})
        for net in LAN_V4:
            specs.append({"name": f"sushTun lan {net}", "remoteip": net})
        specs.append({"name": "sushTun lan6", "remoteip": LAN_V6[0]})
    return specs


def _allow_argv(spec: dict) -> list[str]:
    args = ["netsh", "advfirewall", "firewall", "add", "rule",
            f"name={spec['name']}",
            "dir=out", "action=allow", "enable=yes",
            f"remoteip={spec['remoteip']}",
            f"group={GROUP}",
            f"priority={_ALLOW_PRIORITY}"]
    if spec.get("iface"):
        args.append(f"iface={spec['iface']}")
    if spec.get("proto"):
        args += [f"protocol={spec['proto']}", f"remoteport={spec['rport']}"]
    return args


def _block_argv() -> list[str]:
    return ["netsh", "advfirewall", "firewall", "add", "rule",
            f"name={_BLOCK_NAME}",
            "dir=out", "action=block", "enable=yes",
            "remoteip=any",
            f"group={GROUP}",
            f"priority={_BLOCK_PRIORITY}"]


def _group_rules() -> list[str]:
    """The names of the rules currently in our group (empty if none)."""
    r = proc.run(["netsh", "advfirewall", "firewall", "show", "rule",
                  f"groupname={GROUP}"])
    if r.returncode != 0:
        return []
    names: list[str] = []
    for line in r.stdout.splitlines():
        s = line.strip()
        if s.lower().startswith("rule name:"):
            name = s.split(":", 1)[1].strip()
            if name:
                names.append(name)
    return names


def _delete_rule(name: str) -> None:
    proc.run(["netsh", "advfirewall", "firewall", "delete", "rule",
              f"name={name}"])


def install(tun_alias: str, server_ips, allow_lan: bool) -> None:
    if not supported():
        raise FirewallError("netsh not found")
    # Clear any rules a crashed previous run left in the group first.
    for name in _group_rules():
        _delete_rule(name)

    added: list[str] = []
    try:
        # Allow rules first, then the block-all rule: the block is only added
        # once every allow is in place, so there is never a block-only moment.
        for spec in _rule_specs(tun_alias, server_ips, allow_lan):
            r = proc.run(_allow_argv(spec))
            if r.returncode != 0:
                raise FirewallError(f"could not add firewall rule {spec['name']}: "
                                    f"{r.stderr.strip()}")
            added.append(spec["name"])
        r = proc.run(_block_argv())
        if r.returncode != 0:
            raise FirewallError(f"could not add the block-all rule: {r.stderr.strip()}")
        added.append(_BLOCK_NAME)

        if not is_active():
            raise FirewallError("firewall installed but could not be verified")
    except FirewallError:
        # Roll back the rules added so far so a failed install never leaves a
        # half-locked-down machine; the caller logs a WARNING and continues.
        for name in added:
            _delete_rule(name)
        raise


def remove() -> list[str]:
    """Idempotent: delete every rule in the group (no-op when none)."""
    warnings: list[str] = []
    if not supported():
        return warnings
    for name in _group_rules():
        r = proc.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                      f"name={name}"])
        if r.returncode != 0:
            warnings.append(f"could not remove firewall rule {name}")
    return warnings


def is_active() -> bool:
    if not supported():
        return False
    return _BLOCK_NAME in _group_rules()
