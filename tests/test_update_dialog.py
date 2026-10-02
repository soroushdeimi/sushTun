"""The update dialog: what each build is offered, and that nothing is
installed until a verified download has actually arrived."""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from xrayui.core import desktop as desktop_mod  # noqa: E402
from xrayui.core import updates as updates_mod  # noqa: E402
from xrayui.ui import update_dialog as update_dialog_mod  # noqa: E402
from xrayui.ui.update_dialog import UpdateDialog  # noqa: E402

RELEASE = updates_mod.Release(
    tag="v9.9.9", url="https://example.com/releases/v9.9.9",
    notes="### Fixed\n- a thing",
    assets={"sushTun-linux": "https://example.com/sushTun-linux",
            "SHA256SUMS": "https://example.com/SHA256SUMS"})


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def installable(monkeypatch):
    """A build that can replace itself, without touching the real platform."""
    monkeypatch.setattr(updates_mod, "asset_for_this_build", lambda _r: "sushTun-linux")
    monkeypatch.setattr(updates_mod, "installed_windows", lambda: False)
    monkeypatch.setattr(updates_mod, "installed_deb", lambda: False)


@pytest.fixture
def not_installable(monkeypatch):
    monkeypatch.setattr(updates_mod, "asset_for_this_build", lambda _r: None)
    monkeypatch.setattr(updates_mod, "installed_windows", lambda: False)
    monkeypatch.setattr(updates_mod, "installed_deb", lambda: False)


def test_offers_to_install_and_shows_the_release_notes(qapp, installable):
    dlg = UpdateDialog(RELEASE)
    try:
        assert "9.9.9" in dlg.windowTitle() or "9.9.9" in _heading(dlg)
        assert "a thing" in dlg.notes.toPlainText()
        assert dlg.btn_primary.isDefault()
        assert not dlg.progress.isVisible()
        assert not dlg.installed()
    finally:
        dlg.close()


def test_a_build_that_cannot_replace_itself_is_sent_to_the_release_page(qapp, not_installable):
    """Silently offering an Install button that cannot install is worse than
    saying so: the user is told why and handed the download page instead."""
    dlg = UpdateDialog(RELEASE)
    try:
        assert "download page" in dlg.btn_primary.text().lower()
        assert dlg.subtitle.text() != ""
    finally:
        dlg.close()


def test_the_release_page_button_opens_through_the_users_session(
        qapp, monkeypatch, not_installable):
    # Elevated on Linux, Qt's own opener reaches nothing, so the .deb's only
    # button used to close the dialog having done nothing at all.
    opened = []
    monkeypatch.setattr(desktop_mod, "open_url",
                        lambda url: bool(opened.append(url)) or True)
    dlg = UpdateDialog(RELEASE)
    try:
        dlg._on_primary()
        assert opened == [RELEASE.url]
        assert dlg.result() == QDialog.Accepted
    finally:
        dlg.close()


def test_a_link_that_cannot_be_opened_is_shown_instead_of_swallowed(
        qapp, monkeypatch, not_installable):
    monkeypatch.setattr(desktop_mod, "open_url", lambda _url: False)
    monkeypatch.setattr(update_dialog_mod.QDesktopServices, "openUrl",
                        staticmethod(lambda _url: False))
    dlg = UpdateDialog(RELEASE)
    try:
        dlg._on_primary()
        assert RELEASE.url in dlg.status.text()
        # isVisible is False while the dialog itself was never shown; what
        # matters is that the label is no longer explicitly hidden.
        assert not dlg.status.isHidden()
        assert dlg.result() != QDialog.Accepted  # still open, still answerable
    finally:
        dlg.close()


def test_release_note_links_go_through_the_same_opener(qapp, monkeypatch, installable):
    # setOpenExternalLinks would hand these straight to Qt, which fails the
    # same way; the dialog routes them itself.
    opened = []
    monkeypatch.setattr(desktop_mod, "open_url",
                        lambda url: bool(opened.append(url)) or True)
    dlg = UpdateDialog(RELEASE)
    try:
        assert not dlg.notes.openExternalLinks()
        dlg.notes.anchorClicked.emit(QUrl("https://example.com/changelog"))
        assert opened == ["https://example.com/changelog"]
    finally:
        dlg.close()


def test_the_deb_gets_the_normal_download_and_install_flow(qapp, monkeypatch):
    monkeypatch.setattr(updates_mod, "installed_deb", lambda: True)
    monkeypatch.setattr(updates_mod, "installed_windows", lambda: False)
    monkeypatch.setattr(updates_mod, "asset_for_this_build",
                        lambda _r: "sushtun_9.9.9_amd64.deb")
    dlg = UpdateDialog(RELEASE)
    try:
        assert "install" in dlg.btn_primary.text().lower()
        assert "apt" not in dlg.subtitle.text()
        assert dlg.relaunches_itself() is False
    finally:
        dlg.close()


def test_a_failed_download_offers_another_try_and_installs_nothing(qapp, installable):
    dlg = UpdateDialog(RELEASE)
    try:
        dlg._on_downloaded(error="the server hung up")
        assert "the server hung up" in dlg.status.text()
        assert dlg.btn_primary.isEnabled()
        assert not dlg.installed()
    finally:
        dlg.close()


