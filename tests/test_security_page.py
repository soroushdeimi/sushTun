"""The Security settings page: every control round-trips its real setting,
the firewall group hides on an unsupported platform, the status banner never
claims a protection that is not active, every control carries hover help, and
the Persian keys are complete.

Skipped when PySide6 is missing so a contributor without it still gets a
green suite -- except under CI, where a skip must fail instead.
"""
from __future__ import annotations

import copy
import os
import types

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import i18n_fa  # noqa: E402
from xrayui.core import firewall as firewall_mod  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.i18n import set_language  # noqa: E402
from xrayui.ui import security_page as sp  # noqa: E402
from xrayui.ui.settings_window import SettingsWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def defaults():
    return copy.deepcopy(app_settings.DEFAULTS)


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


def _page(settings):
    win = SettingsWindow(settings)
    return win, win._pages["security"]


def _live_state(**kw) -> types.SimpleNamespace:
    """A stand-in for the live connection state the banner reads."""
    base = dict(killswitch_active=False, ipv6_blocked=False,
                firewall_supported=False, firewall_active=False,
                leakcheck_status="")
    base.update(kw)
    return types.SimpleNamespace(**base)


# -- round-trip: every setting the page owns ---------------------------------

def test_killswitch_round_trips(qapp, defaults):
    win, page = _page(defaults)
    assert page.killswitch.isChecked() is False  # default OFF
    page.killswitch.setChecked(True)
    assert win.values()["killswitch"] == {"enabled": True}
    # Read back from a saved-on setting.
    defaults["killswitch"]["enabled"] = True
    assert _page(defaults)[1].killswitch.isChecked() is True


def test_strict_round_trips(qapp, defaults):
    win, page = _page(defaults)
    assert page.strict_enabled.isChecked() is False
    assert page.strict_ai_protect.isChecked() is True  # default ON
    assert page.strict_no_direct.isChecked() is False
    page.strict_enabled.setChecked(True)
    page.strict_no_direct.setChecked(True)
    page.strict_domains.setPlainText("mybank.example\n  mybank.example  \nbad_domain\n")
    out = win.values()["strict"]
    assert out["enabled"] is True
    assert out["ai_protect"] is True
    assert out["no_direct"] is True
    # sanitize_domains lowercases, trims and de-duplicates.
    assert out["domains"] == ["mybank.example"]
    # Read back from a saved setting.
    defaults["strict"].update({"enabled": True, "no_direct": True,
                               "domains": ["a.example"]})
    page2 = _page(defaults)[1]
    assert page2.strict_enabled.isChecked() is True
    assert page2.strict_no_direct.isChecked() is True
    assert page2.strict_domains.toPlainText() == "a.example"


def test_strict_reset_button_clears_the_extra_list(qapp, defaults):
    defaults["strict"]["domains"] = ["a.example"]
    win, page = _page(defaults)
    assert page.strict_domains.toPlainText() == "a.example"
    # The Reset button clears the user's extra list (the default AI list is
    # the placeholder, not the text).
    for btn in page.findChildren(type(page.btn_leak_now)):
        if btn.text() == "Reset":
            btn.click()
    assert page.strict_domains.toPlainText() == ""


def test_leakcheck_round_trips(qapp, defaults):
    win, page = _page(defaults)
    assert page.leak_enabled.isChecked() is False  # default OFF
    assert page.leak_notify.isChecked() is True  # default ON
    page.leak_enabled.setChecked(True)
    page.leak_notify.setChecked(False)
    out = win.values()["leakcheck"]
    assert out["enabled"] is True
    assert out["notify"] is False
    # The interval is carried through untouched.
    assert out["interval_s"] == defaults["leakcheck"]["interval_s"]


def test_firewall_round_trips_when_supported(qapp, defaults, monkeypatch):
    monkeypatch.setattr(firewall_mod, "supported", lambda: True)
    defaults["firewall"].update({"enabled": True, "allow_lan": False})
    win, page = _page(defaults)
    assert page.firewall_enabled is not None
    assert page.firewall_enabled.isChecked() is True
    assert page.firewall_allow_lan.isChecked() is False
    page.firewall_enabled.setChecked(False)
    assert win.values()["firewall"] == {"enabled": False, "allow_lan": False}


def test_firewall_group_hidden_when_unsupported(qapp, defaults, monkeypatch):
    monkeypatch.setattr(firewall_mod, "supported", lambda: False)
    win, page = _page(defaults)
    assert page.firewall_enabled is None
    assert page.firewall_allow_lan is None
    assert page._firewall_section is None
    # And the key is not emitted at all on an unsupported platform.
    assert "firewall" not in win.values()


