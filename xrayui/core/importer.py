"""Parse share formats into Profile objects: vless://, wireguard://, .conf, JSON, QR."""
from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

from .profiles import Profile, normalize_pcs


def _b64decode(text: str) -> str:
    s = "".join(text.split())
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", errors="replace")


def _maybe_b64(text: str) -> str:
    try:
        decoded = _b64decode(text)
        if "://" in decoded or "[Interface]" in decoded:
            return decoded
    except (binascii.Error, ValueError):
        pass
    return text


def _parse_port(raw) -> int:
    """A port from parsed JSON: an int (never a bool) or a digit string, 1-65535.

    Plain int() both crashes (a list/dict port raises TypeError, which the
    per-line import loop never caught, so one hostile line killed the whole
    import) and silently mangles (80.5 -> 80, True -> 1). Anything else is a
    ValueError, so the bad line/config is skipped or reported as invalid.
    """
    if isinstance(raw, bool):
        raise ValueError(f"invalid port: {raw!r}")
    if isinstance(raw, int):
        port = raw
    elif isinstance(raw, str) and raw.strip().isdigit():
        port = int(raw.strip())  # may still raise ValueError for exotic digits
    else:
        raise ValueError(f"invalid port: {raw!r}")
    if not 1 <= port <= 65535:
        raise ValueError(f"port out of range: {raw!r}")
    return port


def _parse_http_socks_userinfo(userinfo: str) -> tuple[str, str]:
    if not userinfo:
        return "", ""
    if ":" in userinfo:
        user, _, pw = userinfo.partition(":")
        return unquote(user), unquote(pw)
    try:
        decoded = _b64decode(userinfo)
        if ":" in decoded:
            user, _, pw = decoded.partition(":")
            return user, pw
    except (ValueError, binascii.Error):
        pass
    return unquote(userinfo), ""

def is_proxy_url(line: str) -> bool:
    line = line.strip()
    try:
        s = urlsplit(line)
        port = s.port
    except ValueError:
        return False
    if s.scheme in ("socks", "socks5", "socks5h"):
        return bool(s.hostname and port)
    if s.scheme in ("http", "https"):
        return bool(s.hostname and port is not None and s.path in ("", "/") and not s.query)
    return False

def parse_http(link: str) -> Profile:
    s = urlsplit(link.strip())
    if s.scheme not in ("http", "https"):
        raise ValueError("not an http(s) link")
    if not s.hostname or s.port is None:
        raise ValueError("missing host or port")

    name = unquote(s.fragment) if s.fragment else f"{s.hostname}:{s.port}"
    security = "tls" if s.scheme == "https" else "none"
    sni = ""
    if security == "tls":
        try:
            ipaddress.ip_address(s.hostname.strip("[]"))
        except ValueError:
            sni = s.hostname

    netloc = s.netloc
    userinfo = netloc.rpartition("@")[0] if "@" in netloc else ""
    user, pw = _parse_http_socks_userinfo(userinfo)

    return Profile(
        name=name,
        protocol="http",
        network="tcp",
        address=s.hostname.strip("[]"),
        port=s.port,
        username=user,
        id=pw,
        security=security,
        sni=sni,
    )

def parse_socks(link: str) -> Profile:
    s = urlsplit(link.strip())
    if s.scheme not in ("socks", "socks5", "socks5h"):
        raise ValueError("not a socks link")
    if not s.hostname or s.port is None:
        raise ValueError("missing host or port")

    name = unquote(s.fragment) if s.fragment else f"{s.hostname}:{s.port}"
    netloc = s.netloc
    userinfo = netloc.rpartition("@")[0] if "@" in netloc else ""
    user, pw = _parse_http_socks_userinfo(userinfo)

    return Profile(
        name=name,
        protocol="socks",
        network="tcp",
        address=s.hostname.strip("[]"),
        port=s.port,
        username=user,
        id=pw,
        security="none",
    )

def _std_query_fields(query: str, q: dict[str, str] | None = None) -> dict:
    """Transport/TLS query keys shared by vless, trojan and the std vmess://
    URI form -- everything that means the same thing regardless of which
    protocol's credential/userinfo carries the rest of the link."""
    if q is None:
        q = {k: v[0] for k, v in parse_qs(query).items()}
    network = q.get("type", "tcp") or "tcp"
    if network == "raw":  # v2rayN's wire alias for plain tcp
        network = "tcp"
    path = q.get("path", "")
    if not path.startswith("/") and unquote(path).startswith("/"):
        path = unquote(path)
    extra = q.get("extra", "")
    if extra:
        try:
            json.loads(extra)
        except (ValueError, RecursionError):
            try:
                json.loads(unquote(extra))
            except (ValueError, RecursionError):
                pass
            else:
                extra = unquote(extra)
    insecure = (q.get("allowInsecure") or q.get("insecure") or "").strip().lower()
    return {
        "network": network,
        "security": q.get("security", "none") or "none",
        "sni": q.get("sni", ""),
        "fp": q.get("fp", ""),
        "alpn": q.get("alpn", ""),
        "pbk": q.get("pbk", ""),
        "sid": q.get("sid", ""),
        "spx": q.get("spx", ""),
        "pqv": q.get("pqv", ""),
        "path": path,
        "host": q.get("host", ""),
        "service_name": q.get("serviceName", ""),
        "header_type": q.get("headerType", ""),
        "xhttp_mode": q.get("mode", ""),
        "xhttp_extra": extra,
        "allow_insecure": insecure in ("1", "true"),
        "ech": q.get("ech", ""),
        "pcs": normalize_pcs(q.get("pcs", "")),
        "vcn": q.get("vcn", ""),
    }


