"""Parse share formats into Profile objects: vless://, wireguard://, .conf, JSON, QR."""
from __future__ import annotations

import base64
import binascii
import json
from urllib.parse import parse_qs, unquote, urlsplit

from .profiles import Profile


def _b64decode(text: str) -> str:
    s = text.strip().replace("\n", "").replace("\r", "")
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


def parse_vless(url: str) -> Profile:
    s = urlsplit(url.strip())
    if s.scheme != "vless" or not s.hostname:
        raise ValueError("not a vless:// link")
    q = {k: v[0] for k, v in parse_qs(s.query).items()}
    name = unquote(s.fragment) if s.fragment else (s.hostname or "")
    return Profile(
        name=name or s.hostname,
        protocol="vless",
        address=s.hostname,
        port=s.port or 443,
        id=unquote(s.username or ""),
        encryption=q.get("encryption", "none") or "none",
        flow=q.get("flow", ""),
        network=q.get("type", "tcp"),
        security=q.get("security", "none"),
        sni=q.get("sni", ""),
        fp=q.get("fp", ""),
        alpn=q.get("alpn", ""),
        pbk=q.get("pbk", ""),
        sid=q.get("sid", ""),
        spx=q.get("spx", ""),
        path=unquote(q.get("path", "")),
        host=q.get("host", ""),
        service_name=q.get("serviceName", ""),
    )


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
    body = _maybe_b64(text)
    if _looks_like_wg_conf(body):
        return [parse_wg_conf(body)]
    out: list[Profile] = []
    for line in body.splitlines():
        line = line.strip()
        try:
            if line.startswith("vless://"):
                out.append(parse_vless(line))
            elif line.startswith("wireguard://") or line.startswith("wg://"):
                out.append(parse_wireguard(line))
        except ValueError:
            continue
    return out


def parse_subscription(text: str) -> list[Profile]:
    return parse_share_text(text)


def _profile_from_wg_outbound(proxy: dict) -> Profile:
    settings = proxy.get("settings") or {}
    peer = (settings.get("peers") or [{}])[0]
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


def _profile_from_config(cfg: dict) -> Profile:
    outbounds = cfg.get("outbounds", [])
    proxy = next((o for o in outbounds if o.get("tag") == "proxy"), None)
    if proxy is None:
        proxy = next(
            (o for o in outbounds if o.get("protocol") in ("vless", "wireguard")),
            None,
        )
    if proxy is None:
        raise ValueError("no vless/wireguard/proxy outbound in config")
    if (proxy.get("protocol") or "").lower() == "wireguard":
        return _profile_from_wg_outbound(proxy)
    vnext = proxy.get("settings", {}).get("vnext", [{}])[0]
    user = (vnext.get("users") or [{}])[0]
    stream = proxy.get("streamSettings", {})
    security = stream.get("security", "none")
    tls = stream.get("tlsSettings", {}) if security == "tls" else {}
    reality = stream.get("realitySettings", {}) if security == "reality" else {}
    alpn = tls.get("alpn", [])
    return Profile(
        name=vnext.get("address", "imported"),
        protocol=proxy.get("protocol", "vless"),
        address=vnext.get("address", ""),
        port=int(vnext.get("port", 443)),
        id=user.get("id", ""),
        encryption=user.get("encryption", "none") or "none",
        flow=user.get("flow", ""),
        network=stream.get("network", "tcp"),
        security=security,
        sni=tls.get("serverName", "") or reality.get("serverName", ""),
        fp=tls.get("fingerprint", "") or reality.get("fingerprint", ""),
        alpn=",".join(alpn) if isinstance(alpn, list) else str(alpn),
        pbk=reality.get("publicKey", ""),
        sid=reality.get("shortId", ""),
        spx=reality.get("spiderX", ""),
    )


def parse_json(text: str) -> Profile:
    stripped = text.strip()
    if _looks_like_wg_conf(stripped):
        return parse_wg_conf(stripped)
    data = json.loads(text)
    if isinstance(data, dict) and "outbounds" in data:
        return _profile_from_config(data)
    if isinstance(data, dict):
        return Profile.from_dict(data)
    raise ValueError("unsupported JSON shape")


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
    if data.startswith("vless://"):
        return [parse_vless(data)]
    if data.startswith("wireguard://") or data.startswith("wg://"):
        return [parse_wireguard(data)]
    if data.lstrip().startswith(("{", "[")):
        return [parse_json(data)]
    return parse_share_text(data)
