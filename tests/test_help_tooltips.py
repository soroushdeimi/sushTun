"""Every feature explains itself on hover: a width-limited rich tooltip with
what it does and a small example, in English and Persian.

The walk below fails for any control added without help, so a new button or
option cannot slip in unexplained.
"""
from __future__ import annotations

import copy
import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabBar,
    QWidget,
)

from xrayui import paths  # noqa: E402
from xrayui.core import chains as chain_core  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.core.subscription import Subscription  # noqa: E402
from xrayui.i18n import set_language  # noqa: E402
from xrayui.ui import main_window as mw  # noqa: E402
from xrayui.ui.dialogs import (  # noqa: E402
    ImportDialog,
    ProfileEditDialog,
    SubscriptionEditDialog,
)
from xrayui.ui.help import HELP_WIDTH, is_help  # noqa: E402
from xrayui.ui.pages.chains_page import ChainEditor, ChainsPage  # noqa: E402
from xrayui.ui.pages.dns_page import DnsPage  # noqa: E402
from xrayui.ui.pages.routing_page import COL_ACTION, RoutingPage  # noqa: E402
from xrayui.ui.rule_editor import RuleEditorDialog, default_rule  # noqa: E402
from xrayui.ui.server_table import COLUMNS  # noqa: E402
from xrayui.ui.settings_window import SettingsWindow  # noqa: E402
from xrayui.ui.widgets import set_help  # noqa: E402

_CONTROLS = (QAbstractButton, QComboBox, QSpinBox, QLineEdit, QPlainTextEdit)
# Standard dialog buttons name themselves; the title-bar lights already carry
# their own plain tooltips (Close / Minimize / Zoom).
_SELF_EVIDENT = {"Cancel", "OK", "Save", "Done", "Later"}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
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


def _desc(w: QWidget) -> str:
    text = w.text() if isinstance(w, QAbstractButton) else ""
    return (f"{type(w).__name__}#{w.objectName()} text={text!r} "
            f"name={w.accessibleName()!r}")


def _missing(root: QWidget, *, include_hidden: bool = False) -> list[str]:
    """Controls under *root* without help, menu actions and tabs included."""
    problems: list[str] = []
    for w in root.findChildren(QWidget):
        if isinstance(w, QMenu):
            if not w.toolTipsVisible():
                problems.append(f"menu {w.title()!r} hides its tooltips")
            for action in w.actions():
                if not action.isSeparator() and not is_help(action.toolTip()):
                    problems.append(f"action {action.text()!r}")
            continue
        if isinstance(w, QTabBar):
            for i in range(w.count()):
                if not is_help(w.tabToolTip(i)):
                    problems.append(f"tab {w.tabText(i)!r}")
            continue
        if not isinstance(w, _CONTROLS):
            continue
        if not include_hidden and w.isHidden():
            continue
        if type(w).__name__ == "TrafficLight" or w.objectName().startswith("qt_"):
            continue
        if isinstance(w.parentWidget(), (QSpinBox, QComboBox, QTabBar)):
            continue  # a spin box's inner editor, a tab bar's scroll arrows
        if isinstance(w, QPushButton) and w.text() in _SELF_EVIDENT:
            continue
        if not w.isEnabled() and w.toolTip():
            continue  # off, and its tooltip says why (e.g. no autostart here)
        if not is_help(w.toolTip()):
            problems.append(_desc(w))
    return problems


# -- the helper ---------------------------------------------------------------

def test_set_help_builds_a_width_limited_rich_tooltip(qapp):
    w = QPushButton("Go")
    set_help(w, "Does the thing.", "Use it on a rainy day.")
    tip = w.toolTip()
    assert is_help(tip)
    assert f'width="{HELP_WIDTH}"' in tip
    assert "Does the thing." in tip
    assert "Example: Use it on a rainy day." in tip
    assert "<i " in tip
    assert 'dir="rtl"' not in tip


def test_set_help_without_example_has_no_example_line(qapp):
    w = QPushButton("Go")
    set_help(w, "Does the thing.")
    assert "Example" not in w.toolTip()


def test_set_help_escapes_markup(qapp):
    w = QPushButton("Go")
    set_help(w, "Keep <b>this</b> literal & safe.", "a < b")
    tip = w.toolTip()
    assert "<b>this</b>" not in tip
    assert "&lt;b&gt;this&lt;/b&gt;" in tip
    assert "a &lt; b" in tip
    assert "&amp; safe" in tip


