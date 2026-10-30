"""DnsPage (embeddable): malformed fields and config-check failures refuse
inline on the page's status label and never touch the stored dns config. The
dialog is the same page behind a thin wrapper, so that behaviour is covered
here once for both entry points.
"""
from __future__ import annotations

import copy
import os
import time

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402

from xrayui.core import xraycheck  # noqa: E402
from xrayui.core.settings import DEFAULTS  # noqa: E402
from xrayui.ui.pages.dns_page import DnsPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pump(condition, timeout=5.0) -> None:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


@pytest.mark.parametrize("entry,fragment", [
    ("8.8.8.8:5353", "scheme"),        # Xray parses a scheme-less entry as a URL
    ("localhost", "loop"),             # resolves back into this app's own resolver
    ("not a server", "spaces"),
    ("https://", "no server after the scheme"),
])
def test_invalid_server_refuses_inline(qapp, entry, fragment):
    page = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])
    page.servers.setPlainText(entry)
    original = copy.deepcopy(DEFAULTS["dns"])

    page.apply()

    assert fragment in page.status_label.text(), f"no refusal shown for {entry}"
    assert page.result_dns() == original


def test_config_check_failure_leaves_settings_unchanged(qapp, monkeypatch):
    # dns fields are valid here; the refusal comes from the real
    # render+validate round trip, which is stubbed to fail like xray would
    # on an unknown geosite category in the active routing.
    monkeypatch.setattr(xraycheck, "check_config",
                        lambda *a, **k: "unknown geosite category: not-a-real-category-xyz")
    bad_routing = copy.deepcopy(DEFAULTS["routing"])
    bad_routing["bypass_domains"] = ["geosite:not-a-real-category-xyz"]
    page = DnsPage(DEFAULTS["dns"], bad_routing)
    original = copy.deepcopy(DEFAULTS["dns"])
    page.servers.setPlainText("1.1.1.1")

    page.apply()
    _pump(lambda: not page._busy)

    assert "unknown geosite category" in page.status_label.text()
    assert page.result_dns() == original


def test_dns_page_starts_clean_and_silent(qapp):
    # An empty resolvers field means "inherit the template", so a genuinely
    # clean page must not reject anything nor show a stale status.
    page = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])
    assert not page.is_dirty()
    assert page.status_label.text() == ""


def test_dns_page_dirty_revert_and_applied_signal(qapp, monkeypatch):
    monkeypatch.setattr(xraycheck, "check_config", lambda *a, **k: None)
    page = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])
    assert not page.is_dirty()
    assert not page.btn_apply.isEnabled()

    captured = []
    page.applied.connect(lambda cfg: captured.append(cfg))
    page.servers.setPlainText("1.1.1.1")
    assert page.is_dirty()
    assert page.btn_apply.isEnabled()
    assert page.result_dns()["servers"] == []  # not applied yet

    page.apply()
    _pump(lambda: not page._busy)

    assert len(captured) == 1
    assert page.result_dns()["servers"] == ["1.1.1.1"]
    assert not page.is_dirty()
    assert not page.btn_apply.isEnabled()

    page.servers.setPlainText("8.8.8.8")
    assert page.is_dirty()
    page.revert()
    assert not page.is_dirty()
    assert page.result_dns()["servers"] == ["1.1.1.1"]
    assert page.servers.toPlainText() == "1.1.1.1"


def test_refusal_text_isolates_the_raw_value(qapp):
    # The user's own raw input inside a refusal text is wrapped in isolation
    # marks so Persian RTL layout renders it left-to-right as one unit.
    page = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])
    page.servers.setPlainText("not a server")
    page.apply()
    assert "\u2066not a server\u2069" in page.status_label.text()


def test_enter_in_the_resolvers_editor_inserts_a_newline_not_an_apply(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(xraycheck, "check_config", lambda *a, **k: calls.append(1) or None)
    page = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])
    page.servers.setFocus()
    QTest.keyClick(page.servers, Qt.Key_Return)
    assert not calls  # Return is a new paragraph, never a save
    assert "\n" in page.servers.toPlainText()


