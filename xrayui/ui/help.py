"""Hover help: an explanation plus one small example, in a fixed-width column.

Kept apart from widgets.py so the table models can use it too (widgets imports
them). widgets.py re-exports set_help.
"""
from __future__ import annotations

import html

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QAbstractButton, QWidget

from ..i18n import current, tr
from .theme import MUTED

HELP_WIDTH = 340


def help_html(what: str, example: str = "", title: str = "") -> str:
    """Rich-text tooltip body: optional bold title, the explanation, then the
    example on its own line in a softer italic. RTL when the UI is Persian."""
    lines = []
    if title:
        lines.append(f"<b>{html.escape(title)}</b>")
    lines.append(html.escape(what))
    if example:
        lead = html.escape(tr("Example:"))
        lines.append(
            f'<i style="color:{MUTED}">{lead} {html.escape(example)}</i>')
    direction = ' dir="rtl"' if current() == "fa" else ""
    return (f'<table width="{HELP_WIDTH}"{direction}><tr><td{direction}>'
            + "<br>".join(lines) + "</td></tr></table>")


def is_help(tip: str) -> bool:
    return tip.startswith(f'<table width="{HELP_WIDTH}"')


def set_help(target: QWidget | QAction, what: str, example: str = "",
             title: str | None = None) -> None:
    """Give a widget (or menu action) its hover help.

    An icon-only button has no label to say what it is, so its accessible name
    leads the tooltip unless *title* says otherwise. A row of an InsetGroup
    gets the same help, so hovering its label explains the control too.
    """
    if title is None and isinstance(target, QAbstractButton) and not target.text():
        title = target.accessibleName()
    body = help_html(what, example, title or "")
    target.setToolTip(body)
    if isinstance(target, QWidget):
        row = target.parentWidget()
        if row is not None and row.objectName() == "InsetGroupRow":
            row.setToolTip(body)
