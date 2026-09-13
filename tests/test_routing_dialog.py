"""Routing dialog: Simple/Rule sets tabs, rule sets, rule editor, save."""
from __future__ import annotations

import json
import os
import time

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

import xrayui.ui.routing_dialog as rd  # noqa: E402
from xrayui.core.settings import DEFAULTS  # noqa: E402
from xrayui.ui.rule_editor import RuleEditorDialog, default_rule  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dlg(qapp):
    d = rd.RoutingDialog(DEFAULTS["routing"])
    yield d
    d.close()


def _pump(condition, timeout=5.0) -> None:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


# -- tabs -----------------------------------------------------------------
def test_tabs_exist_and_simple_is_default(dlg):
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == ["Simple", "Rule sets"]
    assert dlg.tabs.currentIndex() == 0


# -- presets ----------------------------------------------------------------
def test_add_preset_set(dlg):
    dlg._add_set("global")
    assert [s["name"] for s in dlg._sets] == ["Global"]
    assert [dlg.mode_combo.itemText(i) for i in range(dlg.mode_combo.count())] == \
        ["Simple", "Global"]
    rules = dlg._sets[0]["rules"]
    assert rules[0]["outbound"] == "direct"
    assert rules[0]["domain"] == ["geosite:private"]
    assert rules[0]["ip"] == ["geoip:private"]


def test_like_simple_preset_reproduces_todays_choices(dlg):
    dlg._add_set("like_simple")
    remarks = [r["remarks"] for r in dlg._sets[0]["rules"]]
    assert "Block ads & trackers" in remarks  # DEFAULTS["routing"]["block_ads"] is True
    assert "LAN direct" in remarks  # direct_private is True
    assert "Iran direct" in remarks  # direct_iran is True


# -- rule add/edit/move/delete ------------------------------------------
def test_add_edit_move_delete_rule(dlg):
    dlg._add_set("empty")
    r1 = default_rule()
    r1.update(remarks="r1", domain=["a.com"])
    r2 = default_rule()
    r2.update(remarks="r2", domain=["b.com"])
    dlg.rule_model.add(r1)
    dlg.rule_model.add(r2)
    assert [r["remarks"] for r in dlg.rule_model._rules] == ["r1", "r2"]

    dlg.rules_table.selectRow(0)
    dlg._move_rule(1)
    assert [r["remarks"] for r in dlg.rule_model._rules] == ["r2", "r1"]

    dlg.rules_table.selectRow(0)
    edited = dict(r2)
    edited["remarks"] = "r2-edited"
    dlg.rule_model.replace(0, edited)
    assert dlg.rule_model._rules[0]["remarks"] == "r2-edited"

    dlg.rules_table.selectRow(1)
    dlg._delete_rule()
    assert [r["remarks"] for r in dlg.rule_model._rules] == ["r2-edited"]


# -- import / export ----------------------------------------------------
def test_import_from_clipboard_reports_skipped_count(dlg):
    QApplication.clipboard().setText(json.dumps([
        {"remarks": "ok", "outboundTag": "direct", "domain": ["example.com"]},
        {"remarks": "bad", "outboundTag": "balancer:x", "domain": ["y.com"]},
    ]))
    dlg._import_from_clipboard()
    assert "Imported 1 set(s), skipped 1 rule(s)." == dlg.status_label.text()
    assert len(dlg._sets) == 1
    assert len(dlg._sets[0]["rules"]) == 1


def test_export_then_import_round_trips(dlg):
    dlg._add_set("empty")
    r = default_rule()
    r.update(remarks="x", outbound="block", domain=["geosite:ads"])
    dlg.rule_model.add(r)

    dlg._export_current(to_file=False)
    exported_text = QApplication.clipboard().text()
    assert dlg.status_label.text() == "Copied to clipboard."

    from xrayui.core import routing_io
    sets, skipped = routing_io.import_rules(exported_text)
    assert skipped == 0
    assert sets[0]["rules"][0]["domain"] == ["geosite:ads"]
    assert sets[0]["rules"][0]["outbound"] == "block"


# -- rule editor -----------------------------------------------------------
def test_rule_editor_refuses_an_empty_rule(qapp, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a[2])), raising=False)
    editor = RuleEditorDialog(None)
    editor._save()
    assert editor.result() != QDialog.Accepted
    assert warnings  # refused with a message, not silently


def test_rule_editor_accepts_a_rule_with_a_domain(qapp):
    editor = RuleEditorDialog(None)
    editor.domains.setPlainText("example.com")
    editor.rb_direct.setChecked(True)
    editor._save()
    assert editor.result() == QDialog.Accepted
    assert editor.result_rule()["domain"] == ["example.com"]
    assert editor.result_rule()["outbound"] == "direct"


# -- save / validation ----------------------------------------------------
def test_save_blocked_by_a_check_rules_error_leaves_settings_unchanged(dlg, monkeypatch):
    monkeypatch.setattr(rd.xraycheck, "check_rules", lambda rules, asset_dir=None: "bad rule")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a[2])), raising=False)

    dlg._add_set("global")
    original_routing = dlg.result_routing()
    assert original_routing.get("sets") in (None, [])  # nothing saved yet

    dlg._save()
    _pump(lambda: not dlg._busy)

    assert dlg.result() != QDialog.Accepted
    assert warnings
    # _routing is only replaced by the validated candidate on success.
    assert dlg.result_routing() is original_routing


def test_save_with_no_sets_still_validates_simple_mode(dlg, monkeypatch):
    calls = []
    monkeypatch.setattr(rd.xraycheck, "check_rules",
                        lambda rules, asset_dir=None: calls.append(rules) or None)
    dlg._save()
    _pump(lambda: not dlg._busy)
    assert dlg.result() == QDialog.Accepted
    assert len(calls) == 1  # Simple mode's own rules, even with zero sets


def test_save_blocked_by_a_bad_simple_mode_rule_leaves_settings_unchanged(dlg, monkeypatch):
    def fake_check(rules, asset_dir=None):
        for r in rules:
            if "domain:gogle.com" in (r.get("domain") or []):
                return 'code not found in geosite.dat: "GOGLE.COM"'
        return None

    monkeypatch.setattr(rd.xraycheck, "check_rules", fake_check)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a[2])), raising=False)

    dlg.domains.setPlainText("gogle.com")
    original_routing = dlg.result_routing()

    dlg._save()
    _pump(lambda: not dlg._busy)

    assert dlg.result() != QDialog.Accepted
    assert warnings and warnings[0].startswith("Simple:")
    assert dlg.result_routing() is original_routing


def test_active_mode_combo_writes_routing_mode(dlg, monkeypatch):
    monkeypatch.setattr(rd.xraycheck, "check_rules", lambda rules, asset_dir=None: None)
    dlg._add_set("empty")
    dlg.rule_model.add({**default_rule(), "domain": ["example.com"]})
    set_id = dlg._sets[0]["id"]
    idx = dlg.mode_combo.findData(set_id)
    dlg.mode_combo.setCurrentIndex(idx)

    dlg._save()
    _pump(lambda: not dlg._busy)

    assert dlg.result() == QDialog.Accepted
    assert dlg.result_routing()["mode"] == set_id
