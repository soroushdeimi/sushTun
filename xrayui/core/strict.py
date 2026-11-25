"""Strict mode: keep the user's real IP away from AI accounts.

Xray routing deliberately sends some traffic with the real IP (Iran/Russia/
China direct, private, the user's own bypass domains, low-usage, custom
rules). If an AI domain falls under one of those, it leaks silently while the
tunnel looks healthy. Strict mode adds a "protected domains" rule that is
placed ahead of every other routing rule and sends those names to the proxy,
plus an optional no-direct mode that drops every direct rule entirely.

Everything here is a pure function over the settings sub-dict so the UI can
call it without touching a live connection. Core stays English; the UI worker
translates the returned strings later.
"""
from __future__ import annotations

import logging
import re

from . import serverless

logger = logging.getLogger(__name__)

# The curated AI services the real IP must never reach. Kept in one constant
# so a new service is a one-line change. These are trusted (not user input),
# so they bypass sanitize_domains.
DEFAULT_AI_DOMAINS: list[str] = [
    "openai.com",
    "chatgpt.com",
    "oaistatic.com",
    "oaiusercontent.com",
    "anthropic.com",
    "claude.ai",
    "claude.com",
    "gemini.google.com",
    "aistudio.google.com",
    "generativelanguage.googleapis.com",
    "bard.google.com",
    "perplexity.ai",
    "x.ai",
    "grok.com",
    "mistral.ai",
    "cohere.com",
    "huggingface.co",
    "copilot.microsoft.com",
    "deepseek.com",
    "poe.com",
    "midjourney.com",
    "replicate.com",
    "openrouter.ai",
    "together.ai",
    "groq.com",
    "character.ai",
]

# A hand-edited settings.json can hold an absurd list; cap it so one bad file
# cannot bloat the rendered config or the DNS server's domain list.
MAX_DOMAINS = 1000

# A plain domain: dot-separated labels of [a-z0-9-], no leading/trailing hyphen
# per label, at least one dot (we protect real names, not single labels).
_DOMAIN_RE = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$"
)

# UI-facing strings. Core stays English; the UI worker translates later.
NO_DIRECT_WARNING = (
    "No-direct mode routes every site through the tunnel, including Iranian "
    "sites. Iranian sites will be slower and some may be blocked."
)
PROBLEM_SERVERLESS_ONLY = (
    "Strict mode is incompatible with serverless-only mode: that mode sends "
    "every site directly, so protected domains would still use the real IP."
)
# Mode names (as strings) that mean "everything goes direct".
_INCOMPATIBLE_MODES = {"serverless-only", "serverless_only", "serverless only", "only"}


def _cfg(cfg) -> dict:
    return cfg if isinstance(cfg, dict) else {}


def _valid_domain(d: str) -> bool:
    if not d or len(d) > 253:
        return False
    if any(c.isspace() for c in d):
        return False
    if not d.isascii():
        return False
    if "." not in d:
        return False
    return bool(_DOMAIN_RE.match(d))


def sanitize_domains(entries) -> list[str]:
    """Normalise the user's protected-domain list.

    Uppercase and a leading wildcard ("*.x.com") are normalised; empty,
    whitespace, non-ASCII, structurally invalid, and duplicate entries are
    dropped with a WARNING. Never raises: a hand-edited settings.json must
    degrade, not stop the connect.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in entries or []:
        if not isinstance(raw, str):
            logger.warning("strict: dropping non-string domain entry %r", raw)
            continue
        d = raw.strip().lower().lstrip("*.").strip().rstrip(".")
        if not d:
            continue
        if not _valid_domain(d):
            logger.warning("strict: dropping invalid protected domain %r", raw)
            continue
        if d in seen:
            continue
        seen.add(d)
        out.append(d)
        if len(out) >= MAX_DOMAINS:
            logger.warning(
                "strict: protected-domain list exceeds %d entries; ignoring the rest",
                MAX_DOMAINS,
            )
            break
    return out


def protected_domains(cfg) -> list[str]:
    """The protected names: the curated AI list (when ai_protect) plus the
    user's own domains, de-duplicated, AI list first."""
    c = _cfg(cfg)
    out: list[str] = []
    seen: set[str] = set()
    if c.get("ai_protect", True):
        for d in DEFAULT_AI_DOMAINS:
            if d not in seen:
                seen.add(d)
                out.append(d)
    for d in sanitize_domains(c.get("domains")):
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def is_active(cfg) -> bool:
    """True when the protected-domains rule will actually be rendered."""
    c = _cfg(cfg)
    return c.get("enabled") is True and bool(protected_domains(c))


