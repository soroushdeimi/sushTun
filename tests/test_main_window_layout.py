"""No-clipping layout guard for the full sidebar window at its minimum
and a medium size, in both languages.

At 820x560 (the window's minimum) and 1040x700, every visible label or
QPushButton must not be narrower than its own content, in English or
Persian.  The only legitimate exceptions are word-wrapped labels (which
take multiple lines) and a label that elides on purpose -- which must
then carry the full text in its tooltip.
"""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QLabel,
)

from xrayui import paths  # noqa: E402
from xrayui.i18n import set_language  # noqa: E402
from xrayui.ui.main_window import MainWindow  # noqa: E402

_WIDTHS = (820, 1040)
_HEIGHTS = {820: 560, 1040: 700}
_LANGS = ("en", "fa")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    set_language("en")


def _problems(widget, where: str) -> list[str]:
    problems: list[str] = []
    for w in widget.findChildren(QLabel) + widget.findChildren(QAbstractButton):
        if not w.isVisible() or not w.text().strip():
            continue
        hint = w.sizeHint().width()
        if w.width() >= hint:
            continue
        if isinstance(w, QLabel):
            if w.wordWrap():
                if w.height() >= w.heightForWidth(w.width()):
                    continue
                problems.append(
                    f"[{where}] QLabel {w.text()!r} {w.width()}x{w.height()} "
                    f"shorter than the {w.heightForWidth(w.width())}px it wraps to")
            elif w.toolTip():
                continue
            else:
                problems.append(
                    f"[{where}] QLabel {w.text()!r} {w.width()}px < sizeHint "
                    f"{hint}px and no tooltip")
        else:
            problems.append(
                f"[{where}] {type(w).__name__} {w.text()!r} {w.width()}px "
                f"< sizeHint {hint}px")
    return problems


@pytest.mark.parametrize("lang", _LANGS)
@pytest.mark.parametrize("width", _WIDTHS)
def test_main_window_does_not_clip(qapp, tmp_path, monkeypatch, width, lang):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    set_language(lang)
    win = MainWindow(elevated=False)
    win.resize(width, _HEIGHTS[width])
    win.show()
    qapp.processEvents()
    qapp.processEvents()
    try:
        problems = _problems(win, f"{lang} {width}")
    finally:
        win.close()
    assert not problems, "Clipped widgets:\n" + "\n".join(problems)
