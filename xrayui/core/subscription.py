"""Subscriptions: fetch a sub URL, parse quota/expiry, and refresh profiles."""
from __future__ import annotations

import functools
import json
import re
import time
import urllib.parse
import uuid
from dataclasses import asdict, dataclass, field

from .. import paths
from . import importer
from .profiles import SUBSCRIPTIONS_FILENAME, Profile, ProfileStore

DEFAULT_USER_AGENT = "v2rayNG/1.8.5"
MAX_BODY_BYTES = 16 * 1024 * 1024

_HTTP_SCHEMES = ("http", "https")


def _require_http_url(url: str) -> None:
    """Reject anything but an http(s) URL with a host, before any fetch.

    subscriptions.json is hand-edited and restored from backups, and this
    code runs as root: without this check a file:// URL hands urlopen a
    local path to read (ftp:// and friends are just as unwanted).
    """
    parts = urllib.parse.urlsplit((url or "").strip())
    if parts.scheme.lower() not in _HTTP_SCHEMES or not parts.hostname:
        raise ValueError("subscription URL must start with http:// or https://")


def _redirect_handler_class():
    """The http-only redirect handler class, defined on first use.

    It must subclass urllib.request.HTTPRedirectHandler, so defining it at
    module top would import urllib.request (ssl/http, ~7 MB) on every
    startup -- and this module loads at launch for SubscriptionStore.
    """
    import urllib.request

    class _HttpOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
        """Refuse redirects that hop to another scheme (https -> file://).

        A panel that answers a subscription fetch with "Location: file://…"
        must not make this root process read local files, so the hop is
        refused before anything is read from the new URL. build_opener()
        drops its default HTTPRedirectHandler when given one of its
        subclasses, so an opener built with this class has exactly this
        handler in charge of every redirect.
        """

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            scheme = urllib.parse.urlsplit(newurl).scheme.lower()
            if scheme and scheme not in _HTTP_SCHEMES:
                raise ValueError(
                    f"refusing to follow a redirect to a non-http(s) URL: {scheme}://…")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return _HttpOnlyRedirectHandler


def __getattr__(name: str):
    # Lazily re-exported (see above): the hardening tests instantiate
    # subscription._HttpOnlyRedirectHandler directly.
    if name == "_HttpOnlyRedirectHandler":
        return _redirect_handler_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


@functools.cache
def _opener():
    """The process-wide urlopen opener, installed on the first network use.

    Same protection main installed at import (only http(s) redirects are
    followed), but building it here -- instead of at module top -- keeps
    urllib.request/ssl out of every startup that never fetches. Cached, so
    the opener is built and installed exactly once.
    """
    import urllib.request

    from . import tls

    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=tls.https_context()), _redirect_handler_class())
    urllib.request.install_opener(opener)
    return opener


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
    # New fields below: all have a default that reproduces today's behavior
    # exactly, so an old subscriptions.json loads unchanged.
    enabled: bool = True
    auto_update_hours: int = 0  # 0 = use the global alerts.auto_refresh_hours
    name_filter: str = ""  # regex; "" = keep every parsed server
    user_agent: str = ""  # "" = DEFAULT_USER_AGENT

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Subscription:
        # Every field below can arrive with a hostile type from a
        # hand-edited or restored subscriptions.json; coerce each to its
        # declared type (wrong type -> the default the UI would write) so
        # a stored entry can never raise in is_due() or elsewhere.
        raw_usage = data.get("usage")
        raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
        usage = Usage(**{k: _coerce_usage_number(v) for k, v in raw_usage.items()
                         if k in Usage.__dataclass_fields__})
        raw_uids = data.get("profile_uids", [])
        # A bare string is not a uid list (list("abc") would be ["a", …]).
        profile_uids = ([u for u in raw_uids if isinstance(u, str)]
                        if isinstance(raw_uids, (list, tuple)) else [])
        uid = data.get("uid", uuid.uuid4().hex)
        uid = uid if isinstance(uid, str) and uid else uuid.uuid4().hex
        enabled = data.get("enabled", True)
        enabled = enabled if isinstance(enabled, bool) else True
        return cls(
            url=_coerce_str(data.get("url", ""), ""),
            name=_coerce_str(data.get("name", "Subscription"), "Subscription"),
            usage=usage,
            updated=_coerce_updated(data.get("updated", 0.0)),
            profile_uids=profile_uids,
            uid=uid,
            enabled=enabled,
            auto_update_hours=_coerce_hours(data.get("auto_update_hours", 0)),
            name_filter=_coerce_str(data.get("name_filter", ""), ""),
            user_agent=_coerce_str(data.get("user_agent", ""), ""),
        )


def _coerce_str(value, default: str) -> str:
    return value if isinstance(value, str) else default


def _coerce_hours(value) -> int:
    # The UI only ever writes an int 0-168; anything else came from a
    # hand-edited or restored file. Wrong type means off (0), and anything
    # out of range clamps to what the spinbox allows, so is_due() can
    # never raise on a stored entry.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, min(int(value), 168))


