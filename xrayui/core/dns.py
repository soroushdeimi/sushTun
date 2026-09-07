"""Build the Xray `dns` object from user settings.

Empty settings mean "inherit the template", so an untouched install renders
exactly the bundled config. Malformed entries are dropped rather than raising:
Xray exits immediately on a config it cannot parse, so a typo in settings.json
must not turn into "the app will not connect".
"""
from __future__ import annotations

import ipaddress
import re

QUERY_STRATEGIES = ("UseIP", "UseIPv4", "UseIPv6", "UseSystem")

# Transport prefixes Xray accepts on a DNS server entry.
_SCHEMES = (
    "https://", "https+local://",
    "h2c://", "h2c+local://",
    "tcp://", "tcp+local://",
    "udp://", "udp+local://",
    "quic://", "quic+local://",
)
# Bare words Xray accepts that this app must refuse, with the reason shown to
# the user. "localhost" is the dangerous one: set_dns_loopback pins the adapter
# to 127.0.0.1, which is dns-in, which routes to dns-out, which asks the
# built-in resolver -- which would then ask the OS resolver at 127.0.0.1 again.
# A closed loop and a total DNS blackout that reads as "the VPN is broken".
_REFUSED = {
    "localhost": "asks the OS resolver, which this app points back at Xray — a loop",
    "fakedns": "needs a matching inbound and sniffing setup this app does not ship",
}

_LABEL = re.compile(r"^[a-zA-Z0-9_]([a-zA-Z0-9_-]{0,61}[a-zA-Z0-9_])?$")

# Literal IPs only, never hostnames: a DoH URL naming a host needs another
# resolver to bootstrap it, and these are often the only servers configured.
PRESETS: dict[str, list[str]] = {
    "Cloudflare": ["https://1.1.1.1/dns-query", "https://1.0.0.1/dns-query"],
    "Google": ["https://8.8.8.8/dns-query", "https://8.8.4.4/dns-query"],
    "Quad9": ["https://9.9.9.9/dns-query", "https://149.112.112.112/dns-query"],
    "AdGuard": ["https://94.140.14.14/dns-query", "https://94.140.15.15/dns-query"],
    "Plain UDP": ["1.1.1.1", "8.8.8.8"],
}


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _valid_hostname(host: str) -> bool:
    if len(host) > 253:
        return False
    return all(_LABEL.match(label) for label in host.rstrip(".").split("."))


def _valid_address(entry: str) -> bool:
    """A bare IP or hostname — no port.

    Verified against Xray 26.3.27: an entry carrying no scheme is parsed as a
    URL, so "8.8.8.8:5353" and "[2606:4700:4700::1111]:53" are both rejected
    with 'first path segment in URL cannot contain colon'. A port needs a
    scheme, e.g. udp://8.8.8.8:5353.
    """
    if not entry:
        return False
    if _is_ip(entry):
        return True
    if ":" in entry:  # a colon here can only be a port or a broken IPv6
        return False
    return _valid_hostname(entry)


def validate_server(entry: str) -> str:
    """Return why `entry` is unusable, or "" when it is a valid server."""
    value = entry.strip()
    if not value:
        return ""
    if value in _REFUSED:
        return f"{value}: {_REFUSED[value]}"
    if any(c.isspace() for c in value):
        return f"{value}: a server address cannot contain spaces"
    if value.startswith(_SCHEMES):
        # Everything after the scheme is host[:port][/path]; require a host.
        rest = value.split("://", 1)[1]
        if not rest.split("/", 1)[0]:
            return f"{value}: no server after the scheme"
        return ""
    if _valid_address(value):
        return ""
    # The common mistake: Xray parses a scheme-less entry as a URL, so a bare
    # host:port fails. Say what to type instead of just "invalid".
    if ":" in value:
        return f"{value}: a port needs a scheme — try udp://{value} or tcp://{value}"
    return (f"{value}: expected an IP, a hostname, or a scheme such as "
            "https:// tcp:// udp:// quic://")


def clean_servers(servers) -> list[str]:
    """Drop anything Xray would choke on. Never raises: a hand-edited
    settings.json must degrade to the template, not fail the connect."""
    out: list = []
    for raw in servers or []:
        # A full DnsServerObject can only be written by hand; pass it through.
        if isinstance(raw, dict):
            if raw not in out:
                out.append(raw)
            continue
        if not isinstance(raw, str):
            continue
        entry = raw.strip()
        if entry and not validate_server(entry) and entry not in out:
            out.append(entry)
    return out


def invalid_servers(servers) -> list[str]:
    """Human-readable reasons for every entry clean_servers would drop."""
    reasons = []
    for raw in servers or []:
        if not isinstance(raw, str):
            continue
        why = validate_server(raw)
        if why:
            reasons.append(why)
    return reasons


def clean_hosts(hosts) -> dict[str, str | list[str]]:
    out: dict[str, str | list[str]] = {}
    for domain, value in (hosts or {}).items():
        if not isinstance(domain, str) or not domain.strip():
            continue
        values = value if isinstance(value, list) else [value]
        # Do not coerce: str(7) would become the "hostname" 7.
        good = [v.strip() for v in values
                if isinstance(v, str) and _valid_address(v.strip())]
        if good:
            out[domain.strip()] = good[0] if len(good) == 1 else good
    return out


def hosts_from_lines(lines) -> dict[str, str | list[str]]:
    """Parse `domain = addr[, addr]` (or `domain addr`) lines into a map.

    Lines with no separator are dropped: a bare domain has no answer to give.
    """
    if isinstance(lines, dict):  # a map hand-written into settings.json
        return clean_hosts(lines)
    hosts: dict[str, str | list[str]] = {}
    for raw in lines or []:
        line = str(raw).strip()
        if not line or line.startswith("#"):
            continue
        domain, sep, rest = line.partition("=")
        if not sep:
            domain, sep, rest = line.partition(" ")
            if not sep:
                continue
        name = domain.strip()
        values = [v.strip() for v in rest.replace(",", " ").split() if v.strip()]
        if name and values:
            hosts[name] = values[0] if len(values) == 1 else values
    return clean_hosts(hosts)


def hosts_to_lines(hosts) -> list[str]:
    lines = []
    for domain, value in (hosts or {}).items():
        values = value if isinstance(value, list) else [value]
        lines.append(f"{domain} = {', '.join(str(v) for v in values)}")
    return lines


def build_dns(d: dict) -> dict:
    """Settings sub-dict -> the Xray `dns` object. Empty when nothing is set."""
    out: dict = {}

    servers = clean_servers(d.get("servers"))
    if servers:
        out["servers"] = servers

    strategy = str(d.get("query_strategy") or "").strip()
    if strategy in QUERY_STRATEGIES:
        out["queryStrategy"] = strategy

    hosts = hosts_from_lines(d.get("hosts"))
    if hosts:
        out["hosts"] = hosts

    return out


def has_custom_dns(d: dict) -> bool:
    return bool(build_dns(d))
