"""Bypass / routing editor: Simple mode (today's toggles, unchanged and the
default tab), and custom routing rule sets."""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QThreadPool
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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

from ..core import routing as routing_mod
from ..core import routing_io, xraycheck
from .rule_editor import CollapsibleSection, RuleEditorDialog, default_rule
from .theme import ACCENT, ERR, OK
from .workers import Worker

CHOCOLATE4U_URL = (
    "https://raw.githubusercontent.com/Chocolate4U/Iran-v2ray-rules/main/v2rayN/template.json"
)

_RULE_COLS = ["", "Remarks", "Action", "Match"]
COL_ENABLED, COL_REMARKS, COL_ACTION, COL_MATCH = range(4)
_ACTION_COLORS = {"proxy": ACCENT, "direct": OK, "block": ERR}
_ACTION_LABELS = {"proxy": "Proxy", "direct": "Direct", "block": "Block"}

_DOMAIN_STRATEGIES = [("Inherit", "")] + [(s, s) for s in routing_mod.DOMAIN_STRATEGIES]
_ROOT = QModelIndex()  # a fresh QModelIndex() per call is a ruff B008 default-arg smell


def _match_summary(rule: dict) -> str:
    dips = list(rule.get("domain") or []) + list(rule.get("ip") or [])
    parts = []
    if dips:
        extra = len(dips) - 1
        parts.append(f"{dips[0]} +{extra}" if extra > 0 else dips[0])
    extras = []
    if rule.get("port") and rule.get("network"):
        extras.append(f"port {rule['port']}/{rule['network']}")
    elif rule.get("port"):
        extras.append(f"port {rule['port']}")
    elif rule.get("network"):
        extras.append(rule["network"])
    if rule.get("protocol"):
        extras.append(",".join(rule["protocol"]))
    if rule.get("process"):
        extras.append(f"{len(rule['process'])} process(es)")
    if extras:
        parts.append(" ".join(extras))
    return " · ".join(parts) if parts else "(matches everything)"


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
            return _RULE_COLS[section]
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
                return rule.get("remarks") or "(no remarks)"
            if col == COL_ACTION:
                return _ACTION_LABELS.get(rule.get("outbound", "proxy"), "Proxy")
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


