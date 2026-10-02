"""Chain cards, visual paths and an ordered server editor."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core import chains, geo_exit
from ...i18n import current, ltr, tr
from ..flags import flag_icon, flag_pixmap
from ..help import help_html, set_help
from ..theme import ACCENT, ERR, LINE, MUTED, OK, SUNKEN, SURFACE, TEXT, WARN
from .flow import FlowLayout


def button(text, help_text, slot):
    widget = QPushButton(text)
    set_help(widget, *help_text)
    widget.clicked.connect(slot)
    return widget


def _new_chain_help():
    return (tr('Build a path of two to eight servers.'),
            tr('A relay inside the country, then a server abroad.'))


def _path_help():
    return (tr('The route in order: the first hop first, the last hop is your Internet exit.'),
            tr('Drag a server up or down to reorder it.'))


def label(text, muted=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(True)
    widget.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)
    if muted:
        widget.setObjectName('Muted')
    return widget


def local_number(value):
    text = str(value)
    return text.translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')) if current() == 'fa' else text


def relative_time(timestamp, now=None):
    if not timestamp:
        return tr('Not tested yet')
    elapsed = max(0, int((time.time() if now is None else now) - timestamp))
    if elapsed < 60:
        return tr('Tested just now')
    if elapsed < 3600:
        return tr('Tested {n} min ago', n=local_number(elapsed // 60))
    if elapsed < 86400:
        return tr('Tested {n} hours ago', n=local_number(elapsed // 3600))
    return tr('Tested {n} days ago', n=local_number(elapsed // 86400))


class PathView(QWidget):
    def __init__(self, profiles, results=None, broken_at=None, compact=False):
        super().__init__()
        self.profiles = profiles
        self.results = results or {}
        self.broken_at = broken_at
        self.compact = compact
        self.testing_link = None
        self.phase = 0
        self.setLayoutDirection(Qt.RightToLeft if current() == 'fa' else Qt.LeftToRight)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(280)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._pulse)
        set_help(self, tr('Follow the arrows from you to the Internet; each link shows the delay it adds.'),
                 tr('42 ms above a link means that hop adds 42 ms.'))
        self.setAccessibleName(tr('Ordered path'))

    def _pulse(self):
        self.phase += .18
        self.update()

    def set_testing(self, link=None):
        self.testing_link = link
        self.timer.start() if link else self.timer.stop()
        self.update()

    def _grid(self, width):
        count = len(self.profiles) + 2
        # The compact preview packs its nodes closer so a path of up to four
        # hops still fits one row at the editor's default width.
        gap_min, pitch = (40., 127) if self.compact else (72., 170)
        columns = max(2, min(count, int((width - 24 + gap_min) / pitch)))
        chip = min(116., (width - 24 - (columns - 1) * gap_min) / columns)
        return count, columns, chip

    def node_rects(self):
        count, columns, chip = self._grid(self.width())
        gap = (self.width() - 24 - columns * chip) / max(1, columns - 1)
        rects = []
        for index in range(count):
            row, col = divmod(index, columns)
            x = 12 + col * (chip + gap)
            if self.layoutDirection() == Qt.RightToLeft:
                x = self.width() - x - chip
            rects.append(QRectF(x, 30 + row * 108, chip, 36))
        return rects

    def sizeHint(self):
        return QSize(700, self.heightForWidth(self.width()))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        count, columns, _chip = self._grid(width)
        return math.ceil(count / columns) * 108

    def resizeEvent(self, event):
        self.setMinimumHeight(self.heightForWidth(self.width()))
        super().resizeEvent(event)

    def link_style(self, index):
        if index == self.broken_at:
            return 'broken'
        result = self.results.get(self.profiles[index - 1].uid, {}) if index <= len(self.profiles) else {}
        return 'ok' if result.get('latency_ms') is not None and not result.get('error') else 'neutral'

    def node_opacity(self, index):
        return .4 if self.broken_at is not None and index >= self.broken_at else 1

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rects = self.node_rects()
        rtl = self.layoutDirection() == Qt.RightToLeft
        direction = -1 if rtl else 1
        for index, (a, b) in enumerate(zip(rects, rects[1:], strict=False), 1):
            style = self.link_style(index)
            color = QColor(ERR if style == 'broken' else OK if style == 'ok' else MUTED)
            if self.testing_link == index:
                color = QColor(ACCENT)
                color.setAlphaF(.45 + .3 * (1 + math.sin(self.phase)) / 2)
            painter.setPen(QPen(color, 1.5, Qt.DashLine if style == 'broken' else Qt.SolidLine))
            start = QPointF(a.left() - 4 if rtl else a.right() + 4, a.center().y())
            end = QPointF(b.right() + 4 if rtl else b.left() - 4, b.center().y())
            path = QPainterPath(start)
            if a.top() == b.top():
                path.lineTo(end)
                middle = (start + end) / 2
            else:
                bend_y = a.bottom() + 44
                path.lineTo(start.x() + direction * 6, start.y())
                path.lineTo(start.x() + direction * 6, bend_y)
                path.lineTo(end.x() - direction * 6, bend_y)
                path.lineTo(end.x() - direction * 6, end.y())
                path.lineTo(end)
                middle = QPointF(self.width() / 2, bend_y)
            painter.drawPath(path)
            painter.setPen(QPen(color, 1.5))
            painter.drawLine(end, end + QPointF(-direction * 4, -3))
            painter.drawLine(end, end + QPointF(-direction * 4, 3))
            result = self.results.get(self.profiles[index - 1].uid, {}) if index <= len(self.profiles) else {}
            latency = result.get('latency_ms')
            value = tr('{n} ms', n=local_number(round(latency))) if latency is not None else '—'
            painter.drawText(QRectF(middle.x() - 45, middle.y() - 26, 90, 20), Qt.AlignCenter, value)
            if style == 'broken':
                painter.fillRect(QRectF(middle.x() - 7, middle.y() - 8, 14, 16), QColor(SURFACE))
                painter.drawText(QRectF(middle.x() - 8, middle.y() - 10, 16, 20), Qt.AlignCenter, '×')
                painter.drawText(QRectF(middle.x() - 48, middle.y() + 5, 96, 20), Qt.AlignCenter, tr('breaks here'))
        for index, rect in enumerate(rects):
            painter.setOpacity(self.node_opacity(index))
            painter.setPen(QPen(QColor(LINE), 1))
            painter.setBrush(QColor(SUNKEN))
            painter.drawRoundedRect(rect, 9, 9)
            painter.setPen(QColor(TEXT))
            content = rect.adjusted(8, 0, -8, 0)
            if index in (0, len(rects) - 1):
                name = tr('You') if index == 0 else tr('Internet')
                glyph = QRectF(content.left(), rect.center().y() - 7, 14, 14)
                if index == 0:
                    painter.drawRoundedRect(glyph.adjusted(0, 0, 0, -4), 1, 1)
                    painter.drawLine(glyph.bottomLeft(), glyph.bottomRight())
                else:
                    painter.drawEllipse(glyph)
                    painter.drawEllipse(glyph.adjusted(4, 0, -4, 0))
                    painter.drawLine(QPointF(glyph.left(), glyph.center().y()), QPointF(glyph.right(), glyph.center().y()))
                content.adjust(20, 0, 0, 0)
            else:
                profile = self.profiles[index - 1]
                name = profile.name or profile.uid
                pix = flag_pixmap(self.results.get(profile.uid, {}).get('country'))
                if pix:
                    painter.drawPixmap(int(content.left()), int(rect.center().y() - 7), 20, 15, pix)
                    content.adjust(25, 0, 0, 0)
            painter.drawText(content, Qt.AlignCenter, painter.fontMetrics().elidedText(name, Qt.ElideRight, int(content.width())))
            role = tr('Entry') if index == 1 else tr('Exit') if index == len(rects) - 2 else ''
            painter.setPen(QColor(MUTED))
            painter.drawText(rect.translated(0, 34), Qt.AlignHCenter | Qt.AlignTop, role)
        painter.end()


ChainPath = PathView


class ChainCard(QFrame):
    testRequested = Signal(str)
    cancelRequested = Signal()
    connectRequested = Signal(object)
    disconnectRequested = Signal()
    editRequested = Signal(str)
    duplicateRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, chain, profiles, report, profile_results, connected=False, interface_name=''):
        super().__init__()
        self.setObjectName('Card')
        self.chain, self.report, self.connected = chain, report, connected
        self.interface_name = interface_name
        self.testing = False
        self.broken_at = report.get('broken_at')
        if connected:
            self.setStyleSheet(f'QFrame#Card {{ border:1px solid {ACCENT}; }}')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(14)
        header = QHBoxLayout()
        title = label(chain.name or tr('Unnamed'))
        title.setObjectName('H1')
        header.addWidget(title, 1)
        self.status = label('')
        self.status.setWordWrap(False)
        header.addWidget(self.status)
        menu_button = QToolButton()
        menu_button.setText('⋯')
        menu_button.setObjectName('IconButton')
        menu_button.setFixedSize(30, 30)
        set_help(menu_button, tr('Manage this chain: edit, duplicate or delete it.'),
                 tr('Duplicate a chain to try another exit.'))
        menu_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(menu_button)
        menu.setToolTipsVisible(True)
        self.edit_button = menu.addAction(tr('Edit'), lambda: self.editRequested.emit(chain.uid))
        set_help(self.edit_button, tr('Change the servers in this chain or their order.'),
                 tr('Swap the last server to try a different exit.'))
        self.duplicate_action = menu.addAction(tr('Duplicate'), lambda: self.duplicateRequested.emit(chain.uid))
        set_help(self.duplicate_action, tr('Make a copy of this chain and keep the original.'),
                 tr('Copy it, then change only the exit server.'))
        self.delete_button = menu.addAction(tr('Delete'), lambda: self.deleteRequested.emit(chain.uid))
        set_help(self.delete_button, tr('Remove this saved chain; your servers stay in your list.'),
                 tr('Delete a chain you no longer use.'))
        menu_button.setMenu(menu)
        header.addWidget(menu_button)
        outer.addLayout(header)
        known = {p.uid: p for p in profiles}
        from ...core.profiles import Profile
        hops = [known.get(uid, Profile(uid=uid, name=tr('Missing server'))) for uid in chain.hops]
        results = {uid: {'country': profile_results.get(uid, {}).get('country')} for uid in chain.hops}
        for profile, prefix in zip(hops, report.get('prefixes', []), strict=False):
            results[profile.uid].update(prefix)
        self.path_view = PathView(hops, results, self.broken_at)
        outer.addWidget(self.path_view)
        tiles = QHBoxLayout()
        self.metric_values = []
        rtl = current() == 'fa'
        side = Qt.AlignAbsolute | (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignVCenter
        direction = Qt.RightToLeft if rtl else Qt.LeftToRight
        for key, title in [('warm_ms', tr('Round trip')), ('cold_ms', tr('First connection')),
                           ('download_mbps', tr('Download'))]:
            tile = QFrame()
            tile.setObjectName('ChainMetric')
            tile.setLayoutDirection(direction)
            box = QVBoxLayout(tile)
            value = report.get(key)
            text = '—' if value is None else local_number(round(value))
            number = label(text)
            number.setObjectName('ChainNumber')
            number.setWordWrap(False)
            number.setAlignment(side)
            self.metric_values.append(number)
            unit = label(tr('Mbit/s') if key == 'download_mbps' else tr('ms'))
            unit.setObjectName('ChainUnit')
            unit.setWordWrap(False)
            unit.setAlignment(side)
            figure = QHBoxLayout()
            figure.setSpacing(5)
            figure.addWidget(number)
            figure.addWidget(unit)
            figure.addStretch()
            box.addLayout(figure)
            caption = label(title, True)
            caption.setAlignment(side)
            box.addWidget(caption)
            tiles.addWidget(tile, 1)
        tile = QFrame()
        tile.setObjectName('ChainMetric')
        tile.setLayoutDirection(direction)
        box = QVBoxLayout(tile)
        country_row = QHBoxLayout()
        pix = flag_pixmap(report.get('country'))
        if pix:
            flag = QLabel()
            flag.setPixmap(pix)
            country_row.addWidget(flag)
        country = label(geo_exit.country_name(report.get('country'), current()) if report.get('country') else '—')
        country.setAlignment(side)
        country_row.addWidget(country, 1)
        box.addLayout(country_row)
        ip = label(report.get('exit_ip') or '—')
        ip.setObjectName('Mono')
        ip.setLayoutDirection(Qt.LeftToRight)
        ip.setAlignment(side)
        ip.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(ip)
        tiles.addWidget(tile, 1)
        outer.addLayout(tiles)
        self.testing_caption = label('', True)
        self.testing_caption.hide()
        outer.addWidget(self.testing_caption)
        footer = QHBoxLayout()
        self.tested_time = label(relative_time(report.get('timestamp')), True)
        footer.addWidget(self.tested_time)
        self.time_timer = QTimer(self)
        self.time_timer.setInterval(60000)
        self.time_timer.timeout.connect(lambda: self.tested_time.setText(relative_time(report.get('timestamp'))))
        self.time_timer.start()
        self.expand = QLabel()
        set_help(self.expand, tr('See which outbound carries each hop.'),
                 tr('chain-1 carries the second server.'))
        self.expand.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
        self.expand.linkActivated.connect(self._toggle_wiring)
        footer.addWidget(self.expand)
        footer.addStretch()
        self.test_button = button(tr('Test'), (tr('Check every link and the country websites see as your exit.'),
                                   tr('Run it before a video call.')), self._test)
        self.connect_button = button(tr('Disconnect') if connected else tr('Connect'),
            (tr('Stop sending your traffic through this chain.'),
             tr('Disconnect to go back to your normal connection.')) if connected else
            (tr('Send all your traffic through this chain.'),
             tr('Connect before opening sites that need the exit country.')),
            self.disconnectRequested.emit if connected else lambda: self._connect(chain, profiles))
        self.connect_button.setObjectName('Primary')
        footer.addWidget(self.test_button)
        footer.addWidget(self.connect_button)
        outer.addLayout(footer)
        issues = chains.validate(chain, profiles)
        self.valid = not issues
        self.connect_button.setEnabled(connected or self.valid)
        self.test_button.setEnabled(self.valid)
        if issues:
            outer.addWidget(label('\n'.join(issues)))
        self.wiring = QWidget()
        self.wiring.setObjectName('ChainWiring')
        details = QVBoxLayout(self.wiring)
        details.setContentsMargins(0, 8, 0, 0)
        table = QTableWidget(len(hops) if not issues else 0, 6)
        table.setHorizontalHeaderLabels([tr('Hop'), tr('Server'), tr('Protocol'),
                                         tr('Transport / security'), tr('Outbound tag'), tr('Dials through')])
        table.setObjectName('ChainWiringTable')
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        set_help(table, tr('One row per hop: its server, its outbound tag and what it dials through.'),
                 tr('chain-1 carries the second server.'))
        table.verticalHeader().hide()
        wiring_rtl = current() == 'fa'
        table.setLayoutDirection(Qt.RightToLeft if wiring_rtl else Qt.LeftToRight)
        wiring_side = Qt.AlignAbsolute | (Qt.AlignRight if wiring_rtl else Qt.AlignLeft) | Qt.AlignVCenter
        table.horizontalHeader().setDefaultAlignment(wiring_side)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        if not issues:
            for row, (profile, outbound) in enumerate(zip(hops, chains.build(chains.resolve(chain, profiles)), strict=True)):
                via = outbound.get('streamSettings', {}).get('sockopt', {}).get('dialerProxy')
                values = [local_number(row + 1), profile.name, profile.protocol,
                          f'{profile.network} / {profile.security or tr("none")}',
                          outbound['tag'], via or (interface_name if isinstance(interface_name, str) else '') or tr('network card')]
                for col, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(wiring_side)
                    table.setItem(row, col, item)
        self.wiring_table = table
        table.setFixedHeight(table.horizontalHeader().sizeHint().height() + 34 * table.rowCount() + 6)
        details.addWidget(table)
        details.addWidget(label(tr("Only the entry is bound to the network card; Xray's dialerProxy dials every later hop through the previous one, never directly through the local network."), True))
        self.wiring.hide()
        outer.addWidget(self.wiring)
        self._update_expander()
        self._update_status()

    def _update_expander(self):
        chevron = '▾' if not self.wiring.isHidden() else '◂' if current() == 'fa' else '▸'
        self.expand.setText(f'<a href="wiring" style="color:{ACCENT};text-decoration:none">{tr("How it is wired")} {chevron}</a>')

    def _toggle_wiring(self, *_):
        if self.wiring.isHidden() and callable(self.interface_name) and self.wiring_table.rowCount():
            self.wiring_table.item(0, 5).setText(self.interface_name() or tr('network card'))
        self.wiring.setVisible(self.wiring.isHidden())
        self._update_expander()

    def _update_status(self):
        verdict = self.report.get('verdict')
        text, color = tr('Not tested'), MUTED
        if verdict == 'OK':
            text, color = tr('Verified'), OK
        elif verdict == 'SKIPS_HOPS':
            text, color = tr('Skips hops'), WARN
        elif verdict == 'BROKEN_AT':
            text, color = tr('Broken'), ERR
        elif verdict:
            text, color = tr('Exit unverified — test again to confirm the last server'), WARN
        if self.connected:
            text, color = tr('Connected'), ACCENT
        if self.testing:
            text, color = tr('Testing…'), ACCENT
        self.status.setText(text)
        self.status.setStyleSheet(f'color:{color};background:transparent;border:1px solid {color};border-radius:10px;padding:3px 10px;')

    def _test(self):
        self.cancelRequested.emit() if self.testing else self.testRequested.emit(self.chain.uid)

    def set_testing(self, active, link=1, total=None):
        self.testing = active
        self.path_view.set_testing(link if active else None)
        self.testing_caption.setVisible(active)
        self.testing_caption.setText(tr('Testing link {n} of {total}…', n=local_number(link),
                                        total=local_number(total or len(self.chain.hops) + 1)))
        self.test_button.setText(tr('Cancel test') if active else tr('Test'))
        set_help(self.test_button,
                 *((tr('Stop the test that is running.'),
                    tr('Cancel it if you need the bandwidth for a call.')) if active else
                   (tr('Check every link and the country websites see as your exit.'),
                    tr('Run it before a video call.'))))
        self._update_status()

    def _connect(self, chain, profiles):
        self.connectRequested.emit(chains.resolve(chain, profiles))


class ChainsPage(QWidget):
    duplicateRequested = Signal(str)
    testRequested = Signal(str)
    connectRequested = Signal(object)
    disconnectRequested = Signal()
    editRequested = Signal(str)
    deleteRequested = Signal(str)
    addRequested = Signal()
    cancelRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft if current() == 'fa' else Qt.LeftToRight)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(14)
        top = QHBoxLayout()
        intro = label(tr('Choose the route. Verify the exit.'), True)
        top.addWidget(intro, 1)
        self.add_button = button(tr('New chain'), _new_chain_help(), self.addRequested.emit)
        self.add_button.setObjectName('Primary')
        top.addWidget(self.add_button)
        outer.addLayout(top)
        self.progress = label('')
        self.progress.hide()
        outer.addWidget(self.progress)
        self.cancel_button = button(tr('Cancel test'), (tr('Stop the test that is running.'),
                                                 tr('Cancel it if you need the bandwidth for a call.')),
                                 self.cancelRequested.emit)
        self.cancel_button.hide()
        outer.addWidget(self.cancel_button, 0, Qt.AlignLeading)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self.rows = QVBoxLayout(host)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(14)
        area.setWidget(host)
        outer.addWidget(area, 1)
        self.cards = []
        self.testing_uid = ''

    def set_chains(self, items, profiles, reports, profile_results=None, connected_uid='', interface_name=''):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards = []
        if not items:
            empty = QFrame()
            empty.setObjectName('Card')
            content = QVBoxLayout(empty)
            content.setContentsMargins(28, 28, 28, 28)
            title = label(tr('A route with a little more reach'))
            title.setObjectName('H1')
            content.addWidget(title)
            content.addWidget(label(tr('Connect through a relay inside the country, then a server abroad. Test the path to check where your traffic exits.'), True))
            content.addWidget(button(tr('New chain'), _new_chain_help(), self.addRequested.emit), 0, Qt.AlignLeading)
            self.rows.addWidget(empty)
        self.add_button.setVisible(bool(items))
        for chain in items:
            card = ChainCard(chain, profiles, reports.get(chain.uid, {}), profile_results or {},
                             chain.uid == connected_uid, interface_name)
            for name in ('testRequested', 'connectRequested', 'disconnectRequested',
                         'editRequested', 'deleteRequested', 'duplicateRequested', 'cancelRequested'):
                getattr(card, name).connect(getattr(self, name))
            self.cards.append(card)
            self.rows.addWidget(card)
        self.rows.addStretch(1)

    def set_testing(self, active, uid=None):
        if uid is not None:
            self.testing_uid = uid
        if not active:
            self.testing_uid = ''
        self.cancel_button.hide()
        self.add_button.setEnabled(not active)
        for card in self.cards:
            testing = active and card.chain.uid == self.testing_uid
            card.set_testing(testing)
            card.test_button.setEnabled(testing or (not active and card.valid))
            for control in (card.edit_button, card.delete_button, card.duplicate_action):
                control.setEnabled(not active)

    def set_progress(self, link, total):
        for card in self.cards:
            if card.chain.uid == self.testing_uid:
                card.set_testing(True, link, total)


class PathRowDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = ''


class ChainEditor(QDialog):
    def __init__(self, profiles, results, chain=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Edit chain') if chain else tr('New chain'))
        self.setLayoutDirection(Qt.RightToLeft if current() == 'fa' else Qt.LeftToRight)
        self.resize(780, 580)
        self.profiles, self.results = profiles, results
        self.chain = chain or chains.Chain()
        outer = QVBoxLayout(self)
        outer.setSpacing(12)
        self.preview_host = QVBoxLayout()
        outer.addLayout(self.preview_host)
        outer.addWidget(label(tr('Name')))
        self.name = QLineEdit(self.chain.name)
        set_help(self.name, tr('A name for this chain so you can spot it in the list.'),
                 tr('Evening detour.'))
        outer.addWidget(self.name)
        columns = QHBoxLayout()
        self.available, self.path = QListWidget(), QListWidget()
        self.available.setIconSize(QSize(20, 15))
        self.path.setIconSize(QSize(20, 15))
        self.path.setItemDelegate(PathRowDelegate(self.path))
        set_help(self.available, tr('Servers you can add to the path; double-click one to add it.'),
                 tr('Start with your relay inside the country.'))
        set_help(self.path, *_path_help())
        self.path.setDragDropMode(QAbstractItemView.InternalMove)
        for title, widget in ((tr('Available servers'), self.available), (tr('Ordered path'), self.path)):
            col = QVBoxLayout()
            col.addWidget(label(title, True))
            col.addWidget(widget)
            columns.addLayout(col)
        outer.addLayout(columns, 1)
        for profile in profiles:
            self.available.addItem(self._item(profile.uid))
        for uid in self.chain.hops:
            self.path.addItem(self._item(uid))
        actions = FlowLayout()
        for text, tip, slot in [
            (tr('Add'), (tr('Add the selected server to the end of the path.'),
                         tr('Select a server in Available servers and press Add.')), self.add_hop),
            (tr('Remove'), (tr('Remove the selected hop from the path.'),
                            tr('Drop a hop that slows things down.')), self.remove_hop),
            (tr('Move up'), (tr('Move the selected hop one place toward you.'),
                             tr('Put your relay inside the country first.')), lambda: self.move(-1)),
            (tr('Move down'), (tr('Move the selected hop one place toward the Internet.'),
                               tr('Put the foreign server last: it is your exit.')), lambda: self.move(1)),
        ]:
            actions.addWidget(button(text, tip, slot))
        outer.addLayout(actions)
        self.validation = label('')
        self.validation.setStyleSheet(f'color:{ERR};')
        bottom = QHBoxLayout()
        bottom.addWidget(self.validation, 1)
        bottom.addStretch()
        bottom.addWidget(button(tr('Cancel'), (tr('Close without saving; the saved chain stays as it was.'),
                                               tr('Changed your mind? Cancel.')), self.reject))
        self.save_button = button(tr('Save'), (tr('Save this chain to your list.'),
                                               tr('Save it, then press Test on its card.')), self.accept)
        self.save_button.setObjectName('Primary')
        bottom.addWidget(self.save_button)
        outer.addLayout(bottom)
        self.path.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self.validate))
        self.available.itemDoubleClicked.connect(lambda *_: self.add_hop())
        self.validate()

    def _item(self, uid):
        profile = next((p for p in self.profiles if p.uid == uid), None)
        result = self.results.get(uid, {})
        delay = result.get('delay_ms')
        text = profile.name if profile else tr('Missing server')
        if delay is not None:
            text += ' · ' + ltr(f'{delay:.0f} ms')
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, uid)
        icon = flag_icon(result.get('country'))
        if icon:
            item.setIcon(icon)
        return item

    def result_chain(self):
        return chains.Chain(uid=self.chain.uid, name=self.name.text().strip(),
                            hops=[self.path.item(i).data(Qt.UserRole) for i in range(self.path.count())])

    def add_hop(self):
        item = self.available.currentItem()
        if item:
            self.path.addItem(self._item(item.data(Qt.UserRole)))
            self.validate()

    def remove_at(self, row):
        self.path.takeItem(row)
        self.validate()

    def remove_hop(self):
        self.remove_at(self.path.currentRow())

    def move(self, delta):
        row = self.path.currentRow()
        if 0 <= row + delta < self.path.count() and row >= 0:
            item = self.path.takeItem(row)
            self.path.insertItem(row + delta, item)
            self.path.setCurrentRow(row + delta)
            self.validate()

    def validate(self, *_):
        chain = self.result_chain()
        problems = chains.validate(chain, self.profiles)
        self.validation.setText('\n'.join(problems))
        self.save_button.setEnabled(not problems)
        known = {p.uid: p for p in self.profiles}
        for i, uid in enumerate(chain.hops):
            item = self.path.item(i)
            role = tr('Entry') if i == 0 else tr('Exit') if i == len(chain.hops) - 1 else ''
            heading = local_number(i + 1) + (' · ' + role if role else '')
            item.setText(heading + '   ' + self._item(uid).text())
            individual = chains.validate(chains.Chain(hops=[uid]), self.profiles)[1:]
            if chain.hops.count(uid) > 1:
                individual.append(tr('This server appears twice.'))
            if individual:
                item.setText(item.text() + '\n' + '\n'.join(individual))
            item.setToolTip('\n'.join(individual) or help_html(*_path_help()))
            row = QWidget()
            row.setStyleSheet('background:transparent;')
            box = QHBoxLayout(row)
            box.setContentsMargins(4, 4, 4, 4)
            handle = label('⠿', True)
            set_help(handle, *_path_help())
            handle.setAttribute(Qt.WA_TransparentForMouseEvents)
            box.addWidget(handle)
            text_box = QVBoxLayout()
            title = label(heading + '   ' + self._item(uid).text())
            title.setAttribute(Qt.WA_TransparentForMouseEvents)
            text_box.addWidget(title)
            if individual:
                error = label('\n'.join(individual))
                error.setStyleSheet(f'color:{ERR};')
                error.setAttribute(Qt.WA_TransparentForMouseEvents)
                text_box.addWidget(error)
            box.addLayout(text_box, 1)
            remove = button('×', (tr('Remove this hop from the path.'),
                                  tr('Drop the middle hop to shorten the path.')),
                            lambda checked=False, item=item: self.remove_at(self.path.row(item)))
            remove.setFixedWidth(36)
            box.addWidget(remove)
            item.setSizeHint(QSize(280, 48 + 34 * len(individual)))
            self.path.setItemWidget(item, row)
        while self.preview_host.count():
            self.preview_host.takeAt(0).widget().deleteLater()
        self.preview_host.addWidget(ChainPath([known[uid] for uid in chain.hops if uid in known],
                                              self.results, compact=True))

    def accept(self):
        if not chains.validate(self.result_chain(), self.profiles):
            super().accept()
