"""Parse share formats into Profile objects: vless://, base64 sub, JSON, QR."""
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
        if "://" in decoded:
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


def parse_share_text(text: str) -> list[Profile]:
    body = _maybe_b64(text)
    out: list[Profile] = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("vless://"):
            try:
                out.append(parse_vless(line))
            except ValueError:
                continue
    return out


def parse_subscription(text: str) -> list[Profile]:
    return parse_share_text(text)


def _profile_from_config(cfg: dict) -> Profile:
    outbounds = cfg.get("outbounds", [])
    proxy = next(
        (o for o in outbounds if o.get("tag") == "proxy"),
        next((o for o in outbounds if o.get("protocol") == "vless"), None),
    )
    if proxy is None:
        raise ValueError("no vless/proxy outbound in config")
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
    if data.lstrip().startswith(("{", "[")):
        return [parse_json(data)]
    return parse_share_text(data)
