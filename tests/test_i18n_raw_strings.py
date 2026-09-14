"""Best-effort raw-string guard: every bare string literal passed as the
label/text argument to a handful of common Qt calls in xrayui/ui/*.py is
either wrapped in tr() or explicitly allow-listed as technical/a symbol/
the product name. Catches a label added later without tr() around it.

Deliberately narrow -- it only looks at a literal passed *directly*; an
expression like tr("A") + "\\n" + tr("B") is left alone (best-effort, not
a full data-flow analysis).
"""
from __future__ import annotations

import ast
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent / "xrayui" / "ui"

_CONSTRUCTORS = {"QLabel", "QPushButton", "QCheckBox", "QGroupBox", "QRadioButton"}
_FIRST_ARG_METHODS = {"setText", "setToolTip", "setWindowTitle", "setPlaceholderText",
                      "addAction", "addItem"}
_SECOND_ARG_METHODS = {"addTab"}  # addTab(widget, "text")
_MSGBOX_METHODS = {"warning", "information", "question", "critical"}

# Symbols, the product name, technical acronyms/tab labels, language names,
# and routing/DNS/JSON syntax examples -- none of these are English prose
# meant for translation (see CLAUDE.md and the Phase 7b spec's own list of
# what stays untranslated).
_ALLOWLIST = {
    "",  # a label/field filled in later, never shown empty
    "JSON",
    "DNS", "DNS…",
    "sushTun",
    "English", "فارسی",
    "↑", "↓", "✎", "↻", "✕", "⋯", "—",
    "20000-30000",
    '{"headers": {"X-Extra": "1"}}',
    "example.com = 93.184.216.34\ncdn.example.com = 1.2.3.4, 5.6.7.8",
    "178.22.122.100, 185.51.200.2",
    '{"servers": [...]}',
    "example.com\ngeosite:google",
    "10.0.0.0/8\ngeoip:ir",
    "domain:example.com\nfull:exact.example.com\ngeosite:google\nkeyword:ads",
    "443 or 1000-2000 or 80,443,8000-9000",
}


def _bare_literal_calls() -> list[tuple[str, int, str, str]]:
    """(filename, lineno, call-context, literal text) for every flagged call."""
    found = []
    for path in sorted(UI_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            targets: list[tuple[ast.expr, str]] = []
            if isinstance(func, ast.Name) and func.id in _CONSTRUCTORS and node.args:
                targets.append((node.args[0], func.id))
            elif isinstance(func, ast.Attribute):
                if func.attr in _FIRST_ARG_METHODS and node.args:
                    targets.append((node.args[0], func.attr))
                elif func.attr in _SECOND_ARG_METHODS and len(node.args) > 1:
                    targets.append((node.args[1], func.attr))
                elif (func.attr in _MSGBOX_METHODS and isinstance(func.value, ast.Name)
                      and func.value.id == "QMessageBox"):
                    for i in (1, 2):
                        if len(node.args) > i:
                            targets.append((node.args[i], f"QMessageBox.{func.attr}"))
            for arg, context in targets:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append((path.name, node.lineno, context, arg.value))
    return found


def test_no_unwrapped_raw_string_labels():
    violations = [f"{fname}:{lineno}: [{context}] {text!r}"
                 for fname, lineno, context, text in _bare_literal_calls()
                 if text not in _ALLOWLIST]
    assert not violations, "Raw (untranslated) literal labels found:\n" + "\n".join(violations)


def test_allowlist_has_no_stale_entries():
    """Every allow-listed literal must still actually appear somewhere in
    xrayui/ui/*.py -- otherwise it's dead weight hiding a real regression
    if that code path comes back differently worded later."""
    seen = {text for *_rest, text in _bare_literal_calls()}
    stale = _ALLOWLIST - seen
    assert not stale, f"Allowlist entries no longer used anywhere: {stale}"