def parse_vless(url: str) -> Profile:
    s = urlsplit(url.strip())
    if s.scheme != "vless" or not s.hostname:
        raise ValueError("not a vless:// link")
    q = {k: v[0] for k, v in parse_qs(s.query).items()}
    fields = _std_query_fields(s.query, q=q)
    name = unquote(s.fragment) if s.fragment else (s.hostname or "")
    return Profile(
        name=name or s.hostname,
        protocol="vless",
        address=s.hostname,
        port=s.port or 443,
        id=unquote(s.username or ""),
        encryption=q.get("encryption", "none") or "none",
        flow=q.get("flow", ""),
        **fields,
    )


def parse_trojan(url: str) -> Profile:
    s = urlsplit(url.strip())
    if s.scheme != "trojan" or not s.hostname:
        raise ValueError("not a trojan:// link")
    q = {k: v[0] for k, v in parse_qs(s.query).items()}
    fields = _std_query_fields(s.query, q=q)
    name = unquote(s.fragment) if s.fragment else (s.hostname or "")
    return Profile(
        name=name or s.hostname,
        protocol="trojan",
        address=s.hostname,
        port=s.port or 443,
        id=unquote(s.username or ""),
        **fields,
    )


def _parse_std_vmess(url: str) -> Profile:
    """vmess://uuid@host:port?...#name -- the newer, non-base64 form."""
    s = urlsplit(url)
    if s.scheme != "vmess" or not s.hostname or not s.username:
        raise ValueError("not a std vmess:// link")
    q = {k: v[0] for k, v in parse_qs(s.query).items()}
    fields = _std_query_fields(s.query, q=q)
    name = unquote(s.fragment) if s.fragment else (s.hostname or "")
    return Profile(
        name=name or s.hostname,
        protocol="vmess",
        address=s.hostname,
        port=s.port or 443,
        id=unquote(s.username or ""),
        vmess_security="auto",
        **fields,
    )


def _vmess_json_profile(data: dict) -> Profile:
    """The legacy base64(JSON) vmess:// form. `type` doubles as the xhttp
    mode or the raw/tcp header type depending on `net`; grpc uses host as
    the service authority and path as the service name, same as v2rayN."""
    net = str(data.get("net") or "tcp").strip() or "tcp"
    if net == "raw":
        net = "tcp"
    host = str(data.get("host") or "")
    path = str(data.get("path") or "")
    service_name = ""
    if net == "grpc":
        service_name, path = path, ""
    type_field = str(data.get("type") or "")
    insecure = str(data.get("insecure") or "").strip().lower()
    return Profile(
        name=str(data.get("ps") or data.get("add") or "imported"),
        protocol="vmess",
        address=str(data.get("add") or ""),
        port=_parse_port(data["port"]) if data.get("port") not in (None, "") else 443,
        id=str(data.get("id") or ""),
        vmess_security=str(data.get("scy") or "auto") or "auto",
        network=net,
        security=str(data.get("tls") or "none") or "none",
        sni=str(data.get("sni") or ""),
        fp=str(data.get("fp") or ""),
        alpn=str(data.get("alpn") or ""),
        path=path,
        host=host,
        service_name=service_name,
        header_type=type_field if net == "tcp" else "",
        xhttp_mode=type_field if net == "xhttp" else "",
        allow_insecure=insecure in ("1", "true"),
        vcn=str(data.get("vcn") or ""),
        pcs=normalize_pcs(str(data.get("pcs") or "")),
    )


def parse_vmess(url: str) -> Profile:
    s = url.strip()
    if not s.startswith("vmess://"):
        raise ValueError("not a vmess:// link")
    body = s[len("vmess://"):]
    head = body.split("?", 1)[0].split("#", 1)[0]
    if "@" in head:
        try:
            return _parse_std_vmess(s)
        except ValueError:
            pass  # fall through to the base64 JSON form below
    try:
        data = json.loads(_b64decode(body))
    except (ValueError, binascii.Error, RecursionError) as e:
        raise ValueError("not a valid vmess:// link") from e
    if not isinstance(data, dict):
        raise ValueError("not a valid vmess:// link")
    return _vmess_json_profile(data)