# -- status banner: never claims a protection that is not active -------------

def _banner(state) -> dict:
    """security_summary() as {label: (state_text, is_real_state)}."""
    return {label: (text, real)
            for label, text, real in sp.security_summary({}, state)}


def test_banner_never_claims_killswitch_when_inactive(qapp, defaults):
    items = _banner(_live_state(killswitch_active=False))
    assert items["Kill switch"] == ("Off", False)
    # And it only claims "Active" when the blackholes are really in.
    items = _banner(_live_state(killswitch_active=True))
    assert items["Kill switch"] == ("Active", True)


def test_banner_never_claims_firewall_when_inactive(qapp, defaults):
    off = _banner(_live_state(firewall_supported=True, firewall_active=False))
    assert off["OS firewall"] == ("Inactive", False)
    on = _banner(_live_state(firewall_supported=True, firewall_active=True))
    assert on["OS firewall"] == ("Active", True)
    # An unsupported platform never claims the firewall is active.
    unsup = _banner(_live_state(firewall_supported=False, firewall_active=True))
    assert unsup["OS firewall"][1] is False


def test_banner_never_claims_leakcheck_without_a_verdict(qapp, defaults):
    items = _banner(_live_state(leakcheck_status=""))
    assert items["Leak check"][1] is False
    items = _banner(_live_state(leakcheck_status="protected"))
    assert items["Leak check"][1] is True


# -- hover help on every control ---------------------------------------------

def test_every_control_has_help(qapp, defaults, monkeypatch):
    monkeypatch.setattr(firewall_mod, "supported", lambda: True)
    win, page = _page(defaults)
    from xrayui.ui.help import is_help
    controls = [page.killswitch, page.strict_enabled, page.strict_ai_protect,
                page.strict_no_direct, page.strict_domains, page.leak_enabled,
                page.leak_notify, page.btn_leak_now, page.firewall_enabled,
                page.firewall_allow_lan, page._firewall_section.toggle]
    missing = [type(w).__name__ for w in controls if not is_help(w.toolTip())]
    assert not missing, f"controls without help: {missing}"


def test_not_covered_label_is_visible(qapp, defaults):
    win, page = _page(defaults)
    # Not explicitly hidden (the window itself is not shown in the test).
    assert not page._not_covered.isHidden()
    assert "Serverless-only" in page._not_covered.text()


# -- Persian keys complete ---------------------------------------------------

def test_fa_keys_complete_for_the_security_page(qapp, defaults):
    """Every literal the page passes to tr() has a Persian entry."""
    import ast
    from pathlib import Path
    path = Path(sp.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    literals = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "tr" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            literals.add(node.args[0].value)
    missing = [t for t in literals if t not in i18n_fa.TRANSLATIONS_FA]
    assert not missing, f"missing fa keys: {missing}"


def test_page_builds_in_persian(qapp, defaults):
    set_language("fa")
    try:
        win, page = _page(defaults)
        assert page._not_covered.text() != ""
        # The title is translated, not the English literal.
        assert win.windowTitle() == "تنظیمات"
    finally:
        set_language("en")


def test_settings_window_hands_the_live_connection_to_the_page(qapp, defaults):
    # The banner reads the live connection. Without it the page could never
    # show an active kill switch, even when the blackholes are installed.
    live = types.SimpleNamespace(killswitch_active=True)
    win = SettingsWindow(copy.deepcopy(defaults), connection=live)
    try:
        items = {label: (text, real) for label, text, real in sp.security_summary(
            defaults, win._pages["security"]._live_state())}
        assert items["Kill switch"] == ("Active", True)
    finally:
        win.close()


def test_banner_follows_the_connection_while_the_page_is_open(qapp, defaults):
    live = types.SimpleNamespace(killswitch_active=False)
    page = sp.SecurityPage(copy.deepcopy(defaults), connection=live)
    page.show()
    try:
        assert page._banner_items[0][1].text() == "Off"
        live.killswitch_active = True
        page._banner_timer.timeout.emit()
        assert page._banner_items[0][1].text() == "Active"
    finally:
        page.close()


def test_default_ai_list_is_not_shown_as_if_the_user_typed_it(qapp, defaults):
    page = sp.SecurityPage(copy.deepcopy(defaults))
    try:
        assert page.strict_domains.toPlainText() == ""
        assert "openai.com" not in page.strict_domains.placeholderText()
    finally:
        page.close()