def _coerce_updated(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _coerce_usage_number(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


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


def subscription_url(text: str) -> str:
    """The single http(s) URL `text` is, or "" when it is anything else.

    The Import dialog's first tab is called "Link / Subscription", but it only
    ever parsed share links, so a subscription URL pasted there matched no
    scheme and came back as "No valid profiles found". A URL is recognised
    here instead and kept as a subscription, which is what the user wants
    from a subscription link anyway: one that keeps updating.
    """
    value = text.lstrip("\ufeff").strip()
    if not value or any(c.isspace() for c in value):
        return ""  # several lines, or a link with a comment after it
    if importer.is_proxy_url(value):
        return ""
    return value if value.lower().startswith(("http://", "https://")) else ""


def fetch(url: str, timeout: float = 20.0, user_agent: str = ""):
    # Local import: urllib.request drags in ssl/http/email (~7 MB), and this
    # module is imported at startup for SubscriptionStore, long before any
    # fetch ever runs.
    import urllib.request

    _require_http_url(url)  # a file:// URL must fail here, never in urlopen
    _opener()  # install the http-only redirect guard before the first fetch
    req = urllib.request.Request(url, headers={"User-Agent": user_agent or DEFAULT_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (user-provided sub URL)
        info = resp.headers.get("Subscription-Userinfo", "")
        raw = resp.read(MAX_BODY_BYTES + 1)
        if len(raw) > MAX_BODY_BYTES:
            raise ValueError("subscription body is too large")
        body = raw.decode("utf-8", errors="replace")
    return parse_userinfo(info), importer.parse_subscription(body)


class SubscriptionStore:
    def __init__(self) -> None:
        self.file = paths.profiles_dir() / SUBSCRIPTIONS_FILENAME

    def list(self) -> list[Subscription]:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        if not isinstance(data, list):
            return []  # hand-edited or corrupt: start with no subscriptions
        subs = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                subs.append(Subscription.from_dict(item))
            except (TypeError, ValueError, AttributeError):
                continue  # one broken entry must not hide the others
        return subs

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


def _profile_key(p: Profile) -> tuple:
    return ((p.protocol or "").lower(), p.address, p.port, p.id)


def _name_filter_pattern(name_filter: str) -> re.Pattern | None:
    """A compiled case-insensitive matcher, or None for "no filter" and for
    an invalid regex alike -- a typo in the filter must fetch everything
    rather than silently wipe every server on the next refresh."""
    if not name_filter:
        return None
    try:
        return re.compile(name_filter, re.IGNORECASE)
    except re.error:
        return None


def refresh(sub: Subscription, profiles: ProfileStore, store: SubscriptionStore) -> Subscription:
    _require_http_url(sub.url)  # fail before touching anything, not halfway through
    usage, parsed = fetch(sub.url, user_agent=sub.user_agent)
    # parse_subscription already drops an unparseable line; this also drops
    # a link that parsed but can never connect (no address/credential), the
    # same check import.parse_share_text/parse_json/parse_qr apply.
    parsed = [p for p in parsed if p.is_valid()]

    pattern = _name_filter_pattern(sub.name_filter)
    if pattern is not None:
        filtered = [p for p in parsed if pattern.search(p.name or "")]
        if not filtered:
            # Distinct message from the empty-parse case below, but the
            # same "refuse rather than wipe" handling: a filter that (for
            # now) matches nothing is far more likely a typo or a
            # temporarily empty subscription than "delete every server".
            raise ValueError("name filter matched no servers")
        parsed = filtered

    if not parsed:
        # A panel error page, an empty body, or a sub with every server
        # temporarily removed all parse to zero profiles. Refuse rather than
        # wiping every existing server (and the active one with them) for
        # what is usually a transient fetch problem.
        raise ValueError("subscription returned no servers")

    # Match new servers back to old ones by identity, not position, so a
    # server that reappears keeps its uid (and stays the active profile,
    # since active.txt just points at a uid).
    old_by_key: dict[tuple, list[Profile]] = {}
    for uid in sub.profile_uids:
        old = profiles.get(uid)
        if old:
            old_by_key.setdefault(_profile_key(old), []).append(old)

    new_uids: list[str] = []
    reused_uids: set[str] = set()
    for p in parsed:
        p.sub_uid = sub.uid
        candidates = old_by_key.get(_profile_key(p), [])
        if candidates:
            index = next((i for i, old in enumerate(candidates) if old.name == p.name), 0)
            p.uid = candidates.pop(index).uid
            reused_uids.add(p.uid)
        profiles.save(p)
        new_uids.append(p.uid)

    # Only drop servers that actually disappeared from the subscription.
    for uid in sub.profile_uids:
        if uid not in reused_uids:
            profiles.delete(uid)

    sub.profile_uids = new_uids
    sub.usage = usage
    sub.updated = time.time()
    store.save(sub)
    return sub


def is_due(sub: Subscription, global_hours: float, now: float) -> bool:
    """Whether `sub` should auto-refresh right now. A disabled sub is never
    due. The sub's own interval wins over the global one when set; 0
    (either one) means "off", matching the geo auto-update convention
    elsewhere in this app -- never updated (updated == 0) is always due
    once the effective interval is non-zero.
    """
    if not sub.enabled:
        return False
    hours = sub.auto_update_hours or global_hours
    if not hours:
        return False
    return sub.updated < now - hours * 3600
