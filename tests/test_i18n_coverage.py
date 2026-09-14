"""i18n coverage: every literal tr() call in ui/*.py has a Persian entry
with matching placeholders, and no fa key sits there unused.

Some tr() call sites pass a variable, not a literal (a value+template
pair from core.dns, one of core.autostart.is_supported()'s reasons,
one of core.connection's on_step strings, one of core.alerts.Alert's
templates) -- the AST scan below can never "see" those as used, so
each such key is verified against its actual small, fixed source
instead, and allow-listed for the unused-key check.
"""
from __future__ import annotations

import ast
import string
from pathlib import Path

from xrayui import i18n_fa
from xrayui.core import alerts as alerts_mod
from xrayui.core import dns as dns_mod
from xrayui.core.subscription import Subscription, Usage

UI_DIR = Path(__file__).resolve().parent.parent / "xrayui" / "ui"


def _placeholder_names(template: str) -> set[str]:
    names = set()
    for _, field_name, _, _ in string.Formatter().parse(template):
        if field_name:
            names.add(field_name)
    return names


def _tr_literal_calls() -> list[tuple[str, set[str], str, int]]:
    """(text, keyword-arg names, filename, lineno) for every tr("literal", ...)
    call across xrayui/ui/*.py."""
    found = []
    for path in sorted(UI_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "tr" and node.args):
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                params = {kw.arg for kw in node.keywords if kw.arg}
                found.append((first.value, params, path.name, node.lineno))
    return found


_LITERAL_CALLS = _tr_literal_calls()

# core.dns's server_reason()/domestic_reason()/raw_override_issue_reasons()
# all return (value, template) pairs from this same fixed set of templates
# (see core/dns.py) -- ui/dns_dialog.py._save() calls tr(template, value=...).
_DNS_REASON_KEYS = {
    dns_mod.REASON_SPACES,
    dns_mod.REASON_NO_HOST,
    dns_mod.REASON_PORT_SCHEME,
    dns_mod.REASON_UNRECOGNIZED,
    dns_mod.REASON_INVALID_PORT,
    dns_mod.REASON_USE_RESOLVER_IP,
    *dns_mod._REASON_REFUSED.values(),
}

# core.autostart.is_supported()'s exact reason strings (core/autostart.py),
# reached via ui/dialogs.py's tr(autostart_reason).
_AUTOSTART_REASON_KEYS = {
    "Not supported on macOS yet.",
    "Install the .deb package to start sushTun at login.",
    "Can't tell which user to start sushTun for.",
}

# core.connection's on_step callback (core/connection.py's self._log(...)
# calls) emits these as fixed, non-interpolated strings -- reached via
# ui/main_window.py._on_step()'s tr(msg). Every *other* on_step message
# embeds live data (an interface name, an exception) and is intentionally
# left out: tr() falls back to English for those, exactly as designed.
_ON_STEP_KEYS = {
    "Experimental platform (Linux) — network backend is unverified.",
    "Detecting active interface...",
    "Backing up DNS...",
    "Building runtime config...",
    "Starting Xray...",
    "Waiting for TUN adapter...",
    "Configuring tunnel adapter...",
    "Routing DNS and traffic through the tunnel...",
    "WARNING: DNS could not be routed through the tunnel — "
    "lookups will leave unencrypted via the local network.",
    "Connected.",
    "Starting Windows hotspot...",
    "Starting Wi-Fi hotspot...",
    "Gateway mode on — hotspot clients now use the tunnel.",
    "Building runtime config (macOS: SOCKS + tun2socks bridge)...",
    "Starting tun2socks bridge...",
    "Previous session left DNS pointing at 127.0.0.1. Restoring...",
    "Disconnecting...",
    "Network restored.",
    "Tunnel DNS was cleared by another program — restored.",
    "WARNING: tunnel DNS was cleared by another program and could not "
    "be restored — lookups are leaving outside the tunnel.",
}