def test_set_help_is_right_to_left_in_persian(qapp):
    set_language("fa")
    w = QPushButton("Go")
    set_help(w, "x", "y")
    assert 'dir="rtl"' in w.toolTip()
    assert "مثلاً:" in w.toolTip()


def test_set_help_names_an_icon_only_button(qapp):
    w = QPushButton()
    w.setAccessibleName("More things")
    set_help(w, "Shows more.")
    assert "<b>More things</b>" in w.toolTip()


def test_set_help_on_a_row_control_also_covers_its_label(qapp):
    from xrayui.ui.mac import InsetGroup, Switch

    group = InsetGroup()
    switch = Switch()
    group.add_row("Label", switch)
    set_help(switch, "Explains it.")
    assert is_help(switch.parentWidget().toolTip())


# -- main window ----------------------------------------------------------------

def test_toolbar_header_and_sidebar_are_explained(win):
    explicit = [
        win.toolbar.btn_routing_popup, win.toolbar.btn_fragment, win.toolbar.btn_low,
        win.toolbar.filter_edit,
        win.status_card.btn_connect, win.status_card.btn_disconnect,
        win.status_card.btn_reconnect, win.status_card.btn_more,
        win.sidebar.btn_gateway, *win.sidebar._nav_items,
        win.servers_page.core.btn_import, win.servers_page.core.btn_test,
        win.servers_page.core.btn_fastest, win.servers_page.more_btn,
        win.servers_page.core.filter_edit,
    ]
    assert [_desc(w) for w in explicit
            if w.isEnabled() and not is_help(w.toolTip())] == []
    for root in (win.toolbar, win.sidebar, win.servers_page):
        assert [p for p in _missing(root) if "TrafficLight" not in p] == []


def test_connection_meta_line_is_explained(win):
    header = win.status_card
    # The meta label stays empty-tipped so a live full-text tooltip can show
    # when it is elided; hovering it falls through to its explained container.
    assert is_help(header._meta.parentWidget().toolTip())
    assert is_help(header._flag.parentWidget().toolTip())


def test_server_table_headers_are_explained(win):
    model = win.servers_page.core.model
    for column, title in enumerate(COLUMNS):
        tip = model.headerData(column, Qt.Horizontal, Qt.ToolTipRole)
        assert tip and is_help(tip), title


def test_sidebar_hotspot_keeps_the_reason_when_unavailable(win):
    win.sidebar.set_hotspot_supported(False, "Not here.")
    assert win.sidebar.btn_gateway.toolTip() == "Not here."


def test_routing_page_is_explained(qapp):
    page = RoutingPage(copy.deepcopy(app_settings.DEFAULTS["routing"]))
    page._add_set("empty")
    assert _missing(page) == []
    for column in range(4):
        tip = page.rule_model.headerData(column, Qt.Horizontal, Qt.ToolTipRole)
        assert tip and is_help(tip)
    assert page.rule_model.columnCount() > COL_ACTION


def test_dns_page_is_explained(qapp):
    page = DnsPage(copy.deepcopy(app_settings.DEFAULTS["dns"]),
                   copy.deepcopy(app_settings.DEFAULTS["routing"]))
    assert _missing(page) == []


def test_subscriptions_and_activity_pages_are_explained(win):
    win.subs.save(Subscription(name="Main", url="https://sub.example/x"))
    win._reload_subs()
    QApplication.processEvents()
    assert _missing(win.subs_panel) == []
    assert _missing(win.activity_page) == []


# -- chains --------------------------------------------------------------------

def _chain_profiles():
    return [Profile(name=f"Hop {i}", protocol="vless", address="example.org", port=443,
                    id="b1c2d3e4-0000-4000-8000-000000000001", uid=f"h{i}")
            for i in range(3)]


@pytest.mark.parametrize("lang", ["en", "fa"])
def test_chains_page_is_explained(qapp, lang):
    set_language(lang)
    items = _chain_profiles()
    chain = chain_core.Chain(name="Route", hops=[p.uid for p in items[:2]])
    broken = chain_core.Chain(name="Open", hops=["h0"])
    page = ChainsPage()
    page.set_chains([chain, broken], items, {})
    try:
        assert _missing(page, include_hidden=True) == []
        assert is_help(page.add_button.toolTip())
        assert is_help(page.cancel_button.toolTip())
        for card in page.cards:
            assert is_help(card.path_view.toolTip())
            assert is_help(card.expand.toolTip())
            assert is_help(card.wiring_table.toolTip())
            assert is_help(card.edit_button.toolTip())
            assert is_help(card.duplicate_action.toolTip())
            assert is_help(card.delete_button.toolTip())
        card = page.cards[0]
        for active in (True, False):
            card.set_testing(active)
            assert is_help(card.test_button.toolTip())
    finally:
        page.close()


