"""Check GitHub releases for a newer sushTun version."""
from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable

from .. import __version__

_API_URL = "https://api.github.com/repos/soroushdeimi/sushTun/releases/latest"
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _default_fetch() -> dict:
    req = urllib.request.Request(
        _API_URL, headers={"User-Agent": f"sushTun/{__version__}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (GitHub's own API)
        return json.loads(resp.read().decode("utf-8"))


def latest_release(fetch: Callable[[], dict] | None = None) -> tuple[str, str] | None:
    """(tag, html_url) for the latest GitHub release, or None on any
    failure at all -- a flaky network, a GitHub outage, or a malformed
    response must never raise; a background update check is not
    something that should ever surface as an error to the user."""
    fetch = fetch or _default_fetch
    try:
        data = fetch()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    tag = data.get("tag_name")
    url = data.get("html_url")
    if not isinstance(tag, str) or not tag or not isinstance(url, str) or not url:
        return None
    return tag, url


def is_newer(tag: str, current: str) -> bool:
    """True when `tag` (e.g. "v0.2.0") is a numeric release newer than
    `current` (e.g. "0.1.13"). A non-numeric or pre-release tag (a draft,
    "-rc1", "-beta") is never treated as newer, so it never nags a user
    who is already caught up.
    """
    tag_m = _VERSION_RE.match(tag.strip())
    cur_m = _VERSION_RE.match(current.strip())
    if not tag_m or not cur_m:
        return False
    return tuple(map(int, tag_m.groups())) > tuple(map(int, cur_m.groups()))
