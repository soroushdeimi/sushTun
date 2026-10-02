"""Bypass / routing editor as an embeddable page: Simple mode (today's
toggles) and custom routing rule sets, plus dirty tracking, revert and an
off-thread apply for the sidebar window. The RoutingDialog is a thin
wrapper around this page (see routing_dialog.py).

The page compares the collected candidate against the state load() was
last given for is_dirty(). apply() validates the candidate off the UI
thread exactly like the old dialog's Save did; a check failure is shown
inline on the page instead of in a modal box, so the sidebar can keep the
user on the page to fix it.
"""
from __future__ import annotations

import copy
import json
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core import routing as routing_mod
from ...core import routing_io, userfs, xraycheck
from ...i18n import ltr, tr
from ..help import help_html, set_help
from ..rule_editor import CollapsibleSection, RuleEditorDialog, default_rule
from ..theme import ACCENT, ERR, OK
from ..workers import Worker

CHOCOLATE4U_URL = (
    "https://raw.githubusercontent.com/Chocolate4U/Iran-v2ray-rules/main/v2rayN/template.json"
)

_RULE_COLS = ["", "Remarks", "Action", "Match"]
COL_ENABLED, COL_REMARKS, COL_ACTION, COL_MATCH = range(4)
_ACTION_COLORS = {"proxy": ACCENT, "direct": OK, "block": ERR}
_ACTION_LABELS = {"proxy": "Proxy", "direct": "Direct", "block": "Block"}

def _rule_column_help(section: int) -> str:
    if section == COL_ENABLED:
        return help_html(
            tr("Tick a rule to use it; untick to keep it without applying it."),
            tr("Pause the streaming rule for a week without losing it."),
            title=tr("On"))
    if section == COL_REMARKS:
        return help_html(
            tr("Your own note about what the rule is for."),
            tr("\"Banks stay direct\" beats a rule you can't remember."),
            title=tr("Remarks"))
    if section == COL_ACTION:
        return help_html(
            tr("What happens to traffic that matches: Proxy goes through the "
               "tunnel, Direct goes straight out, Block is dropped."),
            tr("Block a tracker, send your own country's sites direct."),
            title=tr("Action"))
    return help_html(
        tr("What the rule looks for: domains, addresses, ports and so on. Rules "
           "are checked from the top, and the first match wins."),
        tr("Put the specific rules above the broad ones."),
        title=tr("Match"))


_ROOT = QModelIndex()  # a fresh QModelIndex() per call is a ruff B008 default-arg smell


def _match_summary(rule: dict) -> str:
    dips = list(rule.get("domain") or []) + list(rule.get("ip") or [])
    parts = []
    if dips:
        extra = len(dips) - 1
        parts.append(f"{dips[0]} +{ltr(str(extra))}" if extra > 0 else dips[0])
    extras = []
    if rule.get("port") and rule.get("network"):
        extras.append(tr("port {port}/{network}",
                         port=ltr(str(rule["port"])), network=rule["network"]))
    elif rule.get("port"):
        extras.append(tr("port {port}", port=ltr(str(rule["port"]))))
    elif rule.get("network"):
        extras.append(rule["network"])
    if rule.get("protocol"):
        extras.append(",".join(rule["protocol"]))
    if rule.get("process"):
        extras.append(tr("{n} process(es)", n=len(rule["process"])))
    if extras:
        parts.append(" ".join(extras))
    return " · ".join(parts) if parts else tr("(matches everything)")


def _lan_direct_rule() -> dict:
    r = default_rule()
    r.update(remarks="LAN direct", outbound="direct",
             domain=["geosite:private"], ip=["geoip:private"])
    return r


def _has_lan_direct(rules: list[dict]) -> bool:
    return any(r.get("outbound") == "direct"
               and "geosite:private" in (r.get("domain") or [])
               and "geoip:private" in (r.get("ip") or [])
               for r in rules)


def _ensure_lan_direct(rules: list[dict]) -> list[dict]:
    return rules if _has_lan_direct(rules) else [_lan_direct_rule(), *rules]


def _like_simple_rules(cfg: dict) -> list[dict]:
    """Today's Simple-mode choices, turned into editable rules."""
    def rule(**kw) -> dict:
        r = default_rule()
        r.update(kw)
        return r

    rules = []
    if cfg.get("block_ads", True):
        rules.append(rule(remarks="Block ads & trackers", outbound="block",
                          domain=["geosite:category-ads-all"]))
    if cfg.get("direct_private", True):
        rules.append(_lan_direct_rule())
    for country, key, label in (("iran", "direct_iran", "Iran direct"),
                                 ("russia", "direct_russia", "Russia direct"),
                                 ("china", "direct_china", "China direct")):
        if cfg.get(key):
            domains, ips = routing_mod.COUNTRY_RULES[country]
            rules.append(rule(remarks=label, outbound="direct",
                              domain=list(domains), ip=list(ips)))
    if cfg.get("bypass_domains"):
        rules.append(rule(remarks="Custom bypass domains", outbound="direct",
                          domain=[routing_mod._norm_domain(d) for d in cfg["bypass_domains"]]))
    if cfg.get("bypass_ips"):
        rules.append(rule(remarks="Custom bypass IPs", outbound="direct",
                          ip=list(cfg["bypass_ips"])))
    if cfg.get("proxy_domains"):
        rules.append(rule(remarks="Force through tunnel", outbound="proxy",
                          domain=[routing_mod._norm_domain(d) for d in cfg["proxy_domains"]]))
    return rules


class RuleTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rules: list[dict] = []

    def set_rules(self, rules: list[dict]) -> None:
        self.beginResetModel()
        self._rules = rules
        self.endResetModel()

    def rule_at(self, row: int) -> dict | None:
        return self._rules[row] if 0 <= row < len(self._rules) else None

    def add(self, rule: dict) -> int:
        row = len(self._rules)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rules.append(rule)
        self.endInsertRows()
        return row

    def replace(self, row: int, rule: dict) -> None:
        self._rules[row] = rule
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(_RULE_COLS) - 1))

    def remove(self, row: int) -> None:
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._rules[row]
        self.endRemoveRows()

    def move(self, row: int, delta: int) -> int | None:
        new_row = row + delta
        if not (0 <= row < len(self._rules) and 0 <= new_row < len(self._rules)):
            return None
        self._rules[row], self._rules[new_row] = self._rules[new_row], self._rules[row]
        lo, hi = sorted((row, new_row))
        self.dataChanged.emit(self.index(lo, 0), self.index(hi, len(_RULE_COLS) - 1))
        return new_row

    def rowCount(self, parent=_ROOT) -> int:
        return 0 if parent.isValid() else len(self._rules)

    def columnCount(self, parent=_ROOT) -> int:
        return 0 if parent.isValid() else len(_RULE_COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return tr(_RULE_COLS[section])
        if orientation == Qt.Horizontal and role == Qt.ToolTipRole:
            return _rule_column_help(section)
        return None

    def flags(self, index):
        base = super().flags(index)
        if index.column() == COL_ENABLED:
            return base | Qt.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        rule = self._rules[index.row()]
        col = index.column()
        if role == Qt.CheckStateRole and col == COL_ENABLED:
            return Qt.Checked if rule.get("enabled", True) else Qt.Unchecked
        if role == Qt.DisplayRole:
            if col == COL_REMARKS:
                return rule.get("remarks") or tr("(no remarks)")
            if col == COL_ACTION:
                return tr(_ACTION_LABELS.get(rule.get("outbound", "proxy"), "Proxy"))
            if col == COL_MATCH:
                return _match_summary(rule)
            return None
        if role == Qt.ForegroundRole and col == COL_ACTION:
            return QColor(_ACTION_COLORS.get(rule.get("outbound", "proxy"), ACCENT))
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and index.column() == COL_ENABLED:
            self._rules[index.row()]["enabled"] = value == Qt.Checked
            self.dataChanged.emit(index, index)
            return True
        return False


class RoutingPage(QWidget):
    """The Routing editor as a page: dirty-tracking, revert, off-thread apply.

    Signals:
        dirtyChanged(bool): emitted whenever a field differs from the state
            load() was last given (and when it stops differing).
        applied(object): the candidate routing dict, after apply()'s
            validation succeeded off the UI thread.
        applyFinished(bool): True when apply() applied the page, False when
            a validation failure left it dirty -- the sidebar uses this to
            know an async apply has settled in either direction.
    """
    dirtyChanged = Signal(bool)
    applied = Signal(object)
    applyFinished = Signal(bool)

    def __init__(self, routing_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._routing = dict(routing_cfg)
        self._sets: list[dict] = copy.deepcopy(self._routing.get("sets") or [])
        self._busy = False
        self._dirty = False
        self._loading = True  # construction populates widgets; see @end
        self.pool = QThreadPool.globalInstance()
        self._workers: set = set()

        layout = QVBoxLayout(self)

        mode_row = QHBoxLayout()
        active_label = QLabel(tr("Active routing:"))
        active_label.setWordWrap(True)
        mode_row.addWidget(active_label)
        self.mode_combo = QComboBox()
        mode_help = (
            tr("Which rules are in charge: Simple, or one of your own rule sets. "
               "It's the same choice as the Routing button in the toolbar."),
            tr("Keep a \"Work\" set for office days and flip back to Simple at home."))
        set_help(self.mode_combo, *mode_help)
        set_help(active_label, *mode_help)
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_simple_tab(routing_cfg), tr("Simple"))
        self.tabs.addTab(self._build_sets_tab(), tr("Rule sets"))
        self.tabs.setTabToolTip(0, help_html(
            tr("A few easy switches for the usual cases."),
            tr("Most people never need more than this tab.")))
        self.tabs.setTabToolTip(1, help_html(
            tr("Build your own sets of rules, one rule at a time."),
            tr("A set for streaming nights, another for work.")))
        layout.addWidget(self.tabs, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_revert = QPushButton(tr("Revert"))
        self.btn_revert.clicked.connect(self.revert)
        self.btn_revert.setEnabled(False)
        set_help(self.btn_revert,
                 tr("Throws away your unsaved edits and goes back to the saved routing."),
                 tr("Changed your mind halfway through? Revert and start clean."))
        self.btn_apply = QPushButton(tr("Apply"))
        self.btn_apply.clicked.connect(self.apply)
        self.btn_apply.setEnabled(False)
        set_help(self.btn_apply,
                 tr("Saves your routing changes. If you are connected, reconnect "
                    "afterwards to use them."),
                 tr("Edit as much as you like; nothing changes until you press this."))
        bottom.addWidget(self.btn_revert)
        bottom.addWidget(self.btn_apply)
        layout.addLayout(bottom)

        self._mark_widgets_dirty()
        self._refresh_sets_list()
        self._refresh_mode_combo(keep_mode=self._routing.get("mode", "simple"))
        self._loading = False
        self._loaded = self._candidate()
        self._update_buttons()
        self._set_dirty(False)

    def _mark_widgets_dirty(self) -> None:
        """Connect every field to the dirty tracker. Programmatic fills fire
        these too, but _candidate() still equals _loaded then, so no signal
        is emitted unless the value genuinely differs. set_name only reacts
        to textEdited (user edits, not programmatic setText)."""
        self.mode_combo.currentIndexChanged.connect(lambda _i: self._maybe_notify_dirty())
        for cb in (self.cb_low, self.cb_ads, self.cb_private,
                   self.cb_iran, self.cb_russia, self.cb_china):
            cb.toggled.connect(lambda _c: self._maybe_notify_dirty())
        for w in (self.domains, self.ips, self.proxy):
            w.textChanged.connect(lambda *_: self._maybe_notify_dirty())
        self.set_name.textEdited.connect(lambda _t: self._on_name_edited())
        self.domain_strategy_combo.currentIndexChanged.connect(
            lambda _i: self._on_domain_strategy_changed())
        self.rule_model.dataChanged.connect(lambda *_: self._maybe_notify_dirty())
        self.rule_model.rowsInserted.connect(lambda *_: self._maybe_notify_dirty())
        self.rule_model.rowsRemoved.connect(lambda *_: self._maybe_notify_dirty())
        self.rule_model.layoutChanged.connect(lambda *_: self._maybe_notify_dirty())

    # -- Simple tab (unchanged content, in its own method) -----------------
    def _build_simple_tab(self, routing: dict) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        toggles = QGroupBox(tr("Bypass the tunnel (go direct)"))
        tg = QGridLayout(toggles)
        self.cb_low = QCheckBox(
            tr("Low usage — bypass macOS update/telemetry chatter") if sys.platform == "darwin"
            else tr("Low usage — bypass Windows telemetry/update chatter"))
        self.cb_ads = QCheckBox(tr("Block ads && trackers"))
        self.cb_private = QCheckBox(tr("Local network / private IPs direct"))
        self.cb_iran = QCheckBox(tr("Iran sites && IPs direct"))
        self.cb_russia = QCheckBox(tr("Russia sites && IPs direct"))
        self.cb_china = QCheckBox(tr("China sites && IPs direct"))
        set_help(self.cb_low,
                 tr("Lets your computer's update and background-report traffic skip "
                    "the tunnel, so it stops using up the server's data. Those "
                    "downloads use your normal internet instead."),
                 tr("On a server with a monthly data cap, stop Windows updates from "
                    "eating your gigabytes."))
        set_help(self.cb_ads,
                 tr("Blocks known ad and tracker domains, so they never load."),
                 tr("Fewer banners, and pages feel lighter."))
        set_help(self.cb_private,
                 tr("Keeps addresses on your own network, like 192.168.x.x, out of "
                    "the tunnel."),
                 tr("Your printer and home router stay reachable while you're connected."))
        set_help(self.cb_iran,
                 tr("Iranian websites and IP addresses connect directly instead of "
                    "through the tunnel."),
                 tr("Your bank's site loads as usual while everything else is tunnelled."))
        set_help(self.cb_russia,
                 tr("Russian websites and IP addresses connect directly instead of "
                    "through the tunnel."),
                 tr("Local delivery and banking apps keep working like they always did."))
        set_help(self.cb_china,
                 tr("Chinese websites and IP addresses connect directly instead of "
                    "through the tunnel."),
                 tr("Local video apps keep loading at full speed."))
        boxes = (self.cb_low, self.cb_ads, self.cb_private,
                 self.cb_iran, self.cb_russia, self.cb_china)
        for i, cb in enumerate(boxes):
            tg.addWidget(cb, i // 2, i % 2)
        layout.addWidget(toggles)

        bypass_label = QLabel(tr("Bypass domains (one per line — direct):"))
        bypass_label.setWordWrap(True)
        layout.addWidget(bypass_label)
        self.domains = QPlainTextEdit()
        self.domains.setPlaceholderText("example.com\ngeosite:google")
        self.domains.setLayoutDirection(Qt.LeftToRight)
        domains_help = (
            tr("Websites that skip the tunnel, one per line. A plain name like "
               "example.com also covers its subdomains; groups such as geosite:google "
               "work too."),
            tr("Add your university's site so its library login sees your real address."))
        set_help(self.domains, *domains_help)
        set_help(bypass_label, *domains_help)
        layout.addWidget(self.domains)

        ips_label = QLabel(tr("Bypass IPs / CIDRs (one per line — direct):"))
        ips_label.setWordWrap(True)
        layout.addWidget(ips_label)
        self.ips = QPlainTextEdit()
        self.ips.setPlaceholderText("10.0.0.0/8\ngeoip:ir")
        self.ips.setLayoutDirection(Qt.LeftToRight)
        ips_help = (
            tr("Addresses or ranges that skip the tunnel, one per line. 10.0.0.0/8 "
               "covers a whole range at once."),
            tr("Add your NAS's range so file copies don't crawl through a server "
               "abroad."))
        set_help(self.ips, *ips_help)
        set_help(ips_label, *ips_help)
        layout.addWidget(self.ips)

        proxy_label = QLabel(tr("Force through tunnel (one per line — proxy):"))
        proxy_label.setWordWrap(True)
        layout.addWidget(proxy_label)
        self.proxy = QPlainTextEdit()
        self.proxy.setLayoutDirection(Qt.LeftToRight)
        proxy_help = (
            tr("Websites to send through the tunnel, one per line. Anything a direct "
               "rule above also catches still goes direct."),
            tr("List streaming.example.com here to spell out that it should always "
               "use the tunnel."))
        set_help(self.proxy, *proxy_help)
        set_help(proxy_label, *proxy_help)
        layout.addWidget(self.proxy)

        self._populate_simple(routing)
        return w

    def _populate_simple(self, routing: dict) -> None:
        self.cb_low.setChecked(routing.get("low_usage", False))
        self.cb_ads.setChecked(routing.get("block_ads", True))
        self.cb_private.setChecked(routing.get("direct_private", True))
        self.cb_iran.setChecked(routing.get("direct_iran", True))
        self.cb_russia.setChecked(routing.get("direct_russia", False))
        self.cb_china.setChecked(routing.get("direct_china", False))
        self.domains.setPlainText("\n".join(routing.get("bypass_domains", [])))
        self.ips.setPlainText("\n".join(routing.get("bypass_ips", [])))
        self.proxy.setPlainText("\n".join(routing.get("proxy_domains", [])))

    @staticmethod
    def _lines(widget: QPlainTextEdit) -> list[str]:
        return [ln.strip() for ln in widget.toPlainText().splitlines() if ln.strip()]

    # -- Rule sets tab -------------------------------------------------------
    def _build_sets_tab(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)

        left = QVBoxLayout()
        self.sets_list = QListWidget()
        set_help(self.sets_list,
                 tr("Your rule sets. Click one to edit it; the active one is chosen "
                    "at the top of the page."),
                 tr("Keep one set per situation and switch with a click."))
        self.sets_list.currentRowChanged.connect(self._on_set_selected)
        left.addWidget(self.sets_list, 1)

        set_btns = QHBoxLayout()
        self.btn_add_set = QToolButton()
        self.btn_add_set.setText(tr("Add"))
        self.btn_add_set.setPopupMode(QToolButton.InstantPopup)
        add_menu = QMenu(self.btn_add_set)
        set_help(add_menu.addAction(tr("Empty"), lambda: self._add_set("empty")),
                 tr("A blank set; you add every rule yourself."),
                 tr("Start from scratch when you know exactly what you want."))
        set_help(add_menu.addAction(tr("Global"), lambda: self._add_set("global")),
                 tr("Sends everything through the tunnel, except your own local network."),
                 tr("When you want no exceptions at all."))
        set_help(add_menu.addAction(tr("Like Simple"), lambda: self._add_set("like_simple")),
                 tr("Starts with the same rules the Simple switches make right now."),
                 tr("Begin from what you have, then add a few special cases."))
        set_help(add_menu.addAction(tr("Chocolate4U Iran rules"),
                                    lambda: self._add_set("chocolate4u")),
                 tr("Downloads a ready-made rule set for Iran from the Chocolate4U "
                    "project. Needs an internet connection."),
                 tr("Iranian sites go direct without you writing a single rule."))
        add_menu.setToolTipsVisible(True)
        self.btn_add_set.setMenu(add_menu)
        set_help(self.btn_add_set,
                 tr("Creates a new rule set from a template."),
                 tr("Make a \"Movie night\" set in a few clicks."))
        btn_dup = QPushButton(tr("Duplicate"))
        btn_dup.clicked.connect(self._duplicate_set)
        set_help(btn_dup,
                 tr("Makes a copy of the selected set."),
                 tr("Try risky changes on a copy and keep the original safe."))
        btn_del = QPushButton(tr("Delete"))
        btn_del.clicked.connect(self._delete_set)
        set_help(btn_del,
                 tr("Removes the selected rule set."),
                 tr("Clear out the sets you stopped using."))
        for b in (self.btn_add_set, btn_dup, btn_del):
            set_btns.addWidget(b)
        left.addLayout(set_btns)

        io_btns = QHBoxLayout()
        btn_import = QToolButton()
        btn_import.setText(tr("Import"))
        btn_import.setPopupMode(QToolButton.InstantPopup)
        import_menu = QMenu(btn_import)
        set_help(import_menu.addAction(tr("From file…"), self._import_from_file),
                 tr("Loads rule sets from a file on your computer."),
                 tr("A friend sent you their rules as a file."))
        set_help(import_menu.addAction(tr("From clipboard"), self._import_from_clipboard),
                 tr("Loads rule sets from text you just copied."),
                 tr("Copy rules from a chat message, then import them."))
        set_help(import_menu.addAction(tr("From URL…"), self._import_from_url),
                 tr("Downloads rule sets from a web address."),
                 tr("A community list published online? Paste its link."))
        import_menu.setToolTipsVisible(True)
        btn_import.setMenu(import_menu)
        set_help(btn_import,
                 tr("Brings in rule sets made elsewhere."),
                 tr("Borrow a tested set instead of writing one."))
        btn_export = QToolButton()
        btn_export.setText(tr("Export"))
        btn_export.setPopupMode(QToolButton.InstantPopup)
        export_menu = QMenu(btn_export)
        set_help(export_menu.addAction(tr("To file…"),
                                       lambda: self._export_current(to_file=True)),
                 tr("Saves the selected set to a file."),
                 tr("Keep a backup before experimenting."))
        set_help(export_menu.addAction(tr("Copy to clipboard"),
                                       lambda: self._export_current(to_file=False)),
                 tr("Copies the selected set as text you can paste anywhere."),
                 tr("Send your rules to a friend in one message."))
        export_menu.setToolTipsVisible(True)
        btn_export.setMenu(export_menu)
        set_help(btn_export,
                 tr("Shares the selected rule set with others or saves a copy."),
                 tr("Give your setup to someone who just installed sushTun."))
        io_btns.addWidget(btn_import)
        io_btns.addWidget(btn_export)
        left.addLayout(io_btns)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(tr("Name:")))
        self.set_name = QLineEdit()
        set_help(self.set_name,
                 tr("The name this set has in the lists."),
                 tr("\"Work\" is easier to find than \"New set 3\"."))
        name_row.addWidget(self.set_name, 1)
        right.addLayout(name_row)

        self.rule_model = RuleTableModel()
        self.rules_table = QTableView()
        self.rules_table.setModel(self.rule_model)
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.horizontalHeader().setSectionResizeMode(COL_MATCH, QHeaderView.Stretch)
        for col in (COL_ENABLED, COL_REMARKS, COL_ACTION):
            self.rules_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeToContents)
        self.rules_table.doubleClicked.connect(lambda _i: self._edit_rule())
        set_help(self.rules_table,
                 tr("The rules of this set, checked from the top. The first one that "
                    "matches decides. Double-click a rule to edit it."),
                 tr("Block ads first, send local sites direct, tunnel the rest."))
        right.addWidget(self.rules_table, 1)

        rule_btns = QHBoxLayout()
        btn_add_rule = QPushButton(tr("Add"))
        btn_add_rule.clicked.connect(self._add_rule)
        btn_edit_rule = QPushButton(tr("Edit"))
        btn_edit_rule.clicked.connect(self._edit_rule)
        btn_del_rule = QPushButton(tr("Delete"))
        btn_del_rule.clicked.connect(self._delete_rule)
        set_help(btn_add_rule,
                 tr("Writes a new rule for this set."),
                 tr("Send a streaming site through the tunnel."))
        set_help(btn_edit_rule,
                 tr("Changes the selected rule."),
                 tr("Add one more domain to a rule you already made."))
        set_help(btn_del_rule,
                 tr("Removes the selected rule."),
                 tr("That rule that never mattered? Gone."))
        btn_up = QToolButton()
        btn_up.setText("↑")
        btn_up.setAccessibleName(tr("Move rule up"))
        set_help(btn_up,
                 tr("Moves the selected rule up. Higher rules are checked first."),
                 tr("Put \"block ads\" above \"allow everything\"."),
                 title=tr("Move rule up"))
        btn_up.clicked.connect(lambda: self._move_rule(-1))
        btn_down = QToolButton()
        btn_down.setText("↓")
        btn_down.setAccessibleName(tr("Move rule down"))
        set_help(btn_down,
                 tr("Moves the selected rule down. Lower rules are checked later."),
                 tr("Let a general rule wait until the special ones had their turn."),
                 title=tr("Move rule down"))
        btn_down.clicked.connect(lambda: self._move_rule(1))
        for b in (btn_add_rule, btn_edit_rule, btn_del_rule, btn_up, btn_down):
            rule_btns.addWidget(b)
        right.addLayout(rule_btns)

        adv = QWidget()
        adv_row = QHBoxLayout(adv)
        adv_row.setContentsMargins(0, 0, 0, 0)
        adv_row.addWidget(QLabel(tr("Domain strategy:")))
        self.domain_strategy_combo = QComboBox()
        domain_strategies = [(tr("Inherit"), "")] + [(s, s) for s in routing_mod.DOMAIN_STRATEGIES]
        for label, value in domain_strategies:
            self.domain_strategy_combo.addItem(label, value)
        adv_row.addWidget(self.domain_strategy_combo, 1)
        set_help(self.domain_strategy_combo,
                 tr("How domain names are matched against address rules. Inherit "
                    "uses the global choice; the others decide when a name is looked "
                    "up to get its IP."),
                 tr("Leave it on Inherit unless a rule with IP addresses misses its target."))
        adv_section = CollapsibleSection(tr("Advanced"), adv)
        set_help(adv_section.toggle,
                 tr("Shows the rarely needed options."),
                 tr("Skip it until a guide tells you otherwise."))
        right.addWidget(adv_section)

        row.addLayout(right, 2)
        self._set_right_enabled(False)
        return w

    # -- sets: list management -----------------------------------------
    def _current_set(self) -> dict | None:
        row = self.sets_list.currentRow()
        return self._sets[row] if 0 <= row < len(self._sets) else None

    def _set_right_enabled(self, enabled: bool) -> None:
        for w in (self.set_name, self.rules_table, self.domain_strategy_combo):
            w.setEnabled(enabled)

    def _refresh_sets_list(self, select_id: str | None = None, keep_mode: str | None = None) -> None:
        if select_id is None:
            current = self._current_set()
            select_id = current["id"] if current else None
        self.sets_list.blockSignals(True)
        self.sets_list.clear()
        for s in self._sets:
            item = QListWidgetItem(s.get("name") or tr("Unnamed"))
            item.setData(Qt.UserRole, s["id"])
            self.sets_list.addItem(item)
        self.sets_list.blockSignals(False)
        row = 0
        if select_id:
            for i in range(self.sets_list.count()):
                if self.sets_list.item(i).data(Qt.UserRole) == select_id:
                    row = i
                    break
        if self.sets_list.count():
            self.sets_list.setCurrentRow(row)
        else:
            self._on_set_selected(-1)
        self._refresh_mode_combo(keep_mode=keep_mode)

    def _on_set_selected(self, row: int) -> None:
        s = self._current_set()
        if s is None:
            self.set_name.setText("")
            self.rule_model.set_rules([])
            self.domain_strategy_combo.setCurrentIndex(0)
            self._set_right_enabled(False)
            return
        self.set_name.setText(s.get("name", ""))
        # `s.get("rules") or []` would hand the model a throwaway list when
        # rules is already [] (empty is falsy too), so Add/Delete/Move would
        # mutate that instead of the set actually stored in self._sets.
        rules = s.get("rules")
        if rules is None:
            rules = []
            s["rules"] = rules
        self.rule_model.set_rules(rules)
        idx = self.domain_strategy_combo.findData(s.get("domain_strategy", ""))
        self.domain_strategy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._set_right_enabled(True)

    def _on_name_edited(self) -> None:
        s = self._current_set()
        if s is None:
            return
        s["name"] = self.set_name.text().strip() or tr("Unnamed")
        item = self.sets_list.item(self.sets_list.currentRow())
        if item is not None:
            item.setText(s["name"])
        self._refresh_mode_combo()
        self._maybe_notify_dirty()

    def _on_domain_strategy_changed(self) -> None:
        s = self._current_set()
        if s is not None:
            s["domain_strategy"] = self.domain_strategy_combo.currentData()
            self._maybe_notify_dirty()

    def _unique_name(self, base: str) -> str:
        existing = {s.get("name") for s in self._sets}
        if base not in existing:
            return base
        n = 2
        while f"{base} ({n})" in existing:
            n += 1
        return f"{base} ({n})"

    def _add_set(self, kind: str) -> None:
        if kind == "chocolate4u":
            self._add_chocolate4u_set()
            return
        if kind == "empty":
            rules: list[dict] = []
            name = self._unique_name(tr("New set"))
        elif kind == "global":
            rules = _ensure_lan_direct([])
            name = self._unique_name("Global")
        elif kind == "like_simple":
            rules = _ensure_lan_direct(_like_simple_rules(self._routing))
            name = self._unique_name("Like Simple")
        else:
            return
        new_set = {"id": uuid.uuid4().hex, "name": name, "domain_strategy": "", "rules": rules}
        self._sets.append(new_set)
        self._refresh_sets_list(select_id=new_set["id"])
        self._maybe_notify_dirty()

    def _add_chocolate4u_set(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.status_label.setText(tr("Fetching Chocolate4U Iran rules…"))
        self._run_async(lambda: routing_io.import_url(CHOCOLATE4U_URL), self._on_chocolate4u_done)

    def _on_chocolate4u_done(self, result=None, error=None) -> None:
        self._set_busy(False)
        if error:
            self.status_label.setText("")
            QMessageBox.warning(self, tr("Import failed"), str(error))
            return
        sets, skipped = result
        if not sets:
            self.status_label.setText(tr("Nothing to import."))
            return
        first_id = sets[0]["id"]
        for s in sets:
            s["name"] = self._unique_name(s.get("name") or "Chocolate4U")
            s["rules"] = _ensure_lan_direct(s.get("rules") or [])
            self._sets.append(s)
        self._refresh_sets_list(select_id=first_id)
        self.status_label.setText(
            tr("Imported {n} set(s), skipped {skipped} rule(s).", n=len(sets), skipped=skipped))
        self._maybe_notify_dirty()

    def _duplicate_set(self) -> None:
        s = self._current_set()
        if s is None:
            return
        clone = copy.deepcopy(s)
        clone["id"] = uuid.uuid4().hex
        clone["name"] = self._unique_name(f"{s.get('name', 'Set')} copy")
        self._sets.append(clone)
        self._refresh_sets_list(select_id=clone["id"])
        self._maybe_notify_dirty()

    def _delete_set(self) -> None:
        row = self.sets_list.currentRow()
        if row < 0:
            return
        if QMessageBox.question(self, tr("Delete set"),
                                tr("Delete '{name}'?", name=self._sets[row].get("name"))
                                ) != QMessageBox.Yes:
            return
        del self._sets[row]
        self._refresh_sets_list()
        self._maybe_notify_dirty()

    # -- rules: table actions ---------------------------------------------
    def _add_rule(self) -> None:
        if self._current_set() is None:
            return
        dlg = RuleEditorDialog(None, self)
        if dlg.exec():
            self.rule_model.add(dlg.result_rule())
            self._maybe_notify_dirty()

    def _edit_rule(self) -> None:
        row = self.rules_table.currentIndex().row()
        rule = self.rule_model.rule_at(row)
        if rule is None:
            return
        dlg = RuleEditorDialog(rule, self)
        if dlg.exec():
            self.rule_model.replace(row, dlg.result_rule())
            self._maybe_notify_dirty()

    def _delete_rule(self) -> None:
        row = self.rules_table.currentIndex().row()
        if self.rule_model.rule_at(row) is not None:
            self.rule_model.remove(row)
            self._maybe_notify_dirty()

    def _move_rule(self, delta: int) -> None:
        row = self.rules_table.currentIndex().row()
        new_row = self.rule_model.move(row, delta)
        if new_row is not None:
            self.rules_table.selectRow(new_row)
            self._maybe_notify_dirty()

    # -- import / export ----------------------------------------------------
    def _apply_imported(self, sets: list[dict], skipped: int) -> None:
        if not sets:
            self.status_label.setText(tr("Nothing to import."))
            return
        for s in sets:
            s["name"] = self._unique_name(s.get("name") or "Imported")
            self._sets.append(s)
        self._refresh_sets_list(select_id=sets[0]["id"])
        self.status_label.setText(
            tr("Imported {n} set(s), skipped {skipped} rule(s).", n=len(sets), skipped=skipped))
        self._maybe_notify_dirty()

    def _import_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Import rule sets"), "", "JSON (*.json);;All files (*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, tr("Import failed"), str(exc))
            return
        sets, skipped = routing_io.import_rules(text)
        self._apply_imported(sets, skipped)

    def _import_from_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        sets, skipped = routing_io.import_rules(text)
        self._apply_imported(sets, skipped)

    def _import_from_url(self) -> None:
        url, ok = QInputDialog.getText(self, tr("Import from URL"), tr("URL:"))
        if not ok or not url.strip():
            return
        self._set_busy(True)
        self.status_label.setText(tr("Fetching {url}…", url=url.strip()))
        self._run_async(lambda: routing_io.import_url(url.strip()), self._on_url_import_done)

    def _on_url_import_done(self, result=None, error=None) -> None:
        self._set_busy(False)
        if error:
            self.status_label.setText("")
            QMessageBox.warning(self, tr("Import failed"), str(error))
            return
        sets, skipped = result
        self._apply_imported(sets, skipped)

    def _export_current(self, to_file: bool) -> None:
        s = self._current_set()
        if s is None:
            return
        data = routing_io.export_rules(s)
        text = json.dumps(data, indent=2, ensure_ascii=False)
        if not to_file:
            QApplication.clipboard().setText(text)
            self.status_label.setText(tr("Copied to clipboard."))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export rule set"), f"{s.get('name', 'rules')}.json", "JSON (*.json)")
        if not path:
            return
        try:
            userfs.save_for_user(Path(path), text.encode("utf-8"))
        except (OSError, userfs.UserFsError) as exc:
            QMessageBox.warning(self, tr("Export failed"), str(exc))

    # -- mode combo -----------------------------------------------------
    def _refresh_mode_combo(self, keep_mode: str | None = None) -> None:
        current = keep_mode if keep_mode is not None else self.mode_combo.currentData()
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        self.mode_combo.addItem(tr("Simple"), "simple")
        for s in self._sets:
            self.mode_combo.addItem(s.get("name") or tr("Unnamed"), s["id"])
        idx = self.mode_combo.findData(current)
        self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.mode_combo.blockSignals(False)

    # -- candidate / dirty state ------------------------------------------
    def _candidate(self) -> dict:
        """Everything the page holds right now, in the same flat shape
        settings["routing"] uses (the old dialog's _save candidate). Compared
        against _loaded for dirty tracking, and stored on successful apply."""
        return {
            "low_usage": self.cb_low.isChecked(),
            "block_ads": self.cb_ads.isChecked(),
            "direct_private": self.cb_private.isChecked(),
            "direct_iran": self.cb_iran.isChecked(),
            "direct_russia": self.cb_russia.isChecked(),
            "direct_china": self.cb_china.isChecked(),
            "bypass_domains": self._lines(self.domains),
            "bypass_ips": self._lines(self.ips),
            "proxy_domains": self._lines(self.proxy),
            "sets": copy.deepcopy(self._sets),
            "mode": self.mode_combo.currentData() or "simple",
        }

    def _maybe_notify_dirty(self) -> None:
        if self._loading:
            return
        dirty = self._candidate() != self._loaded
        if dirty != self._dirty:
            self._set_dirty(dirty)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self._update_buttons()
        self.dirtyChanged.emit(dirty)

    def is_dirty(self) -> bool:
        return self._dirty

    def result_routing(self) -> dict:
        """The committed routing dict -- settings["routing"]'s flat shape.
        Returns the live object (like the old dialog) so a caller that
        snapshots it earlier can detect later rewrites by identity."""
        return self._routing

    # -- load / revert -------------------------------------------------------
    def load(self, routing_cfg: dict) -> None:
        """Replace the page's content and re-baseline the dirtiness. Never
        emits dirtyChanged while populating: the baseline is snapshotted at
        the end, and equal fields then read as clean."""
        self._loading = True
        self._routing = dict(routing_cfg)
        self._sets = copy.deepcopy(self._routing.get("sets") or [])
        self._populate_simple(self._routing)
        self._refresh_sets_list(keep_mode=self._routing.get("mode", "simple"))
        self._loading = False
        self._loaded = self._candidate()
        self.status_label.clear()
        self._set_dirty(False)

    def revert(self) -> None:
        self.load(self._loaded)

    def expand_sections(self) -> None:
        """Lower any CollapsibleSections so a fresh sidebar view shows
        everything without a pointer hint."""
        for section in self.findChildren(CollapsibleSection):
            section.set_expanded(True)

    # -- apply ---------------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.tabs.setEnabled(not busy)
        self.btn_add_set.setEnabled(not busy)
        self._update_buttons()

    def _update_buttons(self) -> None:
        enable = self._dirty and not self._busy
        self.btn_apply.setEnabled(enable)
        self.btn_revert.setEnabled(enable)
        # Enter anywhere on the page triggers the default button; only keep
        # it on Apply while there is actually something to apply.
        self.btn_apply.setDefault(self._dirty)

    def apply(self) -> None:
        if self._busy:
            return
        candidate = self._candidate()
        self._set_busy(True)
        self.status_label.setText(tr("Validating…"))
        low_usage = candidate["low_usage"]
        sets = candidate["sets"]

        def work():
            # Always validate Simple too: a typo in Bypass domains or a
            # geoip category the current geo data lacks is exactly as capable
            # of stopping Xray from starting as a bad custom rule is.
            simple_rules = routing_mod.build_rules({**candidate, "mode": "simple"})
            err = xraycheck.check_rules(simple_rules)
            if err:
                return ("Simple", err)
            for s in sets:
                rules = routing_mod.build_rules(
                    {"mode": s["id"], "sets": sets, "low_usage": low_usage})
                err = xraycheck.check_rules(rules)
                if err:
                    return (s.get("name", "?"), err)
            return None

        def done(result=None, error=None):
            self._set_busy(False)
            if error:
                self.status_label.setText("")
                # A raw failure from the validation plumbing itself, not a
                # translated app message -- stays in English.
                QMessageBox.warning(self, tr("Validation failed"), str(error))
                self.applyFinished.emit(False)
                return
            if result:
                name, err = result
                label = tr("Simple") if name == "Simple" else f"'{name}'"
                # `err` is Xray's own raw parser output -- stays in English.
                self.status_label.setText(f"{label}: {err}")
                self.applyFinished.emit(False)
                return
            self.status_label.setText("")
            self._routing = candidate
            self._loading = True
            self._loaded = self._candidate()
            self._loading = False
            self._set_dirty(False)
            self._set_busy(False)
            self.applied.emit(dict(candidate))
            self.applyFinished.emit(True)

        self._run_async(work, done)

    def _run_async(self, fn, done) -> None:
        worker = Worker(fn)

        def finish(result=None, error=None):
            self._workers.discard(worker)
            done(result=result, error=error)

        worker.signals.finished.connect(lambda r: finish(result=r))
        worker.signals.error.connect(lambda e: finish(error=e))
        self._workers.add(worker)
        self.pool.start(worker)
