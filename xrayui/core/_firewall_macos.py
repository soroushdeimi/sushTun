"""macOS firewall backend: a dedicated pf anchor, added to the main ruleset
additively and reversibly.

The anchor's rules are only evaluated once the main ruleset reaches an
`anchor "sushtun"` line, so install adds exactly that one line and remove
strips it. The main ruleset is never written to disk: it is reloaded from a
temp file, so /etc/pf.conf itself is never modified and a crash mid-write
cannot corrupt it.

Reload base and safety (a pf bug can brick the internet):
- The reload base is /etc/pf.conf -- the canonical main ruleset pf loads at
  boot, complete and always re-loadable (a live `pfctl -sr` dump is lossy: no
  `set` options, no `load anchor from` lines, so it must not be the base).
- Before any change we refuse if the live ruleset references an anchor that
  /etc/pf.conf does not: `pfctl -f` would replace the live ruleset with the
  file's content and destroy that anchor (another app's firewall/VPN), which
  we cannot recover.
- The original /etc/pf.conf is backed up to a root-only state file BEFORE any
  change, so recover_stale / the boot task can undo it after a crash.
- The anchor reference is added while the anchor is still empty, and the
  allow+block rules are loaded into the anchor in one step, so there is never
  a moment with a block rule and no allow rules.
- install verifies the anchor reference and the rules are actually live before
  reporting success; any failure rolls back to the saved original.
- pf is enabled with a token and the token is released on remove, which
  restores the prior enabled/disabled state exactly (the enable count is
  reference-counted, so an already-enabled pf stays enabled).
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from .. import paths
from . import proc
from ._firewall_common import (
    DHCP_V4,
    DHCP_V6,
    LAN_V4,
    LAN_V6,
    FirewallError,
    clear_state,
    load_state,
    save_state,
    split_ips,
)

ANCHOR = "sushtun"
_PFCONF = Path("/etc/pf.conf")
# The one line we add to the main ruleset. A filter anchor, placed before
# Apple's filter anchor so our quick rules are evaluated first (a strict
# allowlist must decide before any other rule can quick-match).
_ANCHOR_LINE = f'anchor "{ANCHOR}"'
# Apple's filter anchor, which our line is inserted before.
_APPLE_ANCHOR = re.compile(r'^\s*anchor\s+"com\.apple')


def supported() -> bool:
    return shutil.which("pfctl") is not None


def build_ruleset(tun_alias: str, server_ips, allow_lan: bool) -> str:
    """The pf ruleset loaded into the anchor.

    Allow rules come before the final block, so the anchor is never
    block-only. Outbound only: inbound is never filtered, so a misrule cannot
    cut the user's downloads.
    """
    v4, v6 = split_ips(server_ips)
    lines = [f"pass out quick on {tun_alias}"]
    for ip in v4:
        lines.append(f"pass out quick inet from any to {ip}")
    for ip in v6:
        lines.append(f"pass out quick inet6 from any to {ip}")
    lines.append("pass out quick on lo0")
    if allow_lan:
        lines.append(f"pass out quick inet proto udp from any port {DHCP_V4[0]} "
                     f"to any port {DHCP_V4[1]}")
        lines.append(f"pass out quick inet6 proto udp from any port {DHCP_V6[0]} "
                     f"to any port {DHCP_V6[1]}")
        for net in LAN_V4:
            lines.append(f"pass out quick inet from any to {net}")
        for net in LAN_V6:
            lines.append(f"pass out quick inet6 from any to {net}")
    lines.append("block out quick")
    return "\n".join(lines) + "\n"


def _insert_anchor_line(main_ruleset: str) -> str:
    """Return the main ruleset with our anchor line added before Apple's
    filter anchor. Raises if no safe insertion point is found: a misplaced
    anchor would either weaken the lockdown or break other rules, and we must
    never claim protection that is not actually in force."""
    lines = main_ruleset.splitlines()
    for i, line in enumerate(lines):
        if _APPLE_ANCHOR.match(line):
            lines.insert(i, _ANCHOR_LINE)
            return "\n".join(lines) + "\n"
    raise FirewallError(
        "could not find Apple's pf anchor to place the sushtun anchor before; "
        "refusing to modify the main ruleset")


def _write_temp(content: str) -> Path:
    d = paths.state_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="fw-", suffix=".rules", dir=str(d))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return Path(name)


def _pf(args: list[str]):
    return proc.run(["pfctl", *args])


def _main_ruleset_has_anchor() -> bool:
    r = _pf(["-sr"])
    return r.returncode == 0 and _ANCHOR_LINE in r.stdout


def _anchor_has_rules() -> bool:
    r = _pf(["-a", ANCHOR, "-sr"])
    return r.returncode == 0 and "block out quick" in r.stdout


def _anchor_names(ruleset_text: str) -> set[str]:
    """Every anchor reference in a ruleset, e.g. 'com.apple/*' or 'sushtun'."""
    names: set[str] = set()
    for line in ruleset_text.splitlines():
        m = re.match(r'^(?:scrub|nat|rdr|binat|dummynet)?-?anchor\s+"([^"]+)"',
                     line.strip())
        if m:
            names.add(m.group(1))
    return names


def _live_anchors_unsafe(original: str) -> bool:
    """True if the live main ruleset has an anchor that /etc/pf.conf lacks.

    `pfctl -f` replaces the live ruleset with the file's content, so an anchor
    another app added at runtime (absent from the file) would be destroyed and
    unrecoverable. Refuse rather than risk it.
    """
    r = _pf(["-sr"])
    if r.returncode != 0:
        return True  # cannot inspect: treat as unsafe
    live = _anchor_names(r.stdout)
    in_file = _anchor_names(original)
    return bool(live - in_file - {ANCHOR})


def _read_main_ruleset() -> str:
    if not _PFCONF.is_file():
        raise FirewallError(f"{_PFCONF} not found; refusing to modify the pf ruleset")
    return _PFCONF.read_text(encoding="utf-8")


def install(tun_alias: str, server_ips, allow_lan: bool) -> None:
    if not supported():
        raise FirewallError("pfctl not found")
    # A previous install that crashed may have left the anchor and a dangling
    # pf enable token; clear them so we always start from the clean ruleset.
    remove()
    try:
        original = _read_main_ruleset()
    except OSError as exc:
        raise FirewallError(f"could not read {_PFCONF}: {exc}") from exc

    # Back up the original BEFORE any change, so a crash still leaves a way out.
    save_state({"kind": "macos", "original": original, "token": "", "ruleset": ""})
    try:
        _install_steps(tun_alias, server_ips, allow_lan, original)
    except FirewallError:
        # Roll back whatever was installed so a failed install never leaves a
        # half-locked-down machine; the caller logs a WARNING and continues.
        remove()
        raise


def _install_steps(tun_alias: str, server_ips, allow_lan: bool, original: str) -> None:
    combined = _insert_anchor_line(original)
    check = _write_temp(combined)
    try:
        if _pf(["-nf", str(check)]).returncode != 0:
            raise FirewallError("the combined pf ruleset failed validation")
        if _live_anchors_unsafe(original):
            raise FirewallError(
                "the live pf ruleset has anchors this app cannot round-trip; "
                "refusing to modify it")
        if _pf(["-f", str(check)]).returncode != 0:
            raise FirewallError("could not load the main pf ruleset")
    finally:
        check.unlink(missing_ok=True)

    ruleset = build_ruleset(tun_alias, server_ips, allow_lan)
    rules_file = _write_temp(ruleset)
    try:
        if _pf(["-a", ANCHOR, "-f", str(rules_file)]).returncode != 0:
            raise FirewallError("could not load the sushtun anchor rules")
    finally:
        rules_file.unlink(missing_ok=True)

    # Enable pf with a token; releasing it on remove restores the prior state.
    en = _pf(["-E"])
    token = _extract_token(en.stdout)
    if en.returncode != 0 or not token:
        raise FirewallError("could not enable pf")
    save_state({"kind": "macos", "original": original, "token": token,
                "ruleset": ruleset})

    # Verify it is actually live before claiming success.
    if not _main_ruleset_has_anchor() or not _anchor_has_rules():
        raise FirewallError("pf firewall installed but could not be verified live")


def _extract_token(out: str) -> str:
    m = re.search(r"\b(\d{6,})\b", out)
    return m.group(1) if m else ""


def remove() -> list[str]:
    """Idempotent. Returns a list of warning strings (empty when clean)."""
    warnings: list[str] = []
    state = load_state()
    if state is None or state.get("kind") != "macos":
        # Nothing we installed is recorded; a stray anchor we cannot account
        # for is left in place (removing it blindly could drop another app's
        # rules) and reported.
        if _main_ruleset_has_anchor():
            warnings.append("found a sushtun pf anchor with no saved state; "
                            "left it in place")
        return warnings

    original = state.get("original") or ""
    token = state.get("token") or ""

    # Restore the main ruleset only if our anchor reference is still present.
    if _main_ruleset_has_anchor():
        if not original:
            warnings.append("sushtun pf anchor present but no saved original; "
                            "could not restore the main ruleset")
        else:
            restore = _write_temp(original)
            try:
                if _pf(["-f", str(restore)]).returncode != 0:
                    warnings.append("could not restore the main pf ruleset")
            finally:
                restore.unlink(missing_ok=True)

    # Drop the anchor rules so a leftover cannot filter anything.
    _pf(["-a", ANCHOR, "-F"])  # flush the anchor (no-op if empty)

    if token:
        if _pf(["-X", token]).returncode != 0:
            warnings.append("could not release the pf enable token")

    clear_state()
    return warnings


def is_active() -> bool:
    if not supported():
        return False
    return _main_ruleset_has_anchor() and _anchor_has_rules()