def no_direct(cfg) -> bool:
    """True when every direct rule must be dropped (stronger mode)."""
    c = _cfg(cfg)
    return c.get("enabled") is True and c.get("no_direct") is True


def build_rule(cfg) -> dict | None:
    """The protected-domains routing rule, or None when strict is not active.

    Uses the `domain:` prefix so each name matches itself and its subdomains
    (suffix matching). outboundTag is "proxy" so the names go through the
    tunnel, never the real IP.
    """
    if not is_active(cfg):
        return None
    return {
        "type": "field",
        "domain": [f"domain:{d}" for d in protected_domains(cfg)],
        "outboundTag": "proxy",
    }


def strip_direct(rules) -> list[dict]:
    """Every rule except those that send traffic with the real IP.

    Used by no-direct mode. DNS infrastructure rules (dns-out, the proxy's own
    hostname pin) are not "direct" outbound rules, so they survive -- matching
    "everything goes proxy except DNS/own-server pins".
    """
    return [r for r in (rules or []) if r.get("outboundTag") != "direct"]


def _overlaps_protected(bare: str, protected: set[str]) -> bool:
    bare = bare.lower().strip(".")
    for p in protected:
        if bare == p or bare.endswith("." + p) or p.endswith("." + bare):
            return True
    return False


def filter_direct_domains(direct_domains, protected) -> list[str]:
    """Remove any direct-domain matcher that names a protected domain.

    The domestic (Iranian) DNS server is given the direct domains in its
    `domains` list, so it would resolve a protected name via the local
    resolver -- a leak and a poisoning risk. Dropping the matcher here makes
    the name fall through to the tunnel DNS instead. Only `domain:`/`full:`
    matchers name a specific host; geo categories are left alone.
    """
    prot = set(protected or [])
    if not prot:
        return list(direct_domains or [])
    out: list[str] = []
    for d in direct_domains or []:
        if isinstance(d, str):
            prefix, sep, rest = d.partition(":")
            if sep and prefix in ("domain", "full") and _overlaps_protected(rest, prot):
                logger.warning(
                    "strict: keeping %s out of the domestic DNS resolver (protected)", d
                )
                continue
        out.append(d)
    return out


def problem(profile_or_mode) -> str | None:
    """A message when strict mode cannot protect the connection, else None.

    Serverless-only mode makes the "proxy" outbound a fragmenting *direct*
    outbound, so routing protected domains to "proxy" would still use the real
    IP. That must be reported, not silently ignored. Accepts a Profile or a
    mode string.
    """
    if profile_or_mode is None:
        return None
    if isinstance(profile_or_mode, str):
        incompatible = profile_or_mode.strip().lower() in _INCOMPATIBLE_MODES
    else:
        incompatible = serverless.is_only(profile_or_mode)
    return PROBLEM_SERVERLESS_ONLY if incompatible else None


def status(cfg) -> str:
    """A short human-readable status line for the UI (English)."""
    c = _cfg(cfg)
    if c.get("enabled") is not True:
        return "Strict mode is off."
    n = len(protected_domains(c))
    if c.get("no_direct") is True:
        return (
            f"Strict mode is on (no-direct): all traffic goes through the "
            f"tunnel; {n} AI domains explicitly protected."
        )
    if n:
        return f"Strict mode is on: {n} AI domains are protected from the real IP."
    return "Strict mode is on but no domains are protected."
