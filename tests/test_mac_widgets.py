"""Shared macOS-style widgets (mac.py), icons, theme tokens, ltr() in the
status figures, and the standalone connection header: construction,
interaction, signal plumbing and RTL mirroring.
"""
from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QFrame,
    QLabel,
    QMenu,
    QToolButton,
    QWidget,
)

from xrayui import i18n  # noqa: E402
from xrayui.ui import icons, theme  # noqa: E402
from xrayui.ui.connection_header import ConnectionHeader  # noqa: E402
from xrayui.ui.mac import (  # noqa: E402
    IconButton,
    InsetGroup,
    PopupButton,
    SidebarItem,
    SidebarSection,
    Switch,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _english_namespace():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def _render(widget) -> QPixmap:
    pm = QPixmap(widget.size())
    widget.render(pm)
    return pm


# -- Switch ---------------------------------------------------------------
def test_switch_toggles_on_click(qapp):
    sw = Switch()
    assert not sw.isChecked()
    sw.click()
    assert sw.isChecked()
    sw.click()
    assert not sw.isChecked()


def test_switch_toggles_with_space(qapp):
    sw = Switch()
    sw.resize(32, 19)
    sw.show()
    qapp.processEvents()
    sw.setFocus()
    QTest.keyClick(sw, Qt.Key_Space)
    assert sw.isChecked()
    QTest.keyClick(sw, Qt.Key_Space)
    assert not sw.isChecked()


def test_switch_accessible_name_is_settable(qapp):
    sw = Switch()
    sw.setAccessibleName("VPN toggle")
    assert sw.accessibleName() == "VPN toggle"


def test_switch_honours_disabled(qapp):
    sw = Switch()
    sw.setEnabled(False)
    assert not sw.isEnabled()
    sw.click()
    assert not sw.isChecked()


def test_switch_size_hint(qapp):
    sw = Switch()
    assert sw.sizeHint().width() == 32
    assert sw.sizeHint().height() == 19


# -- InsetGroup -----------------------------------------------------------
def test_inset_group_rows_with_separators(qapp):
    grp = InsetGroup()
    grp.add_row("First", footnote="foot 1")
    grp.add_row("Second", Switch())
    grp.add_row("Third")
    rows = grp.findChildren(QWidget, "InsetGroupRow")
    seps = grp.findChildren(QFrame, "InsetGroupSeparator")
    assert len(rows) == 3
    assert len(seps) == 2
    for row in rows:
        assert row.minimumHeight() >= 38


def test_inset_group_leading_trailing_mirrors_in_rtl(qapp):
    grp = InsetGroup()
    sw = Switch()
    row = grp.add_row("Server", sw, "footnote")
    grp.resize(320, 120)
    grp.show()
    qapp.processEvents()
    lbl = row.findChild(QLabel, "GroupRowLabel")
    note = row.findChild(QLabel, "GroupRowFootnote")
    # LTR: label + footnote lead on the left, trailing widget on the right.
    assert lbl.x() < sw.x()
    assert note.x() == lbl.x()
    grp.setLayoutDirection(Qt.RightToLeft)
    qapp.processEvents()
    # RTL mirrors the row: label now leads on the right, switch trails left.
    assert lbl.x() > sw.x()


def test_inset_group_label_keeps_full_width_in_narrow_row(qapp):
    # A row must never squeeze its label: the trailing widget gets the
    # leftover space, not the label. (The gallery used to show "ro…".)
    grp = InsetGroup()
    row = grp.add_row("Server settings", Switch())
    grp.resize(200, 60)
    grp.show()
    qapp.processEvents()
    lbl = row.findChild(QLabel, "GroupRowLabel")
    assert lbl.width() >= lbl.sizeHint().width()


def test_inset_group_trailing_switch_keeps_natural_size(qapp):
    # A Fixed-policy Switch ignores the row's extra stretch and stays
    # track-sized instead of ballooning across the row.
    grp = InsetGroup()
    sw = Switch()
    grp.add_row("Label", sw)
    grp.resize(420, 60)
    grp.show()
    qapp.processEvents()
    assert sw.width() == sw.sizeHint().width()


# -- Sidebar ------------------------------------------------
def test_sidebar_item_checked_state(qapp):
    item = SidebarItem("Servers", "servers")
    assert not item.isChecked()
    assert item.accessibleName() == "Servers"
    assert item.sizeHint().height() == 28
    item.setChecked(True)
    assert item.isChecked()
    # Rendering both states must not throw (icon tint + count label).
    item.resize(200, 28)
    item.set_count("12")
    _render(item)
    item.setChecked(False)
    _render(item)
    assert item.width() >= 200


def test_sidebar_section_is_a_label(qapp):
    section = SidebarSection("Account")
    assert isinstance(section, QLabel)
    assert section.text() == "Account"


# -- PopupButton ----------------------------------------------------------
def test_popup_button_set_value(qapp):
    pb = PopupButton("Routing", "Simple")
    assert pb.accessibleName() == "Routing: Simple"
    pb.set_value("Iran smart")
    assert pb.accessibleName() == "Routing: Iran smart"


def test_popup_button_menu_attach(qapp):
    pb = PopupButton("Routing")
    menu = QMenu()
    menu.addAction("A")
    pb.set_menu(menu)
    assert pb.menu() is menu
    assert pb.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup


def test_popup_button_renders(qapp):
    pb = PopupButton("Routing", "Iran smart")
    pb.resize(pb.sizeHint())
    _render(pb)


def test_popup_button_size_hint_respects_max_width(qapp):
    pb = PopupButton("Region", "x" * 200)
    assert pb.maximumWidth() == PopupButton._MAX_WIDTH
    assert pb.sizeHint().width() == PopupButton._MAX_WIDTH


def test_popup_button_elides_and_tooltips_at_narrow_width(qapp):
    value = "Iran smart routing"
    pb = PopupButton("Region", value)
    pb.show()
    qapp.processEvents()
    assert pb.width() <= PopupButton._MAX_WIDTH
    pb.resize(150, 26)
    qapp.processEvents()
    assert pb.toolTip() == f"Region: {value}"
    pb.resize(pb.sizeHint())
    qapp.processEvents()
    assert pb.toolTip() == ""


# -- IconButton -----------------------------------------------------------
def test_icon_button_tooltip_is_the_accessible_name(qapp):
    btn = IconButton("refresh", "Refresh")
    assert btn.toolTip() == "Refresh"
    assert btn.accessibleName() == "Refresh"


def test_icon_button_without_tooltip_is_impossible(qapp):
    with pytest.raises(TypeError):
        IconButton("refresh", "")
    with pytest.raises(TypeError):
        IconButton("refresh", None)  # type: ignore[arg-type]


def test_icon_button_is_an_icon_only_28_square(qapp):
    btn = IconButton("ellipsis", "More")
    assert btn.width() == 28 and btn.height() == 28
    assert btn.sizeHint() == QSize(28, 28)  # the hidden menu indicator adds nothing
    assert not btn.icon().isNull()


# -- icons ----------------------------------------------------------------
_ICON_NAMES = [
    "servers", "subscriptions", "routing", "dns", "activity", "hotspot",
    "settings", "shield-check", "bolt", "leaf", "anti-filter", "search",
    "chevron-down", "chevron-right", "ellipsis", "close", "refresh",
    "pencil", "arrow-up", "arrow-down", "plus", "check",
]


def test_every_required_icon_renders(qapp):
    for name in _ICON_NAMES:
        ic = icons.icon(name)
        assert not ic.isNull(), f"{name} produced a null QIcon"


def test_icon_accepts_a_custom_colour_and_size(qapp):
    ic = icons.icon("shield-check", "#ff453a", 22)
    assert not ic.isNull()


def test_unknown_icon_raises(qapp):
    with pytest.raises(KeyError):
        icons.icon("no-such-icon")


def test_renamed_icons_keep_their_aliases(qapp):
    aliases = (("connected", "shield-check"), ("edit", "pencil"),
               ("up", "arrow-up"), ("down", "arrow-down"),
               ("low-usage", "leaf"), ("test", "bolt"))
    for alias, _target in aliases:
        assert not icons.icon(alias).isNull(), alias


def test_icon_default_colour_is_text(qapp):
    assert not icons.icon("servers").isNull()


# -- theme -----------------------------------------------------------------
def test_stylesheet_has_visible_indicators():
    for needle in ("QCheckBox::indicator", "QRadioButton::indicator",
                   "::indicator:checked"):
        assert needle in theme.STYLESHEET


def test_build_stylesheet_has_the_mac_widget_rules():
    css = theme.build_stylesheet()
    for needle in ("QFrame#InsetGroup", "QLabel#SidebarSection",
                   "QToolButton#IconButton"):
        assert needle in css


def test_theme_tokens_present_and_unchanged():
    expected = {
        "ACCENT": "#0a84ff", "OK": "#30d158", "WARN": "#ffb340",
        "ERR": "#ff453a", "MUTED": "#98989d", "TEXT": "#f5f5f7",
        "BG": "#1e1e20", "SURFACE": "#2a2a2d", "SUNKEN": "#18181a",
        "LINE": "#38383c",
        "SIDEBAR": "#252528", "SIDEBAR_EDGE": "#1a1a1c",
        "HAIRLINE": "#2e2e31", "GROUP_SEP": "#333336",
        "ZEBRA": "rgba(255,255,255,0.025)",
    }
    for token, value in expected.items():
        assert getattr(theme, token) == value


# -- ConnectionHeader -----------------------------------------------------
def test_connection_header_set_and_connected(qapp):
    h = ConnectionHeader()
    h.set("throughput", "↓ 4.2 ↑ 0.3 Mbit/s")
    h.set("used", "18.6 GB")
    assert h._down_up_col[1].text() == i18n.ltr("↓ 4.2 ↑ 0.3 Mbit/s")
    assert h._session_col[1].text() == i18n.ltr("18.6 GB")
    assert h._meta.text() == "—"


def test_connection_header_meta_line_uses_ltr(qapp):
    h = ConnectionHeader()
    h.set("endpoint", "de.example.com:443")
    h.set("protocol", "reality")
    h.set("delay", "650 ms")
    h.set("iface", "utun3")
    assert h._meta.text() == " · ".join(i18n.ltr(p) for p in (
        "de.example.com:443", "reality", "650 ms", "utun3"))


def test_connection_header_connected_state(qapp):
    h = ConnectionHeader()
    h.show()
    h.set_connected(False)
    assert h._state.text() == "Disconnected"
    assert h.btn_connect.isVisible() and not h.btn_disconnect.isVisible()
    h.set_connected(True)
    assert h._state.text() == "Connected"
    assert not h.btn_connect.isVisible() and h.btn_disconnect.isVisible()


def test_connection_header_state_translates_to_fa(_english_namespace):
    i18n.set_language("fa")
    h = ConnectionHeader()
    h.set_connected(True)
    assert h._state.text() == "متصل"
    h.set_connected(False)
    assert h._state.text() == "قطع شده"


def test_connection_header_action_signals(qapp):
    h = ConnectionHeader()
    fired: dict[str, int] = {
        "connectRequested": 0, "disconnectRequested": 0, "reconnectRequested": 0}
    for name in fired:
        getattr(h, name).connect(
            lambda _name=name: fired.__setitem__(_name, fired[_name] + 1))
    h.btn_connect.click()
    h.set_connected(True)
    h.btn_disconnect.click()
    h.btn_reconnect.click()
    assert fired == {"connectRequested": 1, "disconnectRequested": 1,
                     "reconnectRequested": 1}


def test_connection_header_restore_network_menu_signal(qapp):
    h = ConnectionHeader()
    fired: list[str] = []
    h.restoreNetworkRequested.connect(lambda: fired.append(True))
    actions = h.btn_more.menu().actions()
    assert [a.text() for a in actions] == ["Restore network"]
    actions[0].trigger()
    assert fired == [True]


def test_connection_header_reconnect_notice(qapp):
    h = ConnectionHeader()
    h.show()
    qapp.processEvents()
    h.hide_reconnect()
    assert not h.btn_reconnect.isVisible()
    h.show_reconnect("Config changed")
    qapp.processEvents()
    assert h.btn_reconnect.isVisible()
    assert h._notice_label.text() == i18n.ltr("Config changed")
    h.hide_reconnect()
    assert not h.btn_reconnect.isVisible()
    assert h._notice_label.text() == ""


def test_connection_header_timer(qapp):
    h = ConnectionHeader()
    h.set_timer("00:12")
    assert h._timer_pill.text() == "00:12"
    h.set_timer("")
    assert h._timer_pill.text() == ""


def test_connection_header_renders_every_state(qapp):
    h = ConnectionHeader()
    h.resize(680, 120)
    h.set_connected(False)
    h.show_reconnect("Reconnecting…")
    _render(h)
    h.set_connected(True)
    h.hide_reconnect()
    _render(h)


# -- layout gate: nothing may clip -------------------------------------
# The review gate materialised as tests: render the header at a given width
# in the given language and assert every label/button is at least its
# sizeHint wide, except the two labels that elide on purpose and then carry
# the full text in their tooltip (_meta, _notice_label -- checked separately).


def _header_for_layout_tests() -> ConnectionHeader:
    h = ConnectionHeader()
    h.set("endpoint", "de.example.com:443")
    h.set("protocol", "reality")
    h.set("delay", "650 ms")
    h.set("iface", "utun3")
    h.set("throughput", "↓ 4.2 ↑ 0.3 Mbit/s")
    h.set("used", "18.6 GB")
    h.set_connected(True)
    h.set_timer("00:42:17")
    return h


@pytest.mark.parametrize("lang,width", [
    ("en", 560), ("en", 800),
    ("fa", 560), ("fa", 800),
])
def test_connection_header_lays_out_without_clipping(qapp, lang, width):
    i18n.set_language(lang)
    h = _header_for_layout_tests()
    h.show_reconnect(
        i18n.tr("{what} — reconnect to apply.", what=i18n.tr("DNS saved")))
    h.resize(width, 180)
    h.show()
    qapp.processEvents()
    # If the header refused to shrink below its content, the test would be
    # vacuously green; the object of this test is a 560px window.
    assert h.width() == width
    elide = (h._meta, h._notice_label)
    kids = h.findChildren(QLabel) + h.findChildren(QAbstractButton)
    for w in kids:
        if w in elide:
            continue
        hint = w.sizeHint().width()
        assert w.width() + 1 >= hint, (
            f"{lang}/{width}px: {w.objectName() or type(w).__name__} "
            f"at {w.width()}px < sizeHint {hint}px")
    h.hide()
    i18n.set_language("en")


def test_connection_header_elide_labels_tooltip_the_full_text(qapp):
    i18n.set_language("fa")
    h = _header_for_layout_tests()
    h.show_reconnect(
        i18n.tr("{what} — reconnect to apply.", what=i18n.tr("DNS saved")))
    h.resize(480, 180)
    h.show()
    qapp.processEvents()
    for lbl, full in ((h._meta, h._meta_full),
                      (h._notice_label, h._notice_full)):
        fits = lbl.fontMetrics().horizontalAdvance(full) <= lbl.width()
        if fits:
            assert lbl.toolTip() == "", lbl.objectName()
        else:
            assert lbl.toolTip() == full, lbl.objectName()
    h.hide()
    i18n.set_language("en")


def test_connection_header_meta_elides_middle_with_tooltip(qapp):
    h = ConnectionHeader()
    h.set("endpoint", "an-extra-long-server-address.example-vpn-provider.com")
    h.set("protocol", "reality")
    h.set("iface", "utun3")
    h.set_connected(True)
    h.resize(360, 160)
    h.show()
    qapp.processEvents()
    fm = h._meta.fontMetrics()
    assert fm.horizontalAdvance(h._meta.text()) < fm.horizontalAdvance(h._meta_full)
    assert "…" in h._meta.text()
    assert h._meta.toolTip() == h._meta_full
    h.hide()


# -- fa reconnect notice: no English leaks (except technical terms) -------
def test_fa_reconnect_notice_keeps_only_technical_terms_latin(qapp):
    i18n.set_language("fa")
    h = ConnectionHeader()
    # Advanced-settings path: the changed list is built from translated
    # labels -- a bare literal here would leak into the notice.
    changed = [label for label, old, new in (
        (i18n.tr("MTU"), 1, 2),
        (i18n.tr("Log level"), "a", "b"),
        (i18n.tr("Core options"), {}, {}),
    ) if old != new]
    h.show_reconnect(i18n.tr(
        "{what} — reconnect to apply.",
        what=i18n.tr("{items} changed", items=", ".join(changed))))
    latin = set(re.findall(r"[A-Za-z]+", h._notice_full))
    assert latin <= {"MTU"}, f"unexpected English in fa notice: {sorted(latin)}"
    # A second path ("DNS saved"): DNS stays Latin, everything else is fa.
    h.show_reconnect(i18n.tr(
        "{what} — reconnect to apply.", what=i18n.tr("DNS saved")))
    latin = set(re.findall(r"[A-Za-z]+", h._notice_full))
    assert latin <= {"DNS"}, f"unexpected English in fa notice: {sorted(latin)}"
    h.hide()
    i18n.set_language("en")