def _alert_template_keys() -> set[str]:
    """core.alerts.Alert.template values, derived by actually triggering
    every branch of evaluate() rather than hand-copied."""
    cfg = {"data_percent": 10, "data_gb": 1.0, "expiry_days": 3}
    templates = set()
    critical_data = Usage(download=999, total=1000)  # ~0.1% left
    for a in alerts_mod.evaluate(Subscription(usage=critical_data), cfg):
        templates.add(a.template)
    warning_data = Usage(download=91 * 10**9, total=100 * 10**9)  # 9% left
    for a in alerts_mod.evaluate(Subscription(usage=warning_data), cfg):
        templates.add(a.template)
    import time
    critical_exp = Usage(expire=int(time.time() + 12 * 3600))
    for a in alerts_mod.evaluate(Subscription(usage=critical_exp), cfg):
        templates.add(a.template)
    warning_exp = Usage(expire=int(time.time() + 2 * 86400))
    for a in alerts_mod.evaluate(Subscription(usage=warning_exp), cfg):
        templates.add(a.template)
    return templates


# server_table.COLUMNS / routing_dialog._RULE_COLS are module-level lists
# indexed dynamically (tr(COLUMNS[section]) in headerData()), not literal
# tr() calls -- the AST scan can't see these column headers used either.
_COLUMN_HEADER_KEYS = {"Delay", "Transport", "Subscription", "Type", "Match"}

_DYNAMIC_KEYS = (_DNS_REASON_KEYS | _AUTOSTART_REASON_KEYS | _ON_STEP_KEYS
                | _alert_template_keys() | _COLUMN_HEADER_KEYS)


def test_every_tr_literal_has_a_persian_translation():
    missing = [f"{fname}:{lineno}: {text!r}" for text, _params, fname, lineno in _LITERAL_CALLS
              if text and text not in i18n_fa.TRANSLATIONS_FA]
    assert not missing, "Missing fa translations:\n" + "\n".join(missing)


def test_tr_literal_placeholders_match_between_english_and_persian():
    mismatches = []
    for text, _params, fname, lineno in _LITERAL_CALLS:
        fa = i18n_fa.TRANSLATIONS_FA.get(text)
        if fa is None:
            continue  # reported by test_every_tr_literal_has_a_persian_translation
        en_fields = _placeholder_names(text)
        fa_fields = _placeholder_names(fa)
        if en_fields != fa_fields:
            mismatches.append(f"{fname}:{lineno}: {text!r} en={en_fields} fa={fa_fields}")
    assert not mismatches, "Placeholder mismatches:\n" + "\n".join(mismatches)


def test_no_unused_fa_keys():
    literal_texts = {text for text, *_ in _LITERAL_CALLS}
    unused = set(i18n_fa.TRANSLATIONS_FA) - literal_texts - _DYNAMIC_KEYS
    assert not unused, f"Unused fa keys: {sorted(unused)}"


def test_dynamic_key_allowlists_are_still_accurate():
    """Each dynamic-key set above must actually be a subset of the real fa
    dict -- catches a stale allowlist entry that drifted from the code."""
    for name, keys in (("dns reasons", _DNS_REASON_KEYS),
                       ("autostart reasons", _AUTOSTART_REASON_KEYS),
                       ("on_step strings", _ON_STEP_KEYS),
                       ("alert templates", _alert_template_keys())):
        missing = keys - set(i18n_fa.TRANSLATIONS_FA)
        assert not missing, f"{name}: missing fa entries for {missing}"


def test_column_header_allowlist_matches_the_real_column_lists():
    from xrayui.ui import routing_dialog, server_table
    columns = set(server_table.COLUMNS) | set(routing_dialog._RULE_COLS)
    columns.discard("")
    assert columns <= set(i18n_fa.TRANSLATIONS_FA)
    # And the allowlist itself names only real, still-current column labels.
    assert _COLUMN_HEADER_KEYS <= columns