def test_a_cancelled_download_says_so_rather_than_failing(qapp, installable):
    dlg = UpdateDialog(RELEASE)
    try:
        dlg._cancel.set()
        dlg._on_downloaded(error="cancelled")
        assert "cancelled" in dlg.status.text().lower()
    finally:
        dlg.close()


def test_install_only_runs_once_a_download_has_arrived(qapp, installable, monkeypatch):
    installs = []
    monkeypatch.setattr(updates_mod, "install", lambda path: installs.append(path))
    dlg = UpdateDialog(RELEASE)
    try:
        # Nothing downloaded yet: pressing the button starts a download, it
        # does not install.
        started = []
        monkeypatch.setattr(dlg, "_start_download", lambda: started.append(True))
        dlg._on_primary()
        assert started == [True] and installs == []

        dlg._on_downloaded(path="/tmp/sushTun-linux")
        assert "restart" in dlg.btn_primary.text().lower()
        dlg._on_primary()
        assert installs == ["/tmp/sushTun-linux"]
        assert dlg.installed()
    finally:
        dlg.close()


def test_an_install_that_fails_leaves_the_dialog_open_to_retry(qapp, installable, monkeypatch):
    def boom(_path):
        raise updates_mod.UpdateError("could not move the current version aside")

    monkeypatch.setattr(updates_mod, "install", boom)
    dlg = UpdateDialog(RELEASE)
    try:
        dlg._on_downloaded(path="/tmp/sushTun-linux")
        dlg._on_primary()
        assert "could not move" in dlg.status.text()
        assert not dlg.installed()
        assert dlg.isVisible() or not dlg.result()
    finally:
        dlg.close()


def test_progress_survives_a_server_that_sends_no_length(qapp, installable):
    """No Content-Length means no percentage; a busy bar still says it works."""
    dlg = UpdateDialog(RELEASE)
    try:
        dlg._on_progress(5 * 1024 * 1024, 0)
        assert dlg.progress.maximum() == 0
        dlg._on_progress(5 * 1024 * 1024, 10 * 1024 * 1024)
        assert dlg.progress.value() == 50
    finally:
        dlg.close()


def _heading(dlg) -> str:
    from PySide6.QtWidgets import QLabel
    return " ".join(w.text() for w in dlg.findChildren(QLabel))


NOTES = ("- English note\n\n<!-- fa -->\n- یادداشت فارسی\n\n"
         "**Full Changelog**: https://github.com/x/y/compare/v1...v2\n")
NOTES_RELEASE = updates_mod.Release(tag="v9.9.9", url="https://x", notes=NOTES)


@pytest.fixture
def language(qapp):
    from xrayui import i18n
    yield i18n.set_language
    i18n.set_language("en")


def test_persian_ui_shows_the_persian_notes_right_to_left(qapp, installable, language):
    language("fa")
    dlg = UpdateDialog(NOTES_RELEASE)
    try:
        text = dlg.notes.toPlainText()
        assert "یادداشت فارسی" in text and "English note" not in text
        assert "Full Changelog" not in text
        assert dlg.notes.layoutDirection() == Qt.RightToLeft
    finally:
        dlg.close()


def test_english_ui_shows_the_english_notes(qapp, installable, language):
    language("en")
    dlg = UpdateDialog(NOTES_RELEASE)
    try:
        text = dlg.notes.toPlainText()
        assert "English note" in text and "یادداشت" not in text
        assert "Full Changelog" not in text
        assert dlg.notes.layoutDirection() == Qt.LeftToRight
    finally:
        dlg.close()


def test_notes_that_are_only_githubs_link_show_the_empty_message(qapp, installable):
    only_link = updates_mod.Release(
        tag="v9.9.9", url="https://x",
        notes="**Full Changelog**: https://github.com/x/y/compare/v1...v2")
    dlg = UpdateDialog(only_link)
    try:
        assert dlg.notes.toPlainText().strip() == "No release notes."
    finally:
        dlg.close()


def test_every_block_is_right_to_left_in_persian(qapp, installable, language):
    language("fa")
    rel = updates_mod.Release(
        tag="v9.9.9", url="https://x",
        notes="<!-- fa -->\n- macOS اول\n- دوم\n\nیک پاراگراف")
    dlg = UpdateDialog(rel)
    try:
        block = dlg.notes.document().begin()
        count = 0
        while block.isValid():
            assert block.blockFormat().layoutDirection() == Qt.RightToLeft
            count += 1
            block = block.next()
        assert count >= 3
    finally:
        dlg.close()


def test_latin_runs_are_isolated_in_persian_only(qapp, installable, language):
    from xrayui.core.release_notes import isolate_latin
    out = isolate_latin("- با OpenVPN Connect و 0/1 + 128/1 (`-device`).\n"
                        "[x](https://a.b/c) و https://a.b/c")
    assert "\u2066OpenVPN Connect\u2069" in out
    assert "\u20660/1 + 128/1\u2069" in out
    assert "\u2066`-device`\u2069" in out
    assert out.startswith("- ")
    assert "(https://a.b/c)" in out and "\u2066https" not in out
    language("en")
    dlg = UpdateDialog(NOTES_RELEASE)
    try:
        assert "\u2066" not in dlg.notes.toPlainText()
    finally:
        dlg.close()
