"""Chain cards, visual paths and an ordered server editor."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core import chains, geo_exit
from ...i18n import current, ltr, tr
from ..flags import flag_icon, flag_pixmap
from ..theme import ERR, MUTED, OK
from .flow import FlowLayout


def button(text, tip, slot):
    widget = QPushButton(text)
    widget.setToolTip(tip)
    widget.clicked.connect(slot)
    return widget


def label(text, muted=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(True)
    widget.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)
    if muted:
        widget.setObjectName('Muted')
    return widget


class ChainPath(QWidget):
    def __init__(self, profiles, results=None, broken_at=None, compact=False):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft if current() == 'fa' else Qt.LeftToRight)
        self.setStyleSheet('background:transparent;')
        row = FlowLayout(self, spacing=12)
        row.setContentsMargins(0, 4, 0, 4)
        arrow = '←' if current() == 'fa' else '→'
        if not compact:
            row.addWidget(label(tr('You'), True))
        for index, profile in enumerate(profiles, 1):
            if index > 1 or not compact:
                connector = label(('┄  /  ┄\n' + tr('breaks here'))
                                  if broken_at == index else arrow, True)
                if broken_at == index:
                    connector.setStyleSheet(f'color:{ERR};')
                row.addWidget(connector)
            node = QWidget()
            box = QVBoxLayout(node)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            head = QHBoxLayout()
            result = (results or {}).get(profile.uid, {})
            pix = flag_pixmap(result.get('country'))
            if pix:
                flag = QLabel()
                flag.setFixedSize(20, 15)
                flag.setPixmap(pix)
                head.addWidget(flag, 0, Qt.AlignVCenter)
            name = label(profile.name or profile.uid)
            name.setWordWrap(False)
            name.setText(name.fontMetrics().elidedText(profile.name or profile.uid, Qt.ElideRight, 180))
            name.setToolTip(profile.name or profile.uid)
            if broken_at == index or result.get('error'):
                name.setStyleSheet(f'color:{ERR};')
            head.addWidget(name)
            box.addLayout(head)
            latency = result.get('latency_ms')
            if not compact:
                box.addWidget(label(ltr(f'+{latency:.0f} ms') if latency is not None else '—', True))
            row.addWidget(node)
        if not compact:
            row.addWidget(label(arrow, True))
            row.addWidget(label(tr('Internet'), True))


class ChainCard(QFrame):
    testRequested = Signal(str)
    connectRequested = Signal(object)
    disconnectRequested = Signal()
    editRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, chain, profiles, report, profile_results, connected=False):
        super().__init__()
        self.setObjectName('Card')
        self.broken_at = report.get('broken_at')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)
        title = label(chain.name or tr('Unnamed'))
        title.setObjectName('H1')
        outer.addWidget(title)
        known = {p.uid: p for p in profiles}
        from ...core.profiles import Profile
        hops = [known.get(uid, Profile(uid=uid, name=tr('Missing server'))) for uid in chain.hops]
        results = {uid: dict(profile_results.get(uid, {})) for uid in chain.hops}
        for profile, prefix in zip(hops, report.get('prefixes', []), strict=False):
            results[profile.uid].update(prefix)
        outer.addWidget(ChainPath(hops, results, self.broken_at))
        verdict = report.get('verdict')
        text = tr('Not tested yet')
        color = MUTED
        if verdict == 'OK':
            text, color = '✓ ' + tr('Exit verified'), OK
        elif verdict == 'SKIPS_HOPS':
            text, color = '⚠ ' + tr('Skips hops — exits through an earlier server'), ERR
        elif verdict == 'BROKEN_AT':
            k = self.broken_at or 1
            text = (tr('Entry server is unreachable') if k == 1 else
                    tr('Breaks between {entry} and {exit}',
                       entry=hops[k - 2].name, exit=hops[k - 1].name))
            text, color = '× ' + text, ERR
        elif verdict:
            text = tr('Exit unverified — test again to confirm the last server')
        status = label(text)
        status.setStyleSheet(f'color:{color};')
        outer.addWidget(status)
        if report.get('exit_ip'):
            exit_row = QHBoxLayout()
            pix = flag_pixmap(report.get('country'))
            if pix:
                flag = QLabel()
                flag.setFixedSize(20, 15)
                flag.setPixmap(pix)
                exit_row.addWidget(flag)
            exit_row.addWidget(label(tr('Exits in {country} · {ip}',
                country=geo_exit.country_name(report.get('country'), current()),
                ip=ltr(report['exit_ip']))), 1)
            outer.addLayout(exit_row)
        metrics = []
        for key, title in [('warm_ms', tr('Round trip')), ('cold_ms', tr('First connection')),
                           ('download_mbps', tr('Download'))]:
            value = report.get(key)
            if value is not None:
                unit = 'Mbit/s' if key == 'download_mbps' else 'ms'
                metrics.append(f'{title}  {ltr(f"{value:.0f} {unit}")}')
        if metrics:
            outer.addWidget(label('   ·   '.join(metrics), True))
        if report.get('timestamp'):
            stamp = datetime.fromtimestamp(report['timestamp']).strftime('%Y-%m-%d %H:%M')
            outer.addWidget(label(tr('Last tested {time}', time=ltr(stamp)), True))
        actions = FlowLayout()
        self.test_button = button(tr('Test'), tr('Before a video call, test the path and the country websites see.'),
                                  lambda: self.testRequested.emit(chain.uid))
        self.connect_button = button(tr('Disconnect') if connected else tr('Connect'),
            tr('End this connection; time for a pit stop.') if connected else
            tr('Use this path for your traffic; take the scenic route to your next call.'),
            self.disconnectRequested.emit if connected else lambda: self._connect(chain, profiles))
        self.connect_button.setObjectName('Primary')
        actions.addWidget(self.test_button)
        actions.addWidget(self.connect_button)
        self.edit_button = button(tr('Edit'), tr('Change the route; try a different exit for movie night.'),
                                  lambda: self.editRequested.emit(chain.uid))
        self.delete_button = button(tr('Delete'), tr('Remove this saved path; your servers stay ready for another adventure.'),
                                    lambda: self.deleteRequested.emit(chain.uid))
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        outer.addLayout(actions)
        issues = chains.validate(chain, profiles)
        self.connect_button.setEnabled(connected or not issues)
        self.test_button.setEnabled(not issues)
        self.valid = not issues
        if issues:
            outer.addWidget(label('\n'.join(issues)))
        self.wiring = QWidget()
        details = QVBoxLayout(self.wiring)
        details.setContentsMargins(0, 0, 0, 0)
        if not issues:
            built = chains.build(chains.resolve(chain, profiles))
            for profile, outbound in zip(hops, built, strict=True):
                dialer = outbound.get('streamSettings', {}).get('sockopt', {}).get('dialerProxy')
                details.addWidget(label(tr('{name}: {protocol} / {transport} / {security} · tag {tag} · via {via}',
                    name=profile.name, protocol=profile.protocol, transport=profile.network,
                    security=profile.security or tr('none'), tag=outbound['tag'],
                    via=dialer or tr('network card')), True))
        details.addWidget(label(tr('Only the entry is pinned to the network card; each later server is dialed through the previous hop.'), True))
        self.wiring.hide()
        expand = button(tr('How it is wired'), tr('Peek under the hood: see which outbound carries each hop.'),
                        lambda: self.wiring.setVisible(not self.wiring.isVisible()))
        outer.addWidget(expand, 0, Qt.AlignLeading)
        outer.addWidget(self.wiring)

    def _connect(self, chain, profiles):
        self.connectRequested.emit(chains.resolve(chain, profiles))


class ChainsPage(QWidget):
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
        self.add_button = button(tr('New chain'), tr('Build a path with two to eight servers; give your relay a travel buddy.'), self.addRequested.emit)
        self.add_button.setObjectName('Primary')
        top.addWidget(self.add_button)
        outer.addLayout(top)
        self.progress = label('')
        self.progress.hide()
        outer.addWidget(self.progress)
        self.cancel_button = button(tr('Cancel test'), tr('Stop this test; save the bandwidth for your call.'), self.cancelRequested.emit)
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

    def set_chains(self, items, profiles, reports, profile_results=None, connected_uid=''):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.cards = []
        if not items:
            self.rows.addWidget(label(tr('No chains yet. Add two servers to make your first path.'), True))
        for chain in items:
            card = ChainCard(chain, profiles, reports.get(chain.uid, {}), profile_results or {},
                             chain.uid == connected_uid)
            for name in ('testRequested', 'connectRequested', 'disconnectRequested',
                         'editRequested', 'deleteRequested'):
                getattr(card, name).connect(getattr(self, name))
            self.cards.append(card)
            self.rows.addWidget(card)
        self.rows.addStretch(1)

    def set_testing(self, active):
        self.cancel_button.setVisible(active)
        self.progress.setVisible(active or bool(self.progress.text()))
        self.add_button.setEnabled(not active)
        for card in self.cards:
            for control in (card.test_button, card.edit_button, card.delete_button):
                control.setEnabled(not active and (card.valid or control is not card.test_button))


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
        outer.addWidget(label(tr('Name')))
        self.name = QLineEdit(self.chain.name)
        self.name.setToolTip(tr('Name this route so you can find it later; try Evening detour.'))
        outer.addWidget(self.name)
        columns = QHBoxLayout()
        self.available, self.path = QListWidget(), QListWidget()
        self.available.setIconSize(QSize(20, 15))
        self.path.setIconSize(QSize(20, 15))
        self.available.setToolTip(tr('Choose a server to add; start with your trusty relay.'))
        self.path.setToolTip(tr('Drag servers to reorder them; the last one is your Internet exit.'))
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
            (tr('Add'), tr('Add the selected server; one more stop on the journey.'), self.add_hop),
            (tr('Remove'), tr('Remove the selected hop; shorten your detour.'), self.remove_hop),
            (tr('Move up'), tr('Move this server toward you; make it the first stop.'), lambda: self.move(-1)),
            (tr('Move down'), tr('Move this server toward the Internet; choose your final stop.'), lambda: self.move(1)),
        ]:
            actions.addWidget(button(text, tip, slot))
        outer.addLayout(actions)
        self.preview_host = QVBoxLayout()
        outer.addLayout(self.preview_host)
        self.validation = label('')
        self.validation.setStyleSheet(f'color:{ERR};')
        outer.addWidget(self.validation)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(button(tr('Cancel'), tr('Leave without saving; your old route is safe.'), self.reject))
        self.save_button = button(tr('Save'), tr('Keep this route for later; your next detour is one click away.'), self.accept)
        self.save_button.setObjectName('Primary')
        bottom.addWidget(self.save_button)
        outer.addLayout(bottom)
        self.path.model().rowsMoved.connect(self.validate)
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

    def remove_hop(self):
        self.path.takeItem(self.path.currentRow())
        self.validate()

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
            item.setText(self._item(uid).text())
            individual = chains.validate(chains.Chain(hops=[uid]), self.profiles)[1:]
            if chain.hops.count(uid) > 1:
                individual.append(tr('This server appears twice.'))
            item.setForeground(QColor(ERR if individual else '#f5f5f7'))
            if individual:
                item.setText(item.text() + '\n' + '\n'.join(individual))
            item.setToolTip('\n'.join(individual))
        while self.preview_host.count():
            self.preview_host.takeAt(0).widget().deleteLater()
        self.preview_host.addWidget(ChainPath([known[uid] for uid in chain.hops if uid in known],
                                              self.results, compact=True))

    def accept(self):
        if not chains.validate(self.result_chain(), self.profiles):
            super().accept()