def test_empty_chains_page_is_explained(qapp):
    page = ChainsPage()
    page.set_chains([], [], {})
    try:
        assert _missing(page, include_hidden=True) == []
    finally:
        page.close()


@pytest.mark.parametrize("lang", ["en", "fa"])
def test_chain_editor_is_explained(qapp, lang):
    set_language(lang)
    items = _chain_profiles()
    dlg = ChainEditor(items, {}, chain_core.Chain(name="Route", hops=["h0", "h1", "h0"]))
    try:
        assert _missing(dlg, include_hidden=True) == []
        for widget in (dlg.available, dlg.path):
            assert is_help(widget.toolTip())
        handles = [w for w in dlg.findChildren(QLabel) if w.text() == "⠿"]
        assert handles and all(is_help(w.toolTip()) for w in handles)
        removers = [w for w in dlg.findChildren(QPushButton) if w.text() == "×"]
        assert len(removers) == 3 and all(is_help(w.toolTip()) for w in removers)
    finally:
        dlg.close()


# -- settings ---------------------------------------------------------------------

def test_every_settings_page_and_option_is_explained(qapp):
    settings = copy.deepcopy(app_settings.DEFAULTS)
    settings["exits"]["items"] = [{"user": "a", "profile_uid": "p1"}]
    settings["forwards"] = [{"port": 2222, "target": "example.com:22"}]
    profiles = [Profile(name="de", protocol="vless", address="de.example.com", port=443,
                        id="b1c2d3e4-0000-4000-8000-000000000001", uid="p1")]
    win = SettingsWindow(settings, profiles=profiles)
    try:
        assert list(win._pages) == [
            "general", "anti-filter", "local-proxy", "geo-data", "hotspot",
            "startup", "exits", "forwards", "backup", "language"]
        for key, page in win._pages.items():
            assert _missing(page) == [], key
        assert _missing(win._sidebar) == []
        for item in win._sidebar_items:
            assert item.text() in item.toolTip()
    finally:
        win.close()


# -- dialogs -------------------------------------------------------------------------

def test_import_dialog_tabs_and_fields_are_explained(qapp):
    dlg = ImportDialog()
    try:
        assert _missing(dlg, include_hidden=True) == []
        assert dlg.tabs.count() == 3
    finally:
        dlg.close()


@pytest.mark.parametrize("protocol", ["vless", "vmess", "shadowsocks", "trojan",
                                      "wireguard", "hysteria2"])
def test_server_editor_fields_are_explained(qapp, protocol):
    dlg = ProfileEditDialog(Profile(name="de", protocol=protocol,
                                    address="de.example.com", port=443,
                                    id="b1c2d3e4-0000-4000-8000-000000000001"))
    try:
        assert _missing(dlg, include_hidden=True) == []
        labels = [w for w in dlg.findChildren(QLabel) if w.text() in ("Name", "Address", "Port")]
        assert labels and all(is_help(w.toolTip()) for w in labels)
    finally:
        dlg.close()


def test_subscription_and_rule_dialogs_are_explained(qapp):
    for dlg in (SubscriptionEditDialog(Subscription(name="Main", url="https://e.x/s")),
                RuleEditorDialog(default_rule())):
        try:
            assert _missing(dlg, include_hidden=True) == []
        finally:
            dlg.close()


# -- menus that are built on demand -----------------------------------------------

def test_context_and_header_menus_are_explained(win):
    core = win.servers_page.core
    for uids in (["a"], ["a", "b"]):
        menu = core._build_context_menu(uids)
        assert menu.toolTipsVisible()
        assert [a.text() for a in menu.actions()
                if not a.isSeparator() and not is_help(a.toolTip())] == []
    header_menu = core._build_header_menu()
    assert header_menu.toolTipsVisible()
    assert [a.text() for a in header_menu.actions() if not is_help(a.toolTip())] == []


def test_routing_menus_are_explained(win):
    win.settings["routing"]["sets"] = [{"id": "s1", "name": "Work", "rules": []}]
    win._build_routing_popup_menu(win.settings["routing"], "simple")
    win._refresh_routing_combo()
    menus = [win.toolbar.btn_routing_popup.menu()]
    if win.routing_menu is not None:
        menus.append(win.routing_menu)
    for menu in menus:
        assert menu.toolTipsVisible()
        actions = menu.actions()
        assert len(actions) == 2
        assert all(is_help(a.toolTip()) for a in actions)
