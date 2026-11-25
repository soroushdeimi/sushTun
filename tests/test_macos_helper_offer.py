"""The one-time macOS password-free helper offer: shown after a successful
password elevation on an installed macOS app, never repeated once seen, and a
no-op everywhere else.
"""
from __future__ import annotations

import os
import sys

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import macos_helper  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.i18n import set_language  # noqa: E402
from xrayui.ui import main_window as mw  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


@pytest.fixture
def win(qapp, tmp_path, monkeypatch, flush_widgets):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    flush_widgets()
    window = mw.MainWindow(elevated=True)
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def _as_macos(monkeypatch, offer=True):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(macos_helper, "should_offer", lambda: offer)


def _button(box, text):
    for b in box.buttons():
        if b.text() == text:
            return b
    raise AssertionError(f"no button {text!r} in {box.buttons()}")


def test_offer_shown_on_macos_when_it_applies(win, monkeypatch):
    _as_macos(monkeypatch, offer=True)
    win._elevated = True
    win.maybe_offer_macos_helper()
    assert win._helper_offer is not None
    assert win._helper_offer.isVisible()
    # The offer is remembered the moment it is shown, so it is never repeated.
    assert win.settings["helper_offer_seen"] is True


def test_offer_never_shown_twice(win, monkeypatch):
    _as_macos(monkeypatch, offer=True)
    win._elevated = True
    win.maybe_offer_macos_helper()
    first = win._helper_offer
    win.maybe_offer_macos_helper()
    assert win._helper_offer is first  # the second call is a no-op


def test_offer_not_shown_when_should_offer_is_false(win, monkeypatch):
    _as_macos(monkeypatch, offer=False)
    win._elevated = True
    win.maybe_offer_macos_helper()
    assert win._helper_offer is None
    # Not offered, so not marked seen: a later launch may still offer.
    assert not win.settings.get("helper_offer_seen")


def test_offer_not_shown_when_not_elevated(win, monkeypatch):
    _as_macos(monkeypatch, offer=True)
    win._elevated = False
    win.maybe_offer_macos_helper()
    assert win._helper_offer is None


def test_offer_not_shown_off_macos(win, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    win._elevated = True
    win.maybe_offer_macos_helper()
    assert win._helper_offer is None


def test_yes_installs_and_reports_success(win, monkeypatch):
    _as_macos(monkeypatch, offer=True)
    win._elevated = True
    steps: list[str] = []
    monkeypatch.setattr(win, "_on_step", steps.append)
    monkeypatch.setattr(win, "_run_async",
                        lambda work, done: done(result=work(), error=None))
    monkeypatch.setattr(macos_helper, "install", lambda: True)
    win.maybe_offer_macos_helper()
    _button(win._helper_offer, 'Yes').click()
    assert any("Password-free start is on" in s for s in steps)


def test_yes_reports_failure(win, monkeypatch):
    _as_macos(monkeypatch, offer=True)
    win._elevated = True
    steps: list[str] = []
    monkeypatch.setattr(win, "_on_step", steps.append)
    monkeypatch.setattr(win, "_run_async",
                        lambda work, done: done(result=work(), error=None))
    monkeypatch.setattr(macos_helper, "install", lambda: False)
    win.maybe_offer_macos_helper()
    _button(win._helper_offer, 'Yes').click()
    assert any("Could not install" in s for s in steps)


def test_no_and_later_do_not_install(win, monkeypatch):
    _as_macos(monkeypatch, offer=True)
    win._elevated = True
    installs: list = []
    monkeypatch.setattr(win, "_run_async",
                        lambda work, done: installs.append(work))
    monkeypatch.setattr(macos_helper, "install", lambda: True)
    win.maybe_offer_macos_helper()
    _button(win._helper_offer, 'No').click()
    assert installs == []
    # A fresh offer: "Later" also must not install.
    win._helper_offer = None
    win.settings["helper_offer_seen"] = False
    win.maybe_offer_macos_helper()
    _button(win._helper_offer, 'Later').click()
    assert installs == []


def test_default_is_yes(win, monkeypatch):
    _as_macos(monkeypatch, offer=True)
    win._elevated = True
    win.maybe_offer_macos_helper()
    assert win._helper_offer.defaultButton().text() == "Yes"


def test_helper_offer_seen_defaults_to_false():
    assert app_settings.DEFAULTS["helper_offer_seen"] is False
