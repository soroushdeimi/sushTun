"""Build the Xray `dns` object from user settings.

Empty settings mean "inherit the template", so an untouched install renders
exactly the bundled config. Malformed entries are dropped rather than raising:
Xray exits immediately on a config it cannot parse, so a typo in settings.json
must not turn into "the app will not connect".
"""
from __future__ import annotations

import ipaddress
import json
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

# Commonly published Iranian domestic resolvers, literal IPs, plain UDP 53.
# Kept in one dict so a stale address is easy to find and correct later.
DOMESTIC_PRESETS: dict[str, list[str]] = {
    "Shecan": ["178.22.122.100", "185.51.200.2"],
    "Electro": ["78.157.42.100", "78.157.42.101"],
    "403": ["10.202.10.202", "10.202.10.102"],
    "Begzar": ["185.55.226.26", "185.55.225.25"],
}

# Both the domestic-server and remote-via-tunnel bootstrap-server rules use
# this tag (or a prefix of it -- kept as one exact string here since this
# app only ever needs one such rule).
_DIRECT_DNS_TAG = "direct-dns"


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


# -- Domestic DNS, remote-via-tunnel, raw override (Phase 3) ----------------
def _split_host_port(addr: str) -> tuple[str, int | None]:
    """A scheme-less "host:port" -> (host, port). Verified against Xray
    26.3.27: a server object's "address" rejects an embedded port the same
    way a bare server string does ('first path segment in URL cannot
    contain colon'); "port" is a separate field, matching how v2rayN's own
    CreateDnsServer splits it. A scheme'd address, a bare host, or a bare
    (unbracketed) IPv6 literal is returned unsplit."""
    if addr.startswith(_SCHEMES):
        return addr, None
    if addr.startswith("[") and "]:" in addr:
        host, _, port_s = addr.rpartition(":")
        if port_s.isdigit():
            return host.strip("[]"), int(port_s)
        return addr, None
    if addr.count(":") == 1:
        host, _, port_s = addr.partition(":")
        if port_s.isdigit():
            return host, int(port_s)
    return addr, None


def _domestic_reason(entry: str) -> str:
    value = entry.strip()
    if not value:
        return ""
    if value in _REFUSED:
        return f"{value}: {_REFUSED[value]}"
    if any(c.isspace() for c in value):
        return f"{value}: a server address cannot contain spaces"
    if value.startswith(_SCHEMES):
        return validate_server(value)
    host, port = _split_host_port(value)
    if port is not None and not 1 <= port <= 65535:
        return f"{value}: invalid port"
    if _valid_address(host):
        return ""
    return f"{value}: expected an IP or a hostname, optionally with :port"


def validate_domestic(entries) -> list[str]:
    """Human-readable reasons for every entry clean_domestic would drop."""
    reasons = []
    for raw in entries or []:
        if not isinstance(raw, str):
            continue
        why = _domestic_reason(raw)
        if why:
            reasons.append(why)
    return reasons


def clean_domestic(entries) -> list[str]:
    out: list[str] = []
    for raw in entries or []:
        if not isinstance(raw, str):
            continue
        entry = raw.strip()
        if entry and not _domestic_reason(entry) and entry not in out:
            out.append(entry)
    return out


def _domestic_server_object(addr: str, domains: list[str]) -> dict:
    host, port = _split_host_port(addr)
    obj: dict = {"address": host, "domains": list(domains),
                 "skipFallback": True, "tag": _DIRECT_DNS_TAG}
    if port is not None:
        obj["port"] = port
    return obj


def _server_address_str(entry) -> str:
    if isinstance(entry, dict):
        return str(entry.get("address") or "")
    return str(entry or "")


def _server_host(entry) -> str:
    """The bare host Xray would need to resolve to reach this server."""
    addr = _server_address_str(entry)
    if addr.startswith(_SCHEMES):
        addr = addr.split("://", 1)[1]
    addr = addr.split("/", 1)[0]  # drop a DoH path
    if addr.startswith("[") and "]" in addr:
        return addr[1:addr.index("]")]
    if addr.count(":") == 1:  # a scheme-less host:port, e.g. already-split storage
        addr = addr.rsplit(":", 1)[0]
    return addr


