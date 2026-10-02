"""The first-run spotlight tour: cut-out geometry, navigation, when it runs."""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.i18n import set_language  # noqa: E402
from xrayui.ui import main_window as mw  # noqa: E402
from xrayui.ui import tour as tour_mod  # noqa: E402
from xrayui.ui.settings_window import SettingsWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    set_language("en")


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    window = mw.MainWindow(elevated=True)
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def _saved_seen() -> bool:
    return bool(app_settings.load().get("tour_seen"))


def _tour(win):
    win.start_tour()
    QApplication.processEvents()
    return win.tour


def _step_with_target(tour, index):
    tour.go_to(index)
    QApplication.processEvents()
    return tour


def test_tour_seen_defaults_to_false():
    assert app_settings.DEFAULTS["tour_seen"] is False


def test_nine_steps_and_the_first_is_centered(win):
    tour = _tour(win)
    assert tour.step_count() == 9
    assert tour.index() == 0
    assert tour.cutout() is None


def test_cutout_is_the_target_geometry_plus_padding(win):
    tour = _tour(win)
    tour.go_to(4)
    QApplication.processEvents()
    target = win.toolbar.btn_routing_popup
    top_left = target.mapTo(win, QPoint(0, 0))
    expected = QRect(top_left, target.size()).adjusted(
        -tour_mod.PAD, -tour_mod.PAD, tour_mod.PAD, tour_mod.PAD)
    assert tour.cutout() == expected


def test_steps_switch_pages_for_their_targets(win):
    win._show_page(mw.PAGE_ACTIVITY)
    tour = _tour(win)
    tour.go_to(1)
    QApplication.processEvents()
    assert win._current_page == mw.PAGE_SERVERS
    assert tour.cutout() is not None


def test_next_back_and_done(win):
    tour = _tour(win)
    tour.next()
    tour.next()
    assert tour.index() == 2
    tour.back()
    assert tour.index() == 1
    tour.back()
    tour.back()
    assert tour.index() == 0
    for _ in range(tour.step_count() - 1):
        tour.next()
    assert tour.is_last()
    tour.next()
    assert win.tour is None or not win.tour.isVisible()
    assert _saved_seen()


def test_last_step_button_says_done(win):
    tour = _tour(win)
    tour.go_to(tour.step_count() - 1)
    assert tour.next_button.text() == "Done"
    tour.go_to(0)
    assert tour.next_button.text() == "Next"


def test_skip_closes_and_remembers(win):
    tour = _tour(win)
    tour.next()
    tour.skip()
    QApplication.processEvents()
    assert not tour.isVisible()
    assert win.settings["tour_seen"] is True
    assert _saved_seen()


def test_keyboard_navigation(win):
    tour = _tour(win)
    QTest.keyClick(tour, Qt.Key_Right)
    assert tour.index() == 1
    QTest.keyClick(tour, Qt.Key_Return)
    assert tour.index() == 2
    QTest.keyClick(tour, Qt.Key_Left)
    assert tour.index() == 1
    QTest.keyClick(tour, Qt.Key_Escape)
    QApplication.processEvents()
    assert not tour.isVisible()
    assert _saved_seen()


def test_buttons_drive_the_tour(win):
    tour = _tour(win)
    tour.next_button.click()
    assert tour.index() == 1
    tour.back_button.click()
    assert tour.index() == 0
    tour.skip_button.click()
    assert not tour.isVisible()


def test_does_not_start_when_already_seen(win):
    win.settings["tour_seen"] = True
    win.maybe_start_tour()
    QApplication.processEvents()
    assert getattr(win, "tour", None) is None


def test_does_not_start_on_a_hidden_autostart(win):
    win.settings["tour_seen"] = False
    win.maybe_start_tour(shown=False)
    QApplication.processEvents()
    assert getattr(win, "tour", None) is None
    assert not win.settings.get("tour_seen")


def test_starts_on_first_shown_launch(win, qapp):
    win.settings["tour_seen"] = False
    win.maybe_start_tour()
    QTest.qWait(600)
    assert win.tour is not None and win.tour.isVisible()