def _apply_ss_plugin(p: Profile, plugin_str: str) -> None:
    """v2rayN's SIP002 plugin mapping (ShadowsocksFmt.ResolveSip002):
    obfs-local (or the simple-obfs typo) with obfs=http -> tcp + an http
    header carrying the obfs host; v2ray-plugin mode=websocket -> ws
    (+tls). Anything else this app cannot actually reproduce in an Xray
    config, so the caller must drop the whole link rather than connect
    silently without the plugin's obfuscation.
    """
    if not plugin_str:
        return
    parts = [x for x in plugin_str.split(";") if x]
    if not parts:
        return
    name = "obfs-local" if parts[0] == "simple-obfs" else parts[0]
    opts: dict[str, str] = {}
    for part in parts[1:]:
        k, _, v = part.partition("=")
        opts[k] = v
    if name == "obfs-local":
        if opts.get("obfs") == "http" and opts.get("obfs-host"):
            p.network = "tcp"
            p.header_type = "http"
            p.host = opts["obfs-host"]
            return
        raise ValueError(f"unsupported obfs-local plugin options: {plugin_str}")
    if name == "v2ray-plugin":
        if opts.get("mode", "websocket") != "websocket":
            raise ValueError(f"unsupported v2ray-plugin mode: {plugin_str}")
        p.network = "ws"
        if opts.get("host"):
            p.host = opts["host"]
        if opts.get("path"):
            p.path = opts["path"].replace("\\=", "=").replace("\\,", ",").replace("\\\\", "\\")
        if "tls" in opts:
            p.security = "tls"
        return
    raise ValueError(f"unsupported ss plugin: {name}")


_SS_LEGACY_RE = re.compile(r"^(?P<method>.+?):(?P<password>.*)@(?P<host>.+?):(?P<port>\d+)$")


def _parse_ss_legacy(url: str) -> Profile | None:
    """ss://base64(method:password@host:port)#tag -- the whole authority is
    base64'd as one blob. Returns None (not a ValueError) when `url` isn't
    this form at all, so the caller can fall through to SIP002 instead of
    treating "not legacy" as "not a valid link"."""
    body = url[len("ss://"):]
    body, _, frag = body.partition("#")
    try:
        decoded = _b64decode(body.rstrip("/"))
    except (binascii.Error, ValueError):
        return None
    m = _SS_LEGACY_RE.match(decoded)
    if not m:
        return None
    host = m.group("host")
    name = unquote(frag) if frag else host
    return Profile(
        name=name or host, protocol="shadowsocks", address=host,
        port=int(m.group("port")), id=m.group("password"), ss_method=m.group("method"),
        network="tcp", security="none",
    )


def _parse_ss_sip002(url: str) -> Profile:
    s = urlsplit(url)
    if s.scheme != "ss" or not s.hostname:
        raise ValueError("not a ss:// link")
    if s.password is not None:
        # 2022-blake3 ciphers: method:password in the clear, unquoted --
        # the password itself is already base64 and would double-decode.
        # urlsplit already split userinfo on the first ":" for us.
        method, password = unquote(s.username or ""), unquote(s.password or "")
    else:
        try:
            decoded = _b64decode(unquote(s.username or ""))
        except (binascii.Error, ValueError) as e:
            raise ValueError("invalid ss:// userinfo") from e
        method, _, password = decoded.partition(":")
    if not method or not password:
        raise ValueError("ss:// link is missing method or password")
    q = {k: v[0] for k, v in parse_qs(s.query).items()}
    name = unquote(s.fragment) if s.fragment else (s.hostname or "")
    p = Profile(
        name=name or s.hostname, protocol="shadowsocks", address=s.hostname,
        port=s.port or 8388, id=password, ss_method=method,
        network="tcp", security="none",
    )
    plugin = q.get("plugin", "")
    try:
        _apply_ss_plugin(p, plugin)
    except ValueError:
        # Retry only unsupported specs with encoded separators. Valid specs
        # may contain literal escapes in option values and must stay intact.
        if not re.search(r"%3[bd]", plugin, re.IGNORECASE):
            raise
        _apply_ss_plugin(p, unquote(plugin))
    return p


def parse_shadowsocks(url: str) -> Profile:
    url = url.strip()
    if not url.startswith("ss://"):
        raise ValueError("not a ss:// link")
    legacy = _parse_ss_legacy(url)
    return legacy if legacy is not None else _parse_ss_sip002(url)


def _query_map(query: str) -> dict[str, str]:
    # parse_qs treats '+' as space, which corrupts WireGuard keys.
    out: dict[str, str] = {}
    for part in query.split("&"):
        if not part:
            continue
        key, _, val = part.partition("=")
        out[unquote(key).lower()] = unquote(val)
    return out


