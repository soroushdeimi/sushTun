"""Profiles: normalized proxy settings persisted as profiles/<uid>.json."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, fields

from .. import paths


@dataclass
class Profile:
    name: str = "New profile"
    protocol: str = "vless"
    address: str = ""
    port: int = 443
    id: str = ""
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
    path: str = ""
    host: str = ""
    service_name: str = ""
    sub_uid: str = ""
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def endpoint(self) -> str:
        return f"{self.address}:{self.port}"


class ProfileStore:
    def __init__(self) -> None:
        self.dir = paths.profiles_dir()

    def _path(self, uid: str):
        return self.dir / f"{uid}.json"

    def list(self) -> list[Profile]:
        self.dir.mkdir(parents=True, exist_ok=True)
        items = []
        for p in self.dir.glob("*.json"):
            try:
                items.append(Profile.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except (ValueError, OSError):
                continue
        return sorted(items, key=lambda x: x.name.lower())

    def get(self, uid: str) -> Profile | None:
        p = self._path(uid)
        if not p.exists():
            return None
        return Profile.from_dict(json.loads(p.read_text(encoding="utf-8")))

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