def test_settings_button_starts_it_again(win, qapp):
    win.settings["tour_seen"] = True
    dlg = SettingsWindow(win.settings, win, profiles=[])
    asked = []
    dlg.tourRequested.connect(lambda: asked.append(True))
    page = dlg._pages["general"]
    page.btn_tour.click()
    assert asked == [True]
    win.start_tour()
    QApplication.processEvents()
    assert win.tour.isVisible()
    dlg.close()


def test_hidden_target_falls_back_to_a_centered_step(win):
    tour = _tour(win)
    win.toolbar.btn_routing_popup.hide()
    tour.go_to(4)
    QApplication.processEvents()
    assert tour.cutout() is None
    bubble = tour.bubble_rect()
    assert abs(bubble.center().x() - win.width() // 2) <= 2
    assert abs(bubble.center().y() - win.height() // 2) <= 2


def test_zero_size_target_falls_back_to_a_centered_step(win):
    tour = _tour(win)
    win.toolbar.btn_routing_popup.setFixedSize(0, 0)
    tour.go_to(4)
    QApplication.processEvents()
    assert tour.cutout() is None


@pytest.mark.parametrize("lang", ["en", "fa"])
def test_bubble_stays_inside_the_window_at_the_minimum_size(qapp, tmp_path, monkeypatch, lang):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    set_language(lang)
    window = mw.MainWindow(elevated=True)
    window.resize(window.minimumSize())
    window.show()
    qapp.processEvents()
    tour = _tour(window)
    inside = window.rect()
    for i in range(tour.step_count()):
        tour.go_to(i)
        qapp.processEvents()
        assert inside.contains(tour.bubble_rect()), (lang, i, tour.bubble_rect())
    window.close()


def test_tour_follows_a_resize(win, qapp):
    tour = _tour(win)
    tour.go_to(4)
    qapp.processEvents()
    win.resize(win.width() + 120, win.height() + 60)
    QTest.qWait(50)
    assert tour.geometry() == win.rect()
    target = win.toolbar.btn_routing_popup
    expected = QRect(target.mapTo(win, QPoint(0, 0)), target.size()).adjusted(
        -tour_mod.PAD, -tour_mod.PAD, tour_mod.PAD, tour_mod.PAD)
    assert tour.cutout() == expected


def test_persian_mirrors_the_bubble(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    set_language("fa")
    window = mw.MainWindow(elevated=True)
    window.show()
    qapp.processEvents()
    tour = _tour(window)
    assert tour.bubble.layoutDirection() == Qt.RightToLeft
    tour.go_to(1)
    qapp.processEvents()
    assert tour.back_button.x() > tour.next_button.x()
    assert tour.title_label.text() != "Import"
    window.close()
    set_language("en")
    window2 = mw.MainWindow(elevated=True)
    window2.show()
    qapp.processEvents()
    t2 = _tour(window2)
    assert t2.bubble.layoutDirection() == Qt.LeftToRight
    t2.go_to(1)
    qapp.processEvents()
    assert t2.back_button.x() < t2.next_button.x()
    window2.close()


def test_a_failing_step_closes_the_overlay_instead_of_breaking(win, qapp):
    tour = _tour(win)

    def boom():
        raise RuntimeError("gone")

    tour._steps[1].target = boom
    tour.go_to(1)
    qapp.processEvents()
    assert not tour.isVisible()


def test_every_step_has_text(win):
    tour = _tour(win)
    for s in tour._steps:
        assert s.title and s.text
    assert all(isinstance(b, QPushButton) for b in
               (tour.back_button, tour.next_button, tour.skip_button))


def test_server_list_step_lights_the_toolbar_and_the_list(win):
    tour = _tour(win)
    tour.go_to(2)
    QApplication.processEvents()
    cut = tour.cutout()
    for w in (win.servers_page.core.btn_import, win.servers_page.core.btn_test,
              win.servers_page.frame):
        assert cut.contains(QRect(w.mapTo(win, QPoint(0, 0)), w.size()))
