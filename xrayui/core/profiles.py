"""Profiles: normalized proxy settings persisted as profiles/<uid>.json."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import MISSING, asdict, dataclass, field, fields

from .. import paths

# SubscriptionStore keeps its own file in this same directory; list() must
# not try to parse it as a profile.
SUBSCRIPTIONS_FILENAME = "subscriptions.json"

_PCS_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
# An ML-DSA-65 public key is 1952 bytes: 2603 characters of unpadded base64url.
_PQV_RE = re.compile(r"^[A-Za-z0-9_-]{2603}$")


def normalize_pcs(raw: str) -> str:
    """pinnedPeerCertSha256 as most hysteria2 links and cert tools hand it
    out -- "AB:CD:...", colon-separated uppercase hex -- normalized to the
    unbroken lowercase hex Xray's own pin comparison actually wants.
    Applied at every point a pcs value enters the app (import, editor
    save, render) since any of them could be the one place a stray link
    format or a hand-edited profile slipped through."""
    return re.sub(r"[:\s]", "", raw or "").lower()


def valid_pcs(raw: str) -> bool:
    """Whether `raw` is (after normalizing) exactly 64 hex characters -- a
    full SHA-256, the only shape Xray's pinnedPeerCertSha256 accepts."""
    return bool(_PCS_HEX_RE.match(normalize_pcs(raw)))


def valid_pqv(raw: str) -> bool:
    """Whether `raw` is a REALITY mldsa65Verify key Xray will accept: the
    server's ML-DSA-65 public key as unpadded base64url (1952 bytes). Xray
    refuses to start on anything else, so the whole connection would fail."""
    return bool(_PQV_RE.match((raw or "").strip()))


def _fits(default, value) -> bool:
    """Whether `value` has the type a field with this default holds."""
    if isinstance(default, bool) or isinstance(value, bool):
        return isinstance(default, bool) and isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float))
    return isinstance(value, type(default))


@dataclass
class Profile:
    name: str = "New profile"
    protocol: str = "vless"
    address: str = ""
    port: int = 443
    id: str = ""
    username: str = ""
    encryption: str = "none"
    flow: str = ""
    network: str = "tcp"
    security: str = "none"
    sni: str = ""
    fp: str = ""
    alpn: str = ""
    pbk: str = ""
    sid: str = ""
    spx: str = ""
    pqv: str = ""  # REALITY mldsa65Verify (post-quantum), link query "pqv"
    path: str = ""
    host: str = ""
    service_name: str = ""
    vmess_security: str = "auto"
    ss_method: str = ""
    header_type: str = ""
    xhttp_mode: str = ""
    xhttp_extra: str = ""
    allow_insecure: bool = False
    ech: str = ""
    pcs: str = ""
    vcn: str = ""
    hy2_obfs_password: str = ""
    hy2_ports: str = ""
    hy2_hop_interval: str = ""
    hy2_up_mbps: int = 0
    hy2_down_mbps: int = 0
    wg_local_address: str = ""
    wg_preshared: str = ""
    wg_reserved: str = ""
    wg_mtu: int = 1420
    wg_keepalive: int = 0
    sub_uid: str = ""
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        # A hand-edited or corrupt file can hold any JSON type in any field;
        # one null name used to take the whole server list down with it. A
        # value of the wrong type keeps the field's default instead.
        clean = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value, default = data[f.name], f.default
            if default is not MISSING and default is not None and not _fits(default, value):
                continue
            clean[f.name] = value
        return cls(**clean)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def endpoint(self) -> str:
        return f"{self.address}:{self.port}"

    def is_valid(self) -> bool:
        """False for a profile a broken/malformed link parsed into but that
        can never actually connect: no address, no credential, or (for the
        protocols that need one) no peer public key / cipher method."""
        if not self.address:
            return False
        if isinstance(self.port, bool) or not isinstance(self.port, int) \
                or not 1 <= self.port <= 65535:
            return False

        if self.protocol in ("http", "socks"):
            if self.protocol == "socks" and self.security not in ("", "none"):
                return False
            if self.protocol == "http" and self.security not in ("", "none", "tls"):
                return False
            return True

        if not self.id:
            return False
        if self.protocol == "wireguard" and not self.pbk:
            return False
        if self.protocol == "shadowsocks" and not self.ss_method:
            return False
        return True


class ProfileStore:
    def __init__(self) -> None:
        self.dir = paths.profiles_dir()

    def _path(self, uid: str):
        return self.dir / f"{uid}.json"

    def list(self) -> list[Profile]:
        self.dir.mkdir(parents=True, exist_ok=True)
        items = []
        for p in self.dir.glob("*.json"):
            if p.name == SUBSCRIPTIONS_FILENAME:
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            p_obj = Profile.from_dict(data)
            p_obj.uid = p.stem
            items.append(p_obj)
        return sorted(items, key=lambda x: x.name.lower())

    def get(self, uid: str) -> Profile | None:
        try:
            data = json.loads(self._path(uid).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None  # missing, or truncated by a crash or a full disk
        if isinstance(data, dict):
            p = Profile.from_dict(data)
            p.uid = uid
            return p
        return None

    def save(self, profile: Profile) -> Profile:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(profile.uid).write_text(
            json.dumps(profile.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return profile

    def delete(self, uid: str) -> None:
        self._path(uid).unlink(missing_ok=True)
        if self.active_uid() == uid:
            (self.dir / "active.txt").unlink(missing_ok=True)

    def active_uid(self) -> str | None:
        p = self.dir / "active.txt"
        return p.read_text(encoding="utf-8").strip() if p.exists() else None

    def set_active(self, uid: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "active.txt").write_text(uid, encoding="utf-8")

    def active(self) -> Profile | None:
        uid = self.active_uid()
        return self.get(uid) if uid else None
