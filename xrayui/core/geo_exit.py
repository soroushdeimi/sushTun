"""Where a server's traffic leaves from, as websites see it.

The country of a server's address is not the country of its exit: a relay in
one place can hand traffic to an exit in another. Cloudflare's trace endpoint
reports the country and IP of whoever is asking, so asking through a proxy (or
through the tunnel itself) tells what the destination sees.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .. import paths

TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
_MAX_BODY = 4096


@dataclass(frozen=True)
class ExitInfo:
    country: str
    ip: str


def flags_dir() -> Path:
    return paths.flags_dir()


@lru_cache(maxsize=1)
def _names() -> dict:
    try:
        data = json.loads((flags_dir() / "names.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def normalize(code: str | None) -> str | None:
    """A lowercase two-letter code that has a flag, else None."""
    code = (code or "").strip().lower()
    if len(code) == 2 and code.isalpha() and code in _names():
        return code
    return None


def flag_path(code: str | None) -> Path | None:
    code = normalize(code)
    return flags_dir() / f"{code}.svg" if code else None


def country_name(code: str | None, lang: str = "en") -> str:
    code = normalize(code)
    if not code:
        return ""
    entry = _names().get(code, {})
    return entry.get(lang) or entry.get("en") or code.upper()


def parse_trace(text: str) -> ExitInfo | None:
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
    country = normalize(fields.get("loc"))
    if not country:
        return None
    return ExitInfo(country, fields.get("ip", ""))


def detect(proxy=None, timeout: float = 8.0) -> ExitInfo | None:
    """The exit country and IP seen through `proxy`, or None on any failure.

    `proxy` is an opener (anything with .open), an HTTP proxy URL, or None for
    a direct request: once connected the system route already is the tunnel.
    """
    try:
        if hasattr(proxy, "open"):
            opener = proxy
        elif proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        else:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(TRACE_URL, timeout=timeout) as resp:
            body = resp.read(_MAX_BODY)
        return parse_trace(body.decode("utf-8", errors="replace"))
    except Exception:
        return None