def test_bypass_use_system_dns_checkbox_lifecycle(qapp, monkeypatch):
    monkeypatch.setattr(xraycheck, "check_config", lambda *a, **k: None)
    page = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])

    # Checkbox exists
    assert hasattr(page, "bypass_use_system_dns")
    assert isinstance(page.bypass_use_system_dns, QCheckBox)

    # Defaults unchecked
    assert not page.bypass_use_system_dns.isChecked()
    assert page.bypass_use_system_dns.isEnabled()

    # Becomes disabled when domestic servers has text and re-enabled when cleared
    page.domestic.setText("178.22.122.100")
    assert not page.bypass_use_system_dns.isEnabled()
    assert "Disabled because" in page.bypass_use_system_dns.toolTip()

    page.domestic.setText("")
    assert page.bypass_use_system_dns.isEnabled()
    assert "Takes effect on the next connection" in page.bypass_use_system_dns.toolTip()

    # Presets and off buttons update the state
    page._fill_domestic(["178.22.122.100"])
    assert not page.bypass_use_system_dns.isEnabled()
    page._fill_domestic([])
    assert page.bypass_use_system_dns.isEnabled()

    # Round-trips through load/save (apply) and saved dict contains the key as a real bool
    page.bypass_use_system_dns.setChecked(True)
    assert page.is_dirty()
    page.apply()
    _pump(lambda: not page._busy)
    assert not page.is_dirty()
    saved = page.result_dns()
    assert "bypass_use_system_dns" in saved
    assert saved["bypass_use_system_dns"] is True
    assert type(saved["bypass_use_system_dns"]) is bool

    # Round-trip through load
    loaded_cfg = copy.deepcopy(saved)
    loaded_cfg["bypass_use_system_dns"] = False
    page.load(loaded_cfg, DEFAULTS["routing"])
    assert not page.bypass_use_system_dns.isChecked()
    assert not page.is_dirty()

    loaded_cfg["bypass_use_system_dns"] = True
    page.load(loaded_cfg, DEFAULTS["routing"])
    assert page.bypass_use_system_dns.isChecked()
    assert not page.is_dirty()

    # Revert restores original state
    page.bypass_use_system_dns.setChecked(False)
    assert page.is_dirty()
    page.revert()
    assert not page.is_dirty()
    assert page.bypass_use_system_dns.isChecked()


def test_bypass_dns_strings_have_persian_translations():
    from xrayui import i18n_fa
    expected_strings = [
        "Resolve bypassed sites with this computer's own DNS",
        (
            "Resolves sites in Routing bypass using this computer's own DNS. "
            "Only applies when Domestic DNS is empty. "
            "Takes effect on the next connection."
        ),
        (
            "Disabled because Domestic DNS is set, which takes precedence. "
            "Clear Domestic DNS to use this computer's own DNS for bypassed sites."
        ),
        (
            'Bypassed sites resolve via the tunnel unless Domestic DNS or '
            '"Resolve bypassed sites with this computer\'s own DNS" is set in DNS settings.'
        ),
    ]
    for text in expected_strings:
        assert text in i18n_fa.TRANSLATIONS_FA, f"Missing translation for: {text!r}"
        assert i18n_fa.TRANSLATIONS_FA[text], f"Empty translation for: {text!r}"



def test_bypass_checkbox_ignores_invalid_domestic_text(qapp, monkeypatch):
    monkeypatch.setattr(xraycheck, "check_config", lambda *a, **k: None)
    page = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])
    page.domestic.setText("not a server !!")
    assert page.bypass_use_system_dns.isEnabled()


def test_bypass_checkbox_value_survives_the_settings_file(qapp, monkeypatch, tmp_path):
    """UI -> settings.save -> settings.load: the schema merge must not drop the key."""
    from xrayui.core import settings as app_settings
    monkeypatch.setattr(xraycheck, "check_config", lambda *a, **k: None)
    page = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])
    page.bypass_use_system_dns.setChecked(True)
    page.apply()
    _pump(lambda: not page._busy)
    saved = page.result_dns()
    # Only now point the settings file at tmp: build_text needs the real base dir.
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    cfg = app_settings.load()
    cfg["dns"] = saved
    app_settings.save(cfg)
    assert app_settings.load()["dns"]["bypass_use_system_dns"] is True