def _q(query: dict[str, str], *names: str) -> str:
    for name in names:
        if name in query and query[name]:
            return query[name]
    return ""


def _split_endpoint(ep: str) -> tuple[str, int]:
    ep = ep.strip()
    if not ep:
        return "", 51820
    if ep.startswith("["):
        host, _, rest = ep[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else "51820"
        return host, int(port or 51820)
    host, sep, port = ep.rpartition(":")
    if not sep:
        return ep, 51820
    return host, int(port or 51820)


def parse_hysteria2(url: str) -> Profile:
    """hysteria2:// or hy2://. Auth is the userinfo, or ?auth= when the
    userinfo is absent. mport, ':' becomes '-' the same way the outbound
    builder and share.py both use, so no conversion happens either way
    here -- it's stored and re-emitted as '-' throughout.
    """
    s = urlsplit(url.strip())
    if s.scheme not in ("hysteria2", "hy2") or not s.hostname:
        raise ValueError("not a hysteria2:// link")
    q = {k: v[0] for k, v in parse_qs(s.query).items()}
    auth = unquote(s.username or "") or q.get("auth", "")
    insecure = (q.get("insecure") or "").strip().lower()
    obfs_password = q.get("obfs-password", "") if q.get("obfs") == "salamander" else ""
    name = unquote(s.fragment) if s.fragment else (s.hostname or "")
    return Profile(
        name=name or s.hostname,
        protocol="hysteria2",
        address=s.hostname,
        port=s.port or 443,
        id=auth,
        sni=q.get("sni", ""),
        alpn=q.get("alpn", ""),
        pcs=normalize_pcs(q.get("pinSHA256", "")),
        vcn=q.get("vcn", ""),
        ech=q.get("ech", ""),
        allow_insecure=insecure in ("1", "true"),
        hy2_obfs_password=obfs_password,
        hy2_ports=q.get("mport", "").replace(":", "-"),
    )


def parse_masque(url: str) -> Profile:
    """masque://[user:pass@]host:port?hv=h2&host=..&path=..&sni=..&fp=..
    &pcs=..&vcn=..&dns=..&pk=..&pub=..&addr=..#name

    The query keys are the reverse of share._masque_query. hv is the single
    h2/h3 carrier and must be one of the two; pk/pub/addr are the WARP
    identity (all-or-nothing, checked by Profile.is_valid)."""
    s = urlsplit(url.strip())
    if s.scheme != "masque" or not s.hostname:
        raise ValueError("not a masque:// link")
    q = {k: v[0] for k, v in parse_qs(s.query).items()}
    hv = (q.get("hv") or "h2").strip().lower()
    if hv not in ("h2", "h3"):
        raise ValueError("masque link has an invalid http version")
    # An explicit port 0 is a broken link, not a "use the default" signal.
    if s.port == 0:
        raise ValueError("masque link has an invalid port")
    name = unquote(s.fragment) if s.fragment else (s.hostname or "")
    return Profile(
        name=name or s.hostname,
        protocol="masque",
        address=s.hostname,
        port=s.port or 443,
        network="masque",
        security="tls",
        username=unquote(s.username or ""),
        id=unquote(s.password or ""),
        masque_http_version=hv,
        host=q.get("host", ""),
        path=q.get("path", ""),
        sni=q.get("sni", ""),
        fp=q.get("fp", ""),
        pcs=normalize_pcs(q.get("pcs", "")),
        vcn=q.get("vcn", ""),
        masque_remote_dns=q.get("dns", ""),
        masque_private_key=q.get("pk", ""),
        masque_public_key=q.get("pub", ""),
        masque_addresses=q.get("addr", ""),
    )


def parse_wireguard(url: str) -> Profile:
    s = urlsplit(url.strip())
    if s.scheme not in ("wireguard", "wg") or not s.hostname:
        raise ValueError("not a wireguard:// link")
    q = _query_map(s.query)
    secret = unquote(s.username or "") or _q(q, "privatekey", "secretkey", "secret")
    pbk = _q(q, "publickey", "public_key", "peerpublickey", "pk")
    if not secret or not pbk:
        raise ValueError("wireguard link is missing private or peer public key")
    name = unquote(s.fragment) if s.fragment else (s.hostname or "WireGuard")
    mtu = _q(q, "mtu")
    keepalive = _q(q, "keepalive", "persistentkeepalive", "keep_alive")
    return Profile(
        name=name or s.hostname,
        protocol="wireguard",
        address=s.hostname,
        port=s.port or 51820,
        id=secret,
        pbk=pbk,
        wg_local_address=_q(q, "address", "ip", "localaddress", "local_address"),
        wg_preshared=_q(q, "presharedkey", "preshared_key", "psk"),
        wg_reserved=_q(q, "reserved"),
        wg_mtu=int(mtu) if mtu.isdigit() else 1420,
        wg_keepalive=int(keepalive) if keepalive.isdigit() else 0,
    )


def _ini_sections(text: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().lower()
            sections.setdefault(current, {})
            continue
        if "=" not in line or not current:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip().lower(), val.strip()
        prev = sections[current].get(key)
        sections[current][key] = f"{prev}, {val}" if prev else val
    return sections


def parse_wg_conf(text: str) -> Profile:
    sections = _ini_sections(text)
    iface = sections.get("interface") or {}
    peer = sections.get("peer") or {}
    secret = iface.get("privatekey", "")
    pbk = peer.get("publickey", "")
    if not secret or not pbk:
        raise ValueError("WireGuard config is missing PrivateKey or PublicKey")
    host, port = _split_endpoint(peer.get("endpoint", ""))
    if not host:
        raise ValueError("WireGuard config is missing Endpoint")
    mtu = iface.get("mtu", "")
    keepalive = peer.get("persistentkeepalive", "")
    return Profile(
        name=host,
        protocol="wireguard",
        address=host,
        port=port,
        id=secret,
        pbk=pbk,
        wg_local_address=iface.get("address", ""),
        wg_preshared=peer.get("presharedkey", ""),
        wg_mtu=int(mtu) if mtu.isdigit() else 1420,
        wg_keepalive=int(keepalive) if keepalive.isdigit() else 0,
    )


def _looks_like_wg_conf(text: str) -> bool:
    low = text.lower()
    return "[interface]" in low and "privatekey" in low and "[peer]" in low


def parse_share_text(text: str) -> list[Profile]:
    # Notepad and many Windows tools start a UTF-8 file with a BOM. Left in, the
    # first link matched no scheme and a base64 body did not decode at all.
    body = _maybe_b64(text.lstrip("\ufeff"))
    out: list[Profile] = []
    if _looks_like_wg_conf(body):
        # A pasted blob can hold a conf and share links; keep both.
        try:
            conf = parse_wg_conf(body)
        except ValueError:
            conf = None
        if conf is not None and conf.is_valid():
            out.append(conf)
    for line in body.splitlines():
        line = line.strip()
        try:
            if line.startswith("vless://"):
                p = parse_vless(line)
            elif line.startswith("vmess://"):
                p = parse_vmess(line)
            elif line.startswith("trojan://"):
                p = parse_trojan(line)
            elif line.startswith("ss://"):
                p = parse_shadowsocks(line)
            elif line.startswith("hysteria2://") or line.startswith("hy2://"):
                p = parse_hysteria2(line)
            elif line.startswith("wireguard://") or line.startswith("wg://"):
                p = parse_wireguard(line)
            elif line.startswith("masque://"):
                p = parse_masque(line)
            elif line.startswith(("socks://", "socks5://", "socks5h://")):
                p = parse_socks(line)
            elif line.startswith(("http://", "https://")) and is_proxy_url(line):
                p = parse_http(line)
            else:
                continue
        except (ValueError, TypeError):
            continue
        # A malformed link a scheme-specific parser didn't reject outright
        # (a vmess link with no "add", a trojan link with no password) must
        # not surface as a profile that will just fail every connect.
        if p.is_valid():
            out.append(p)
    return out


def parse_subscription(text: str) -> list[Profile]:
    body = text.lstrip("﻿").strip()
    if not body.startswith(("{", "[")):
        try:
            decoded = _b64decode(body).lstrip("﻿").strip()
        except ValueError:
            pass
        else:
            if decoded.startswith(("{", "[")):
                body = decoded
    if not body.startswith(("{", "[")) or _looks_like_wg_conf(body):
        return parse_share_text(body)
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return []
    profiles = []
    for item in data if isinstance(data, list) else [data]:
        try:
            if isinstance(item, dict):
                profiles.append(_profile_from_json_dict(item))
        except (ValueError, TypeError, AttributeError, IndexError, OverflowError):
            continue
    return profiles


def _first_dict(value) -> dict:
    # Xray lists a single object here (vnext, servers, peers, users), but a
    # panel may wrap it as an object; indexing that raised KeyError, which
    # aborted a whole subscription instead of skipping the one bad entry. A
    # wrong shape now reads as empty and fails is_valid() like any other.
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _profile_from_wg_outbound(proxy: dict) -> Profile:
    settings = proxy.get("settings") or {}
    peer = _first_dict(settings.get("peers"))
    host, port = _split_endpoint(str(peer.get("endpoint", "")))
    addrs = settings.get("address") or []
    if isinstance(addrs, str):
        local = addrs
    else:
        local = ", ".join(str(a) for a in addrs)
    reserved = settings.get("reserved") or []
    reserved_s = ",".join(str(x) for x in reserved) if isinstance(reserved, list) else str(reserved)
    return Profile(
        name=host or "WireGuard",
        protocol="wireguard",
        address=host,
        port=port,
        id=settings.get("secretKey") or settings.get("secretkey") or "",
        pbk=peer.get("publicKey") or peer.get("publickey") or "",
        wg_local_address=local,
        wg_preshared=peer.get("preSharedKey") or peer.get("presharedkey") or "",
        wg_reserved=reserved_s,
        wg_mtu=int(settings.get("mtu") or 1420),
        wg_keepalive=int(peer.get("keepAlive") or peer.get("keepalive") or 0),
    )


def _stream_fields(stream: dict) -> dict:
    """streamSettings -> the Profile transport/TLS fields shared by every
    stream-based protocol (vless, vmess, trojan, shadowsocks) -- the
    reverse of core/outbounds/_common.py's stream_settings."""
    security = stream.get("security", "none")
    network = stream.get("network", "tcp")
    tls = stream.get("tlsSettings", {}) if security == "tls" else {}
    reality = stream.get("realitySettings", {}) if security == "reality" else {}
    alpn = tls.get("alpn", [])

    path = host = service_name = header_type = xhttp_mode = xhttp_extra = ""
    if network == "ws":
        ws = stream.get("wsSettings", {}) or {}
        path = ws.get("path", "")
        headers = ws.get("headers", {}) or {}
        host = headers.get("Host") or headers.get("host") or ""
    elif network == "grpc":
        grpc = stream.get("grpcSettings", {}) or {}
        service_name = grpc.get("serviceName", "")
    elif network in ("h2", "http"):
        h2 = stream.get("httpSettings", {}) or {}
        path = h2.get("path", "")
        h2_host = h2.get("host", [])
        host = ",".join(h2_host) if isinstance(h2_host, list) else str(h2_host)
    elif network == "xhttp":
        xh = stream.get("xhttpSettings", {}) or {}
        path = xh.get("path", "")
        host = xh.get("host", "")
        xhttp_mode = xh.get("mode", "")
        extra = xh.get("extra")
        if isinstance(extra, dict):
            xhttp_extra = json.dumps(extra, ensure_ascii=False)
    elif network == "httpupgrade":
        hu = stream.get("httpupgradeSettings", {}) or {}
        path = hu.get("path", "")
        host = hu.get("host", "")
    elif network == "tcp":
        tcp = stream.get("tcpSettings", {}) or {}
        header = tcp.get("header", {}) or {}
        if header.get("type") == "http":
            header_type = "http"
            request = header.get("request", {}) or {}
            paths = request.get("path") or []
            path = paths[0] if paths else ""
            hdr_hosts = (request.get("headers") or {}).get("Host") or []
            host = ",".join(hdr_hosts) if isinstance(hdr_hosts, list) else str(hdr_hosts)

    return {
        "network": network,
        "security": security,
        "sni": tls.get("serverName", "") or reality.get("serverName", ""),
        "fp": tls.get("fingerprint", "") or reality.get("fingerprint", ""),
        "alpn": ",".join(alpn) if isinstance(alpn, list) else str(alpn),
        "pbk": reality.get("publicKey", ""),
        "sid": reality.get("shortId", ""),
        "spx": reality.get("spiderX", ""),
        "pqv": reality.get("mldsa65Verify", ""),
        "path": path,
        "host": host,
        "service_name": service_name,
        "header_type": header_type,
        "xhttp_mode": xhttp_mode,
        "xhttp_extra": xhttp_extra,
        "ech": tls.get("echConfigList", ""),
        "pcs": normalize_pcs(tls.get("pinnedPeerCertSha256", "")),
        "vcn": tls.get("verifyPeerCertByName", ""),
    }


def _profile_from_vless_outbound(proxy: dict) -> Profile:
    vnext = _first_dict(proxy.get("settings", {}).get("vnext"))
    user = _first_dict(vnext.get("users"))
    return Profile(
        name=vnext.get("address", "imported"),
        protocol=proxy.get("protocol", "vless"),
        address=vnext.get("address", ""),
        port=_parse_port(vnext.get("port", 443)),
        id=user.get("id", ""),
        encryption=user.get("encryption", "none") or "none",
        flow=user.get("flow", ""),
        **_stream_fields(proxy.get("streamSettings", {})),
    )


def _profile_from_vmess_outbound(proxy: dict) -> Profile:
    vnext = _first_dict(proxy.get("settings", {}).get("vnext"))
    user = _first_dict(vnext.get("users"))
    return Profile(
        name=vnext.get("address", "imported"),
        protocol="vmess",
        address=vnext.get("address", ""),
        port=_parse_port(vnext.get("port", 443)),
        id=user.get("id", ""),
        vmess_security=user.get("security", "auto") or "auto",
        **_stream_fields(proxy.get("streamSettings", {})),
    )


def _profile_from_trojan_outbound(proxy: dict) -> Profile:
    server = _first_dict(proxy.get("settings", {}).get("servers"))
    return Profile(
        name=server.get("address", "imported"),
        protocol="trojan",
        address=server.get("address", ""),
        port=_parse_port(server.get("port", 443)),
        id=server.get("password", ""),
        **_stream_fields(proxy.get("streamSettings", {})),
    )


def _profile_from_ss_outbound(proxy: dict) -> Profile:
    server = _first_dict(proxy.get("settings", {}).get("servers"))
    return Profile(
        name=server.get("address", "imported"),
        protocol="shadowsocks",
        address=server.get("address", ""),
        port=_parse_port(server.get("port", 443)),
        id=server.get("password", ""),
        ss_method=server.get("method", ""),
        **_stream_fields(proxy.get("streamSettings", {})),
    )


def _profile_from_hysteria2_outbound(proxy: dict) -> Profile:
    settings = proxy.get("settings") or {}
    stream = proxy.get("streamSettings") or {}
    tls = stream.get("tlsSettings") or {}
    hy = stream.get("hysteriaSettings") or {}
    finalmask = stream.get("finalmask") or {}
    quic = finalmask.get("quicParams") or {}
    hop = quic.get("udpHop") or {}
    obfs_password = ""
    for mask in finalmask.get("udp") or []:
        if isinstance(mask, dict) and mask.get("type") == "salamander":
            obfs_password = (mask.get("settings") or {}).get("password", "")
            break
    alpn = tls.get("alpn", [])
    up = str(quic.get("brutalUp") or "").removesuffix("mbps")
    down = str(quic.get("brutalDown") or "").removesuffix("mbps")
    return Profile(
        name=settings.get("address", "imported"),
        protocol="hysteria2",
        address=settings.get("address", ""),
        port=_parse_port(settings.get("port", 443)),
        id=hy.get("auth", ""),
        sni=tls.get("serverName", ""),
        alpn=",".join(alpn) if isinstance(alpn, list) else str(alpn),
        pcs=normalize_pcs(tls.get("pinnedPeerCertSha256", "")),
        vcn=tls.get("verifyPeerCertByName", ""),
        hy2_obfs_password=obfs_password,
        hy2_ports=hop.get("ports", ""),
        hy2_hop_interval=str(hop.get("interval") or ""),
        hy2_up_mbps=int(up) if up.isdigit() else 0,
        hy2_down_mbps=int(down) if down.isdigit() else 0,
    )


def _masque_http_version(alpn: object) -> str:
    # Xray picks the h2 carrier only when h2 is advertised and h3 is not;
    # anything else (including omitted/empty) is h3.
    if alpn is None:
        return "h3"
    if not isinstance(alpn, list) or not all(isinstance(a, str) for a in alpn):
        raise ValueError("masque alpn must be a list of strings")
    return "h2" if "h2" in alpn and "h3" not in alpn else "h3"


def _masque_str(mapping: dict, key: str, default: str = "") -> str:
    # A hand-edited or corrupt config can hold any JSON type in a field that
    # must be a string; reject it here rather than let it crash downstream.
    value = mapping.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"masque {key} must be a string")
    return value


def _profile_from_masque_outbound(proxy: dict) -> Profile:
    if not isinstance(proxy, dict):
        raise ValueError("masque outbound must be an object")
    settings = proxy.get("settings") or {}
    stream = proxy.get("streamSettings") or {}
    if not isinstance(settings, dict) or not isinstance(stream, dict):
        raise ValueError("masque settings/streamSettings must be objects")
    masque = stream.get("masqueSettings") or {}
    tls = stream.get("tlsSettings") or {}
    if not isinstance(masque, dict) or not isinstance(tls, dict):
        raise ValueError("masque masqueSettings/tlsSettings must be objects")
    # Xray accepts the transport as streamSettings.method (docs) or the
    # legacy network key; a conflicting pair is a broken config.
    network = _masque_str(stream, "network").lower()
    method = _masque_str(stream, "method").lower()
    if network and method and network != method:
        raise ValueError("masque outbound network/method conflict")
    if network != "masque" and method != "masque":
        raise ValueError("masque outbound has an incompatible network")
    if _masque_str(stream, "security").lower() != "tls":
        raise ValueError("masque outbound requires tls security")
    port = settings.get("port", 443)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("masque port must be an integer 1-65535")
    address = _masque_str(settings, "address")
    dns = settings.get("remoteDNS") or []
    if isinstance(dns, str):
        dns = [dns]
    if not isinstance(dns, list) or not all(isinstance(d, str) for d in dns):
        raise ValueError("masque remoteDNS must be a list of strings")
    # An explicit warp object is a WARP identity attempt: it must be complete
    # and well-typed, never silently dropped to anonymous generic MASQUE.
    if "warp" in masque:
        warp = masque["warp"]
        if not isinstance(warp, dict):
            raise ValueError("masque warp must be an object")
        priv = _masque_str(warp, "privateKey")
        pub = _masque_str(warp, "publicKey")
        addr = warp.get("address")
        if not isinstance(addr, list) or not addr \
                or not all(isinstance(a, str) for a in addr):
            raise ValueError("masque warp address must be a non-empty list of strings")
        if not (priv and pub):
            raise ValueError("masque warp identity is incomplete")
        masque_private_key, masque_public_key = priv, pub
        masque_addresses = ", ".join(addr)
    else:
        masque_private_key = masque_public_key = masque_addresses = ""
    return Profile(
        name=_masque_str(masque, "host") or address or "imported",
        protocol="masque",
        address=address,
        port=port,
        network="masque",
        security="tls",
        username=_masque_str(masque, "user"),
        id=_masque_str(masque, "pass"),
        host=_masque_str(masque, "host"),
        path=_masque_str(masque, "path"),
        sni=_masque_str(tls, "serverName"),
        fp=_masque_str(tls, "fingerprint"),
        pcs=normalize_pcs(_masque_str(tls, "pinnedPeerCertSha256")),
        vcn=_masque_str(tls, "verifyPeerCertByName"),
        masque_http_version=_masque_http_version(tls.get("alpn")),
        masque_remote_dns=", ".join(dns),
        masque_private_key=masque_private_key,
        masque_public_key=masque_public_key,
        masque_addresses=masque_addresses,
    )


_KNOWN_PROTOCOLS = ("vless", "vmess", "trojan", "shadowsocks", "hysteria",
                    "wireguard", "masque")


def _profile_from_config(cfg: dict) -> Profile:
    outbounds = cfg.get("outbounds", [])
    if not isinstance(outbounds, list):
        outbounds = []  # a panel may give an object here; skip, never abort
    proxy = next((o for o in outbounds if isinstance(o, dict) and o.get("tag") == "proxy"), None)
    if proxy is None:
        proxy = next(
            (o for o in outbounds if isinstance(o, dict)
             and o.get("protocol") in _KNOWN_PROTOCOLS), None,
        )
    if proxy is None:
        raise ValueError("no proxy outbound in config")
    protocol = (proxy.get("protocol") or "").lower()
    if protocol == "wireguard":
        return _profile_from_wg_outbound(proxy)
    if protocol == "trojan":
        return _profile_from_trojan_outbound(proxy)
    if protocol == "shadowsocks":
        return _profile_from_ss_outbound(proxy)
    if protocol == "vmess":
        return _profile_from_vmess_outbound(proxy)
    if protocol == "hysteria":
        return _profile_from_hysteria2_outbound(proxy)
    if protocol == "masque":
        return _profile_from_masque_outbound(proxy)
    return _profile_from_vless_outbound(proxy)


def _profile_from_json_dict(data: dict) -> Profile:
    if "outbounds" in data:
        p = _profile_from_config(data)
    else:
        # uid/sub_uid are this app's own internal ids (a file name and a
        # subscription link), never part of a server's settings: keeping one
        # from an imported file would let a config overwrite a stored profile
        # or sign itself up to someone's subscription.
        data = {k: v for k, v in data.items() if k not in ("uid", "sub_uid")}
        p = Profile.from_dict(data)
    if not p.is_valid():
        raise ValueError("config has no address or credential for its protocol")
    return p


def parse_json(text: str) -> Profile:
    stripped = text.strip()
    if _looks_like_wg_conf(stripped):
        return parse_wg_conf(stripped)
    try:
        data = json.loads(text)
    except RecursionError as e:
        raise ValueError("invalid JSON: too deeply nested") from e
    if not isinstance(data, dict):
        raise ValueError("unsupported JSON shape")
    return _profile_from_json_dict(data)


def parse_qr(image_path: str) -> list[Profile]:
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError("QR support requires opencv-python-headless") from e
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"cannot read image: {image_path}")
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    if not data:
        raise ValueError("no QR code found")
    p: Profile | None = None
    if data.startswith("vless://"):
        p = parse_vless(data)
    elif data.startswith("vmess://"):
        p = parse_vmess(data)
    elif data.startswith("trojan://"):
        p = parse_trojan(data)
    elif data.startswith("ss://"):
        p = parse_shadowsocks(data)
    elif data.startswith("hysteria2://") or data.startswith("hy2://"):
        p = parse_hysteria2(data)
    elif data.startswith("wireguard://") or data.startswith("wg://"):
        p = parse_wireguard(data)
    if p is not None:
        if not p.is_valid():
            raise ValueError("QR link has no address or credential for its protocol")
        return [p]
    if data.lstrip().startswith(("{", "[")):
        return [parse_json(data)]
    return parse_share_text(data)
