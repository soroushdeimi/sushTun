"""No-clipping layout guard for the embeddable pages.

The sidebar hosts RoutingPage and DnsPage at content widths 576 and 796; at
those widths a visible label or button must never be laid out narrower than
its own content, in English or Persian. The only legitimate exceptions are
word-wrapped labels (which take multiple lines instead of shrinking) and a
label that elides on purpose -- which must then carry the full text in its
tooltip.
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

from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QLabel,
)

from xrayui.core import dns as dns_mod  # noqa: E402
from xrayui.core.settings import DEFAULTS  # noqa: E402
from xrayui.i18n import set_language  # noqa: E402
from xrayui.ui.pages.dns_page import DnsPage  # noqa: E402
from xrayui.ui.pages.routing_page import RoutingPage  # noqa: E402
from xrayui.ui.rule_editor import CollapsibleSection  # noqa: E402

_WIDTHS = (576, 796)
_LANGS = ("en", "fa")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset_language():
    """Each parametrised case flips the app language; leave it English."""
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
                # Wrapping needs height, not width -- must still fit its lines.
                if w.height() >= w.heightForWidth(w.width()):
                    continue
                problems.append(
                    f"[{where}] QLabel {w.text()!r} {w.width()}x{w.height()} "
                    f"shorter than the {w.heightForWidth(w.width())}px it wraps to")
            elif w.toolTip():
                continue  # elides on purpose, tooltip holds the full text
            else:
                problems.append(
                    f"[{where}] QLabel {w.text()!r} {w.width()}px < sizeHint "
                    f"{hint}px and no tooltip")
        else:
            problems.append(
                f"[{where}] {type(w).__name__} {w.text()!r} {w.width()}px < sizeHint {hint}px")
    return problems


@pytest.mark.parametrize("lang", _LANGS)
@pytest.mark.parametrize("width", _WIDTHS)
@pytest.mark.parametrize("tab", (0, 1))
def test_routing_page_does_not_clip(qapp, width, lang, tab):
    set_language(lang)
    page = RoutingPage(copy.deepcopy(DEFAULTS["routing"]))
    page._add_set("empty")
    page.tabs.setCurrentIndex(tab)
    for section in page.findChildren(CollapsibleSection):
        section.set_expanded(True)
    page.resize(width, 900)
    page.show()
    qapp.processEvents()
    qapp.processEvents()
    try:
        problems = _problems(page, f"{lang} {width} tab{tab}")
    finally:
        page.close()
    assert not problems, "Clipped widgets:\n" + "\n".join(problems)


@pytest.mark.parametrize("lang", _LANGS)
@pytest.mark.parametrize("width", _WIDTHS)
def test_dns_page_does_not_clip(qapp, width, lang):
    set_language(lang)
    page = DnsPage(copy.deepcopy(DEFAULTS["dns"]), copy.deepcopy(DEFAULTS["routing"]))
    page._fill_domestic(dns_mod.DOMESTIC_PRESETS["Shecan"])
    page.remote_via_tunnel.setChecked(True)  # the long explanatory note
    for section in page.findChildren(CollapsibleSection):
        section.set_expanded(True)
    page.resize(width, 900)
    page.show()
    qapp.processEvents()
    qapp.processEvents()
    try:
        problems = _problems(page, f"{lang} {width}")
    finally:
        page.close()
    assert not problems, "Clipped widgets:\n" + "\n".join(problems)


def test_flow_layout_wraps_when_there_is_no_room(qapp):
    from PySide6.QtWidgets import QPushButton, QWidget

    from xrayui.ui.pages.flow import FlowLayout

    host = QWidget()
    flow = FlowLayout()
    host.setLayout(flow)
    for i in range(8):
        flow.addWidget(QPushButton(f"preset-{i}"))
    host.resize(120, 300)
    host.show()
    qapp.processEvents()
    qapp.processEvents()
    # Two columns cannot fit 8 side-by-side buttons in 120px, so the flow
    # must stack enough rows that no button is clipped.
    problems = _problems(host, "flow 120")
    host.close()
    assert flow.heightForWidth(120) > flow.minimumSize().height()
    assert not problems, "Clipped widgets:\n" + "\n".join(problems)


def test_flow_layout_mirrors_in_rtl(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton, QWidget

    from xrayui.ui.pages.flow import FlowLayout

    host = QWidget()
    host.setLayoutDirection(Qt.RightToLeft)
    flow = FlowLayout()
    host.setLayout(flow)
    for i in range(3):
        flow.addWidget(QPushButton(f"rtl-{i}"))
    host.resize(300, 100)
    host.show()
    qapp.processEvents()
    qapp.processEvents()
    items = [flow.itemAt(i).widget() for i in range(flow.count())]
    # The first item must sit flush against the right edge -- leaving it at
    # the left edge would open a gap beside the right-aligned label. The
    # margin comes from the style, so read it back rather than hard-code it.
    right_limit = flow.geometry().right() - flow.contentsMargins().right()
    host.close()
    assert items[0].geometry().right() >= right_limit - 1
    # Items on the row order right-to-left.
    assert items[0].geometry().right() > items[1].geometry().right()