def _is_hostname_server(entry) -> bool:
    host = _server_host(entry)
    return bool(host) and not _is_ip(host)


def _pick_bootstrap_address(domestic: list[str], servers: list) -> str:
    if domestic:
        return domestic[0]
    for entry in servers:
        host = _server_host(entry)
        if host and _is_ip(host):
            return _server_address_str(entry) or host
    return "1.1.1.1"


def _hostnames_needing_bootstrap(proxy_address: str, servers: list) -> list[str]:
    names: list[str] = []
    if proxy_address and not _is_ip(proxy_address):
        names.append(proxy_address)
    for entry in servers:
        host = _server_host(entry)
        if host and not _is_ip(host) and host not in names:
            names.append(host)
    return names


def _sanitize_raw_dns(data: dict) -> dict:
    """Drop any server entry (string, or an object's "address") equal to
    "localhost" or "fakedns" -- the same reason build_dns's servers list
    refuses them, still enforced even for a hand-written raw override."""
    out = dict(data)
    servers = out.get("servers")
    if isinstance(servers, list):
        out["servers"] = [
            s for s in servers
            if not (isinstance(_server_address_str(s), str)
                    and _server_address_str(s).strip() in _REFUSED)
        ]
    return out


def raw_override_issues(raw: str) -> list[str]:
    """Reasons to refuse SAVING a raw DNS override: only the dangerous
    localhost/fakedns case. Invalid JSON or a non-object is not refused --
    it is simply ignored at render time (see build_dns_and_rules), never
    raised, so there is nothing unsafe about saving it as typed."""
    text = (raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    reasons = []
    for s in data.get("servers") or []:
        addr = _server_address_str(s).strip()
        if addr in _REFUSED:
            reasons.append(f"{addr}: {_REFUSED[addr]}")
    return reasons


def build_dns_and_rules(d: dict, direct_domains: list[str], proxy_address: str) -> tuple[dict, list[dict]]:
    """The Xray `dns` object, plus any routing rules it needs.

    Domestic DNS and/or remote-via-tunnel each add one inboundTag routing
    rule; render.py inserts them right after the template's own rules and
    before user rules (see render._apply_dns_routing), so a user catch-all
    can never capture a DNS query these rules are meant to steer.
    """
    raw = str(d.get("raw_override") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            # domestic/remote/parallel/stale are ignored once raw_override
            # fully replaces the dns block -- there's nothing left to layer
            # them onto that would mean the same thing.
            return _sanitize_raw_dns(parsed), []
        # Invalid JSON or not an object: ignored, fall through to the
        # normal build below rather than raising.

    block = build_dns(d)
    rules: list[dict] = []
    needs_direct_dns_rule = False

    domestic = clean_domestic(d.get("domestic_servers"))
    if domestic and direct_domains:
        entries = [_domestic_server_object(addr, direct_domains) for addr in domestic]
        block["servers"] = entries + (block.get("servers") or [])
        needs_direct_dns_rule = True

    if d.get("remote_via_tunnel"):
        block["tag"] = "dns-module"
        rules.append({"type": "field", "inboundTag": ["dns-module"], "outboundTag": "proxy"})
        # Deadlock guard: the proxy outbound's address (and any hostname DNS
        # server) must resolve WITHOUT going through this same DNS module,
        # or resolving it never finishes -- the module can't answer until
        # it can reach the proxy, which it can't reach until it has an
        # answer for the proxy's own hostname.
        hostnames = _hostnames_needing_bootstrap(proxy_address, block.get("servers") or [])
        if hostnames:
            bootstrap_addr = _pick_bootstrap_address(domestic, block.get("servers") or [])
            bootstrap = {"address": bootstrap_addr,
                        "domains": [f"full:{h}" for h in hostnames],
                        "skipFallback": True, "tag": _DIRECT_DNS_TAG}
            block["servers"] = [bootstrap] + (block.get("servers") or [])
            needs_direct_dns_rule = True

    if needs_direct_dns_rule:
        rules.insert(0, {"type": "field", "inboundTag": [_DIRECT_DNS_TAG], "outboundTag": "direct"})

    if d.get("parallel_query"):
        block["enableParallelQuery"] = True
    if d.get("serve_stale"):
        block["serveStale"] = True

    return block, rules
