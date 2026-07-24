"""Subscriptions: fetch a sub URL, parse quota/expiry, and refresh profiles."""
from __future__ import annotations

import json
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field

from .. import paths
from . import importer
from .profiles import ProfileStore

_UA = "v2rayNG/1.8.5"


@dataclass
class Usage:
    upload: int = 0
    download: int = 0
    total: int = 0
    expire: int = 0  # epoch seconds; 0 = unknown / unlimited

    @property
    def used(self) -> int:
        return self.upload + self.download

    @property
    def remaining(self) -> int:
        return max(self.total - self.used, 0) if self.total else 0

    @property
    def percent_left(self) -> float | None:
        return (self.remaining / self.total) if self.total else None

    @property
    def days_left(self) -> float | None:
        return (self.expire - time.time()) / 86400 if self.expire else None


@dataclass
class Subscription:
    url: str = ""
    name: str = "Subscription"
    usage: Usage = field(default_factory=Usage)
    updated: float = 0.0
    profile_uids: list[str] = field(default_factory=list)
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Subscription":
        usage = Usage(**{k: v for k, v in (data.get("usage") or {}).items()
                         if k in Usage.__dataclass_fields__})
        return cls(
            url=data.get("url", ""),
            name=data.get("name", "Subscription"),
            usage=usage,
            updated=data.get("updated", 0.0),
            profile_uids=list(data.get("profile_uids", [])),
            uid=data.get("uid", uuid.uuid4().hex),
        )


def parse_userinfo(header: str) -> Usage:
    fields: dict[str, int] = {}
    for part in header.split(";"):
        if "=" in part:
            key, val = part.split("=", 1)
            try:
                fields[key.strip().lower()] = int(val.strip())
            except ValueError:
                continue
    return Usage(
        upload=fields.get("upload", 0),
        download=fields.get("download", 0),
        total=fields.get("total", 0),
        expire=fields.get("expire", 0),
    )


def fetch(url: str, timeout: float = 20.0):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (user-provided sub URL)
        info = resp.headers.get("Subscription-Userinfo", "")
        body = resp.read().decode("utf-8", errors="replace")
    return parse_userinfo(info), importer.parse_subscription(body)


class SubscriptionStore:
    def __init__(self) -> None:
        self.file = paths.profiles_dir() / "subscriptions.json"

    def list(self) -> list[Subscription]:
        if not self.file.exists():
            return []
        try:
            return [Subscription.from_dict(d) for d in
                    json.loads(self.file.read_text(encoding="utf-8"))]
        except (ValueError, OSError):
            return []

    def _write(self, subs: list[Subscription]) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(
            json.dumps([s.to_dict() for s in subs], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def save(self, sub: Subscription) -> None:
        subs = [s for s in self.list() if s.uid != sub.uid]
        subs.append(sub)
        self._write(subs)

    def delete(self, uid: str, profiles: ProfileStore | None = None) -> None:
        subs = self.list()
        target = next((s for s in subs if s.uid == uid), None)
        if target and profiles:
            for puid in target.profile_uids:
                profiles.delete(puid)
        self._write([s for s in subs if s.uid != uid])


def refresh(sub: Subscription, profiles: ProfileStore, store: SubscriptionStore) -> Subscription:
    usage, parsed = fetch(sub.url)
    for old in sub.profile_uids:
        profiles.delete(old)
    new_uids: list[str] = []
    for p in parsed:
        p.sub_uid = sub.uid
        profiles.save(p)
        new_uids.append(p.uid)
    sub.profile_uids = new_uids
    sub.usage = usage
    sub.updated = time.time()
    store.save(sub)
    return sub
