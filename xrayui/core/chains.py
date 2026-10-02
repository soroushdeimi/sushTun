"""Ordered profile references and detached connection plans for proxy chains."""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field

from .. import paths
from ..i18n import tr
from . import coreopts, outbounds
from .profiles import Profile

SUPPORTED_PROTOCOLS = frozenset({"vless", "vmess", "trojan", "shadowsocks"})
SUPPORTED_TRANSPORTS = frozenset({"tcp", "grpc", "httpupgrade"})
_UID = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass
class Chain:
    name: str = ""
    hops: list[str] = field(default_factory=list)
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Chain:
        return cls(**{key: value for key, value in data.items()
                      if key in cls.__dataclass_fields__})


class ChainStore:
    def __init__(self) -> None:
        self.file = paths.base_dir() / "chains.json"

    def list(self) -> list[Chain]:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        if not isinstance(data, list):
            return []
        return [Chain.from_dict(item) for item in data if isinstance(item, dict)]

    def get(self, uid: str) -> Chain | None:
        return next((chain for chain in self.list() if chain.uid == uid), None)

    def _write(self, items: list[Chain]) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps([c.to_dict() for c in items], indent=2,
                                        ensure_ascii=False), encoding="utf-8")

    def save(self, chain: Chain) -> Chain:
        self._write([c for c in self.list() if c.uid != chain.uid] + [chain])
        return chain

    def delete(self, uid: str) -> None:
        self._write([c for c in self.list() if c.uid != uid])


def _valid_uid(uid) -> bool:
    return isinstance(uid, str) and _UID.fullmatch(uid) is not None


def _profile_map(profiles: Iterable[Profile] | Mapping[str, Profile]) -> dict[str, Profile]:
    items = profiles.values() if isinstance(profiles, Mapping) else profiles
    return {p.uid: p for p in items if _valid_uid(p.uid)}


def _display_name(profile: Profile | None) -> str:
    return (profile.name if profile is not None and profile.name else tr("Missing server"))


def validate(chain: Chain, profiles: Iterable[Profile] | Mapping[str, Profile]) -> list[str]:
    problems = []
    if not _valid_uid(chain.uid):
        problems.append(tr("The chain has an invalid ID."))
    if not isinstance(chain.hops, list):
        return problems + [tr("Chain hops must be a list of profile IDs.")]
    if not 2 <= len(chain.hops) <= 8:
        problems.append(tr("A chain must contain between 2 and 8 hops."))
    known = _profile_map(profiles)
    seen = set()
    for index, uid in enumerate(chain.hops, 1):
        if not _valid_uid(uid):
            problems.append(tr("Hop {hop} has an invalid profile ID.", hop=index))
            continue
        if uid in seen:
            problems.append(tr("Profile {name} is used twice in the chain.",
                               name=_display_name(known.get(uid))))
        seen.add(uid)
        profile = known.get(uid)
        if profile is None:
            problems.append(tr("The server for hop {hop} no longer exists.", hop=index))
            continue
        hop = f"{index} ({_display_name(profile)})"
        protocol = str(profile.protocol or "").lower()
        if protocol not in SUPPORTED_PROTOCOLS:
            problems.append(tr("Hop {hop}: protocol {protocol} is not verified for chains.",
                               hop=hop, protocol=protocol))
        if not profile.is_valid():
            problems.append(tr("Hop {hop} is missing an address or credential settings.", hop=hop))
        network = str(profile.network or "")
        # v26.3.27 transport/internet/splithttp/dialer.go:403-438 builds a
        # separate download stream with independent socket settings. Until
        # both paths are verified, accepting XHTTP could bypass earlier hops.
        if network == "ws":
            problems.append(tr("Hop {hop}: WebSocket (ws) chains can lose responses when "
                               "a connection closes and are not supported yet.", hop=hop))
        elif network not in SUPPORTED_TRANSPORTS:
            problems.append(tr("Hop {hop}: transport {transport} is not verified for chains "
                               "(including separate XHTTP downloads).", hop=hop, transport=network))
        # v26.3.27 proxy/vless/outbound/outbound.go:249-295 inspects the
        # underlying connection for Vision; redirected pipes need separate proof.
        if profile.flow:
            problems.append(tr("Hop {hop}: flow {flow} is not verified for chains.",
                               hop=hop, flow=profile.flow))
    return problems


@dataclass(frozen=True)
class ResolvedChain:
    uid: str
    name: str
    _profile_data: tuple[str, ...] = field(repr=False)

    @property
    def profiles(self) -> tuple[Profile, ...]:
        # Immutable serialized snapshots prevent a saved profile edit (or a
        # caller mutating a returned Profile) from changing the active path.
        return tuple(Profile.from_dict(json.loads(data)) for data in self._profile_data)

    @property
    def entry(self) -> Profile:
        return self.profiles[0]

    @property
    def exit(self) -> Profile:
        return self.profiles[-1]


def resolve(chain: Chain, profiles: Iterable[Profile] | Mapping[str, Profile]) -> ResolvedChain:
    known = _profile_map(profiles)
    problems = validate(chain, known)
    if problems:
        raise ValueError("\n".join(problems))
    return ResolvedChain(chain.uid, chain.name,
                         tuple(json.dumps(known[uid].to_dict()) for uid in chain.hops))


def check(plan: ResolvedChain, core_cfg: dict | None = None) -> None:
    profiles = plan.profiles
    problems = validate(Chain(uid=plan.uid, name=plan.name, hops=[p.uid for p in profiles]), profiles)
    # v26.3.27 app/proxyman/outbound/handler.go:213-238 dispatches mux/XUDP
    # through separate clients; the plain TCP/UDP proof does not cover them.
    if ((core_cfg or {}).get("mux") or {}).get("enabled"):
        problems.append(tr("Mux and XUDP are not verified for chains; disable mux to connect."))
    if problems:
        raise ValueError("\n".join(problems))


def build(plan: ResolvedChain, core_cfg: dict | None = None) -> list[dict]:
    """Build entry-to-exit outbounds; the exit retains the routing tag proxy."""
    check(plan, core_cfg)
    profiles = plan.profiles
    built = []
    for index, profile in enumerate(profiles):
        outbound = outbounds.build(profile, "proxy")
        if index:
            # v26.3.27 transport/internet/dialer.go:111-139,271-282 routes
            # this server dial through the preceding outbound, without falling
            # back to a system socket. AsIs passes downstream hostnames through.
            outbound["streamSettings"]["sockopt"] = {"dialerProxy": f"chain-{index}"}
        if core_cfg:
            coreopts.apply_all({"outbounds": [outbound]}, core_cfg, profile)
        outbound["tag"] = "proxy" if index == len(profiles) - 1 else f"chain-{index + 1}"
        built.append(outbound)
    return built


def apply(cfg: dict, plan: ResolvedChain, core_cfg: dict | None = None) -> None:
    built = build(plan, core_cfg)
    existing = cfg.get("outbounds", [])
    tags = {o.get("tag") for o in existing}
    for outbound in built[:-1]:
        if outbound["tag"] in tags:
            raise ValueError(tr("The template already uses chain outbound tag {tag}.",
                                tag=outbound["tag"]))
    if "proxy" not in tags:
        raise ValueError(tr("The template has no proxy outbound for the chain."))
    # Xray uses the first outbound when no route matches. Retain proxy's
    # original position rather than making the entry the default exit.
    cfg["outbounds"] = [item for o in existing for item in
                        ([built[-1], *built[:-1]] if o.get("tag") == "proxy" else [o])]