class RoutingDialog(QDialog):
    def __init__(self, routing_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bypass & routing")
        self.resize(820, 660)
        self._routing = dict(routing_cfg)
        self._sets: list[dict] = copy.deepcopy(self._routing.get("sets") or [])
        self._busy = False
        self.pool = QThreadPool.globalInstance()
        self._workers: set = set()

        layout = QVBoxLayout(self)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Active routing:"))
        self.mode_combo = QComboBox()
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_simple_tab(routing_cfg), "Simple")
        self.tabs.addTab(self._build_sets_tab(), "Rule sets")
        layout.addWidget(self.tabs, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.btn_save = buttons.button(QDialogButtonBox.Save)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_sets_list()
        self._refresh_mode_combo(keep_mode=self._routing.get("mode", "simple"))

    # -- Simple tab (unchanged content, in its own method) -----------------
    def _build_simple_tab(self, routing: dict) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        toggles = QGroupBox("Bypass the tunnel (go direct)")
        tg = QGridLayout(toggles)
        self.cb_low = QCheckBox("Low usage — bypass Windows telemetry/update chatter")
        self.cb_ads = QCheckBox("Block ads && trackers")
        self.cb_private = QCheckBox("Local network / private IPs direct")
        self.cb_iran = QCheckBox("Iran sites && IPs direct")
        self.cb_russia = QCheckBox("Russia sites && IPs direct")
        self.cb_china = QCheckBox("China sites && IPs direct")
        self.cb_low.setChecked(routing.get("low_usage", False))
        self.cb_ads.setChecked(routing.get("block_ads", True))
        self.cb_private.setChecked(routing.get("direct_private", True))
        self.cb_iran.setChecked(routing.get("direct_iran", True))
        self.cb_russia.setChecked(routing.get("direct_russia", False))
        self.cb_china.setChecked(routing.get("direct_china", False))
        boxes = (self.cb_low, self.cb_ads, self.cb_private,
                 self.cb_iran, self.cb_russia, self.cb_china)
        for i, cb in enumerate(boxes):
            tg.addWidget(cb, i // 2, i % 2)
        layout.addWidget(toggles)

        layout.addWidget(QLabel("Bypass domains (one per line — direct):"))
        self.domains = QPlainTextEdit("\n".join(routing.get("bypass_domains", [])))
        self.domains.setPlaceholderText("example.com\ngeosite:google")
        layout.addWidget(self.domains)

        layout.addWidget(QLabel("Bypass IPs / CIDRs (one per line — direct):"))
        self.ips = QPlainTextEdit("\n".join(routing.get("bypass_ips", [])))
        self.ips.setPlaceholderText("10.0.0.0/8\ngeoip:ir")
        layout.addWidget(self.ips)

        layout.addWidget(QLabel("Force through tunnel (one per line — proxy):"))
        self.proxy = QPlainTextEdit("\n".join(routing.get("proxy_domains", [])))
        layout.addWidget(self.proxy)
        return w

    @staticmethod
    def _lines(widget: QPlainTextEdit) -> list[str]:
        return [ln.strip() for ln in widget.toPlainText().splitlines() if ln.strip()]

    # -- Rule sets tab -------------------------------------------------------
    def _build_sets_tab(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)

        left = QVBoxLayout()
        self.sets_list = QListWidget()
        self.sets_list.currentRowChanged.connect(self._on_set_selected)
        left.addWidget(self.sets_list, 1)

        set_btns = QHBoxLayout()
        self.btn_add_set = QToolButton()
        self.btn_add_set.setText("Add")
        self.btn_add_set.setPopupMode(QToolButton.InstantPopup)
        add_menu = QMenu(self.btn_add_set)
        add_menu.addAction("Empty", lambda: self._add_set("empty"))
        add_menu.addAction("Global", lambda: self._add_set("global"))
        add_menu.addAction("Like Simple", lambda: self._add_set("like_simple"))
        add_menu.addAction("Chocolate4U Iran rules", lambda: self._add_set("chocolate4u"))
        self.btn_add_set.setMenu(add_menu)
        btn_dup = QPushButton("Duplicate")
        btn_dup.clicked.connect(self._duplicate_set)
        btn_del = QPushButton("Delete")
        btn_del.clicked.connect(self._delete_set)
        for b in (self.btn_add_set, btn_dup, btn_del):
            set_btns.addWidget(b)
        left.addLayout(set_btns)

        io_btns = QHBoxLayout()
        btn_import = QToolButton()
        btn_import.setText("Import")
        btn_import.setPopupMode(QToolButton.InstantPopup)
        import_menu = QMenu(btn_import)
        import_menu.addAction("From file…", self._import_from_file)
        import_menu.addAction("From clipboard", self._import_from_clipboard)
        import_menu.addAction("From URL…", self._import_from_url)
        btn_import.setMenu(import_menu)
        btn_export = QToolButton()
        btn_export.setText("Export")
        btn_export.setPopupMode(QToolButton.InstantPopup)
        export_menu = QMenu(btn_export)
        export_menu.addAction("To file…", lambda: self._export_current(to_file=True))
        export_menu.addAction("Copy to clipboard", lambda: self._export_current(to_file=False))
        btn_export.setMenu(export_menu)
        io_btns.addWidget(btn_import)
        io_btns.addWidget(btn_export)
        left.addLayout(io_btns)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.set_name = QLineEdit()
        self.set_name.textEdited.connect(self._on_name_edited)
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
        right.addWidget(self.rules_table, 1)

        rule_btns = QHBoxLayout()
        btn_add_rule = QPushButton("Add")
        btn_add_rule.clicked.connect(self._add_rule)
        btn_edit_rule = QPushButton("Edit")
        btn_edit_rule.clicked.connect(self._edit_rule)
        btn_del_rule = QPushButton("Delete")
        btn_del_rule.clicked.connect(self._delete_rule)
        btn_up = QPushButton("↑")
        btn_up.clicked.connect(lambda: self._move_rule(-1))
        btn_down = QPushButton("↓")
        btn_down.clicked.connect(lambda: self._move_rule(1))
        for b in (btn_add_rule, btn_edit_rule, btn_del_rule, btn_up, btn_down):
            rule_btns.addWidget(b)
        right.addLayout(rule_btns)

        adv = QWidget()
        adv_row = QHBoxLayout(adv)
        adv_row.setContentsMargins(0, 0, 0, 0)
        adv_row.addWidget(QLabel("Domain strategy:"))
        self.domain_strategy_combo = QComboBox()
        for label, value in _DOMAIN_STRATEGIES:
            self.domain_strategy_combo.addItem(label, value)
        self.domain_strategy_combo.currentIndexChanged.connect(self._on_domain_strategy_changed)
        adv_row.addWidget(self.domain_strategy_combo, 1)
        right.addWidget(CollapsibleSection("Advanced", adv))

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

    def _refresh_sets_list(self, select_id: str | None = None) -> None:
        if select_id is None:
            current = self._current_set()
            select_id = current["id"] if current else None
        self.sets_list.blockSignals(True)
        self.sets_list.clear()
        for s in self._sets:
            item = QListWidgetItem(s.get("name") or "Unnamed")
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
        self._refresh_mode_combo()

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

    def _on_name_edited(self, text: str) -> None:
        s = self._current_set()
        if s is not None:
            s["name"] = text
            item = self.sets_list.item(self.sets_list.currentRow())
            if item is not None:
                item.setText(text or "Unnamed")
            self._refresh_mode_combo()

    def _on_domain_strategy_changed(self, _index: int) -> None:
        s = self._current_set()
        if s is not None:
            s["domain_strategy"] = self.domain_strategy_combo.currentData()

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
            name = self._unique_name("New set")
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

    def _add_chocolate4u_set(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.status_label.setText("Fetching Chocolate4U Iran rules…")
        self._run_async(lambda: routing_io.import_url(CHOCOLATE4U_URL), self._on_chocolate4u_done)

    def _on_chocolate4u_done(self, result=None, error=None) -> None:
        self._set_busy(False)
        if error:
            self.status_label.setText("")
            QMessageBox.warning(self, "Import failed", str(error))
            return
        sets, skipped = result
        if not sets:
            self.status_label.setText("Nothing to import.")
            return
        first_id = sets[0]["id"]
        for s in sets:
            s["name"] = self._unique_name(s.get("name") or "Chocolate4U")
            s["rules"] = _ensure_lan_direct(s.get("rules") or [])
            self._sets.append(s)
        self._refresh_sets_list(select_id=first_id)
        self.status_label.setText(f"Imported {len(sets)} set(s), skipped {skipped} rule(s).")

    def _duplicate_set(self) -> None:
        s = self._current_set()
        if s is None:
            return
        clone = copy.deepcopy(s)
        clone["id"] = uuid.uuid4().hex
        clone["name"] = self._unique_name(f"{s.get('name', 'Set')} copy")
        self._sets.append(clone)
        self._refresh_sets_list(select_id=clone["id"])

    def _delete_set(self) -> None:
        row = self.sets_list.currentRow()
        if row < 0:
            return
        if QMessageBox.question(self, "Delete set",
                                f"Delete '{self._sets[row].get('name')}'?") != QMessageBox.Yes:
            return
        del self._sets[row]
        self._refresh_sets_list()

    # -- rules: table actions ---------------------------------------------
    def _add_rule(self) -> None:
        if self._current_set() is None:
            return
        dlg = RuleEditorDialog(None, self)
        if dlg.exec():
            self.rule_model.add(dlg.result_rule())

    def _edit_rule(self) -> None:
        row = self.rules_table.currentIndex().row()
        rule = self.rule_model.rule_at(row)
        if rule is None:
            return
        dlg = RuleEditorDialog(rule, self)
        if dlg.exec():
            self.rule_model.replace(row, dlg.result_rule())

    def _delete_rule(self) -> None:
        row = self.rules_table.currentIndex().row()
        if self.rule_model.rule_at(row) is not None:
            self.rule_model.remove(row)

    def _move_rule(self, delta: int) -> None:
        row = self.rules_table.currentIndex().row()
        new_row = self.rule_model.move(row, delta)
        if new_row is not None:
            self.rules_table.selectRow(new_row)

    # -- import / export ----------------------------------------------------
    def _apply_imported(self, sets: list[dict], skipped: int) -> None:
        if not sets:
            self.status_label.setText("Nothing to import.")
            return
        for s in sets:
            s["name"] = self._unique_name(s.get("name") or "Imported")
            self._sets.append(s)
        self._refresh_sets_list(select_id=sets[0]["id"])
        self.status_label.setText(f"Imported {len(sets)} set(s), skipped {skipped} rule(s).")

    def _import_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import rule sets", "", "JSON (*.json);;All files (*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
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
        url, ok = QInputDialog.getText(self, "Import from URL", "URL:")
        if not ok or not url.strip():
            return
        self._set_busy(True)
        self.status_label.setText(f"Fetching {url.strip()}…")
        self._run_async(lambda: routing_io.import_url(url.strip()), self._on_url_import_done)

    def _on_url_import_done(self, result=None, error=None) -> None:
        self._set_busy(False)
        if error:
            self.status_label.setText("")
            QMessageBox.warning(self, "Import failed", str(error))
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
            self.status_label.setText("Copied to clipboard.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export rule set", f"{s.get('name', 'rules')}.json", "JSON (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    # -- mode combo -----------------------------------------------------
    def _refresh_mode_combo(self, keep_mode: str | None = None) -> None:
        current = keep_mode if keep_mode is not None else self.mode_combo.currentData()
        self.mode_combo.blockSignals(True)
        self.mode_combo.clear()
        self.mode_combo.addItem("Simple", "simple")
        for s in self._sets:
            self.mode_combo.addItem(s.get("name") or "Unnamed", s["id"])
        idx = self.mode_combo.findData(current)
        self.mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.mode_combo.blockSignals(False)

    # -- save / validate off the UI thread -----------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_save.setEnabled(not busy)
        self.btn_add_set.setEnabled(not busy)

    def _run_async(self, fn, done) -> None:
        worker = Worker(fn)

        def finish(result=None, error=None):
            self._workers.discard(worker)
            done(result=result, error=error)

        worker.signals.finished.connect(lambda r: finish(result=r))
        worker.signals.error.connect(lambda e: finish(error=e))
        self._workers.add(worker)
        self.pool.start(worker)

    def _save(self) -> None:
        if self._busy:
            return
        candidate = dict(self._routing)
        candidate.update(
            low_usage=self.cb_low.isChecked(),
            block_ads=self.cb_ads.isChecked(),
            direct_private=self.cb_private.isChecked(),
            direct_iran=self.cb_iran.isChecked(),
            direct_russia=self.cb_russia.isChecked(),
            direct_china=self.cb_china.isChecked(),
            bypass_domains=self._lines(self.domains),
            bypass_ips=self._lines(self.ips),
            proxy_domains=self._lines(self.proxy),
            sets=copy.deepcopy(self._sets),
            mode=self.mode_combo.currentData() or "simple",
        )

        # Always validate, Simple included: a typo in Bypass domains or a
        # geoip category the current geo data lacks is exactly as capable
        # of stopping Xray from starting as a bad custom rule is.
        self._set_busy(True)
        self.status_label.setText("Validating…")
        low_usage = candidate["low_usage"]
        sets = candidate["sets"]

        def work():
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
                QMessageBox.warning(self, "Validation failed", str(error))
                return
            if result:
                name, err = result
                label = name if name == "Simple" else f"'{name}'"
                self.status_label.setText("")
                QMessageBox.warning(self, "Routing invalid", f"{label}: {err}")
                return
            self.status_label.setText("")
            self._routing = candidate
            self.accept()

        self._run_async(work, done)

    def result_routing(self) -> dict:
        return self._routing
