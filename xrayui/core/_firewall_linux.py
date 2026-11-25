"""Linux firewall backend: a dedicated nftables table (or an iptables chain
when nft is missing).

The table `inet sushtun` is created whole and deleted whole, so it never
touches any other table. The output chain allows the tunnel device, the proxy
server IPs, loopback, and (when allow_lan) the LAN / link-local / DHCP, then
drops everything else. Allow rules come before the drop, and the whole table
is loaded in one atomic `nft -f`, so there is never a moment with a drop and
no allows.

ARP is L2 and never reaches the netfilter output hook, so it is inherently
allowed and needs no rule.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .. import paths
from . import proc
from ._firewall_common import (
    DHCP_V4,
    DHCP_V6,
    LAN_V4,
    LAN_V6,
    FirewallError,
    split_ips,
)

TABLE = "sushtun"
# The iptables fallback chain name (max 28 chars, no leading digit).
CHAIN = "SUSHTUN"


def supported() -> bool:
    return shutil.which("nft") is not None or shutil.which("iptables") is not None


def _has_nft() -> bool:
    return shutil.which("nft") is not None


def build_nft(tun_alias: str, server_ips, allow_lan: bool) -> str:
    """The nftables script that creates the whole table.

    Allow rules precede the final drop, so the chain is never block-only.
    """
    v4, v6 = split_ips(server_ips)
    lines = [
        f"table inet {TABLE} {{",
        "\tchain output {",
        "\t\ttype filter hook output priority 0; policy accept;",
        f'\t\toifname "{tun_alias}" accept',
    ]
    for ip in v4:
        lines.append(f"\t\tip daddr {ip} accept")
    for ip in v6:
        lines.append(f"\t\tip6 daddr {ip} accept")
    lines.append('\t\toifname "lo" accept')
    if allow_lan:
        lines.append(f"\t\tudp dport {DHCP_V4[1]} accept")
        lines.append(f"\t\tudp6 dport {DHCP_V6[1]} accept")
        lines.append("\t\tip daddr { " + ", ".join(LAN_V4) + " } accept")
        lines.append(f"\t\tip6 daddr {LAN_V6[0]} accept")
    lines.append("\t\tdrop")
    lines.append("\t}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _write_temp(content: str) -> Path:
    d = paths.state_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="fw-nft-", suffix=".nft", dir=str(d))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return Path(name)


def _nft(args: list[str]):
    return proc.run(["nft", *args])


def _install_nft(tun_alias: str, server_ips, allow_lan: bool) -> None:
    script = build_nft(tun_alias, server_ips, allow_lan)
    # Delete any existing table first (idempotent), then load the whole table
    # in one atomic step.
    _nft(["delete", "table", "inet", TABLE])  # no-op if absent
    f = _write_temp(script)
    try:
        r = _nft(["-f", str(f)])
        if r.returncode != 0:
            raise FirewallError(f"nft failed to load the table: {r.stderr.strip()}")
    finally:
        f.unlink(missing_ok=True)
    if not _nft_active():
        raise FirewallError("nftables firewall installed but could not be verified")


def _nft_active() -> bool:
    r = _nft(["list", "table", "inet", TABLE])
    if r.returncode != 0:
        return False
    # The table must actually carry the drop, not just exist empty.
    return "drop" in r.stdout


def _remove_nft() -> list[str]:
    # Deleting the whole table is atomic and idempotent; a missing table is a
    # no-op, not an error we care about.
    _nft(["delete", "table", "inet", TABLE])
    return []


# -- iptables fallback (no nft) ---------------------------------------------
# A dedicated chain jumped to from the top of OUTPUT. Allow rules are appended
# before the DROP, and the jump is added only once the chain is fully built, so
# there is never a block-only moment.


def _ipt_rules(tun_alias: str, server_ips, allow_lan: bool, v6: bool) -> list[list[str]]:
    """The chain rules for one address family, in order (allows then DROP)."""
    v4, v6ips = split_ips(server_ips)
    ipt = "ip6tables" if v6 else "iptables"
    rules: list[list[str]] = [[ipt, "-A", CHAIN, "-o", tun_alias, "-j", "ACCEPT"]]
    ips = v6ips if v6 else v4
    for ip in ips:
        rules.append([ipt, "-A", CHAIN, "-d", ip, "-j", "ACCEPT"])
    rules.append([ipt, "-A", CHAIN, "-o", "lo", "-j", "ACCEPT"])
    if allow_lan:
        if v6:
            rules.append([ipt, "-A", CHAIN, "-p", "udp", "--dport", str(DHCP_V6[1]),
                          "-j", "ACCEPT"])
            rules.append([ipt, "-A", CHAIN, "-d", LAN_V6[0], "-j", "ACCEPT"])
        else:
            rules.append([ipt, "-A", CHAIN, "-p", "udp", "--dport", str(DHCP_V4[1]),
                          "-j", "ACCEPT"])
            for net in LAN_V4:
                rules.append([ipt, "-A", CHAIN, "-d", net, "-j", "ACCEPT"])
    rules.append([ipt, "-A", CHAIN, "-j", "DROP"])
    return rules


def _jump_present(ipt: str) -> bool:
    r = proc.run([ipt, "-S", "OUTPUT"])
    return r.returncode == 0 and f"-j {CHAIN}" in r.stdout


def _install_family(ipt: str, tun_alias: str, server_ips, allow_lan: bool,
                    v6: bool) -> None:
    proc.run([ipt, "-N", CHAIN])  # create; "already exists" is fine
    proc.run([ipt, "-F", CHAIN])  # clear any stale rules in our chain
    for rule in _ipt_rules(tun_alias, server_ips, allow_lan, v6):
        r = proc.run(rule)
        if r.returncode != 0:
            raise FirewallError(f"{ipt} rule failed: {r.stderr.strip()}")
    if not _jump_present(ipt):
        r = proc.run([ipt, "-I", "OUTPUT", "1", "-j", CHAIN])
        if r.returncode != 0:
            raise FirewallError(f"{ipt} could not hook OUTPUT: {r.stderr.strip()}")


def _install_iptables(tun_alias: str, server_ips, allow_lan: bool) -> None:
    try:
        _install_family("iptables", tun_alias, server_ips, allow_lan, v6=False)
        _install_family("ip6tables", tun_alias, server_ips, allow_lan, v6=True)
        if not _ipt_active():
            raise FirewallError("iptables firewall installed but could not be verified")
    except FirewallError:
        # A failure after the v4 family was installed would leave a half
        # lockdown; roll both families back before reporting the error.
        _remove_iptables()
        raise


def _ipt_active() -> bool:
    for ipt in ("iptables", "ip6tables"):
        if shutil.which(ipt) is None:
            continue
        if not _jump_present(ipt):
            return False
        r = proc.run([ipt, "-S", CHAIN])
        if r.returncode != 0 or "-j DROP" not in r.stdout:
            return False
    return True


def _remove_family(ipt: str) -> None:
    if shutil.which(ipt) is None:
        return
    if _jump_present(ipt):
        proc.run([ipt, "-D", "OUTPUT", "-j", CHAIN])
    proc.run([ipt, "-F", CHAIN])
    proc.run([ipt, "-X", CHAIN])  # delete the chain; no-op if absent


def _remove_iptables() -> list[str]:
    _remove_family("iptables")
    _remove_family("ip6tables")
    return []


# -- public interface --------------------------------------------------------
def install(tun_alias: str, server_ips, allow_lan: bool) -> None:
    if not supported():
        raise FirewallError("neither nft nor iptables is available")
    if _has_nft():
        _install_nft(tun_alias, server_ips, allow_lan)
    else:
        _install_iptables(tun_alias, server_ips, allow_lan)


def remove() -> list[str]:
    if _has_nft():
        return _remove_nft()
    if shutil.which("iptables") is not None:
        return _remove_iptables()
    return []


def is_active() -> bool:
    if _has_nft():
        return _nft_active()
    if shutil.which("iptables") is not None:
        return _ipt_active()
    return False
