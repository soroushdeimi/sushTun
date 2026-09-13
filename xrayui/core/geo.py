"""Update geoip.dat/geosite.dat from an upstream release.

Validated against the current routing rules before ever being swapped in
live: a source missing a category the current rules reference (e.g.
category-ads-all, or win-spy from the Iran lists) would otherwise make Xray
refuse to start, so the app couldn't connect until someone noticed and
reverted it by hand.
"""
from __future__ import annotations

import http.client
import os
import shutil
import urllib.request
from collections.abc import Callable

from .. import paths
from . import routing as routing_mod
from . import settings as app_settings
from . import xraycheck

# Matches scripts/fetch_deps.py's bundled source (Loyalsoldier), plus the
# Iran-specific alternative offered in settings.
SOURCES: dict[str, str] = {
    "Loyalsoldier":
        "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/{name}",
    "Chocolate4U (Iran)":
        "https://github.com/Chocolate4U/Iran-v2ray-rules/releases/latest/download/{name}",
}

_MIN_SIZE = 100 * 1024  # a truncated download or an HTML error page is nowhere near this
_FILES = ("geoip.dat", "geosite.dat")

# Every geo source ships these, and validating with them forces Xray to
# actually parse both files -- with no baseline, a user with every routing
# toggle off has zero rules, so a truncated/garbage download that's still
# over _MIN_SIZE would otherwise sail through unvalidated.
_BASELINE_RULES = [
    {"type": "field", "domain": ["geosite:private"], "outboundTag": "direct"},
    {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
]

Fetch = Callable[[str], bytes]


class GeoUpdateError(Exception):
    pass


def _default_fetch(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "sushTun"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = resp.read()
            length = resp.headers.get("Content-Length")
    except http.client.IncompleteRead as exc:
        # The connection closed before every promised byte arrived --
        # resp.read() itself raises this rather than returning short.
        raise GeoUpdateError(f"download incomplete: {exc}") from exc
    if length is not None and len(data) != int(length):
        # The full body arrived but doesn't match what the server promised
        # (a lying/broken proxy, say) -- resp.read() alone wouldn't catch this.
        raise GeoUpdateError(f"download incomplete: got {len(data)} bytes, expected {length}")
    return data


def update(source: str, fetch: Fetch | None = None) -> None:
    """Download, validate, then atomically swap in a new geo data source.

    Safe to call while connected: Xray only reads XRAY_LOCATION_ASSET at
    startup, so this takes effect on the next connect. Raises
    GeoUpdateError (with a short reason) and leaves the current files
    untouched on any failure.
    """
    tmpl = SOURCES.get(source)
    if tmpl is None:
        raise GeoUpdateError(f"unknown geo source: {source!r}")
    fetch = fetch or _default_fetch

    base = paths.base_dir()
    new_dir = base / "geo.new"
    shutil.rmtree(new_dir, ignore_errors=True)
    new_dir.mkdir(parents=True, exist_ok=True)

    try:
        for name in _FILES:
            data = fetch(tmpl.format(name=name))
            if len(data) < _MIN_SIZE:
                raise GeoUpdateError(f"{name} download looks truncated ({len(data)} bytes)")
            (new_dir / name).write_bytes(data)

        # The union of every mode's rules, not just the one active right
        # now: switching to a different saved set later must not suddenly
        # hit a category this source never had.
        rules = _BASELINE_RULES + routing_mod.all_possible_rules(app_settings.load()["routing"])
        error = xraycheck.check_rules(rules, asset_dir=new_dir)
        if error:
            raise GeoUpdateError(f"new geo data rejected: {error}")

        _swap(base, new_dir)
    except GeoUpdateError:
        shutil.rmtree(new_dir, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(new_dir, ignore_errors=True)
        raise GeoUpdateError(str(exc)) from exc


def _swap(base, new_dir) -> None:
    current = base / "geo"
    old_dir = base / "geo.old"
    shutil.rmtree(old_dir, ignore_errors=True)
    try:
        if current.exists():
            os.replace(current, old_dir)
        os.replace(new_dir, current)
    except OSError as exc:
        # A Windows file lock (Xray or another process still has a file in
        # geo/ open) can fail the rename partway; restore whatever was
        # there before rather than leave a half-swapped directory.
        if old_dir.exists() and not current.exists():
            os.replace(old_dir, current)
        raise GeoUpdateError(f"could not swap in new geo data: {exc}") from exc
    shutil.rmtree(old_dir, ignore_errors=True)
