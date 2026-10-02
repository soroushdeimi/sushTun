import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from xrayui import i18n
from xrayui.core.chains import Chain
from xrayui.core.profiles import Profile
from xrayui.ui.pages.chains_page import ChainCard, ChainEditor, PathView, relative_time


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    yield app
    i18n.set_language('en')
    app.processEvents()


def servers(n=2):
    return [Profile(uid=f'p{i}', name=f'Server {i}', protocol='vless', address='example.org',
                    id='11111111-1111-1111-1111-111111111111') for i in range(n)]


@pytest.mark.parametrize('language', ['en', 'fa'])
def test_path_geometry_and_failure(app, language):
    i18n.set_language(language)
    view = PathView(servers(), broken_at=2)
    view.resize(760, 140)
    rects = view.node_rects()
    xs = [r.center().x() for r in rects]
    assert xs == sorted(xs, reverse=language == 'fa')
    assert [view.link_style(i) for i in range(1, 4)] == ['neutral', 'broken', 'neutral']
    assert [view.node_opacity(i) for i in range(4)] == [1, 1, .4, .4]
    view = PathView(servers(8))
    view.resize(540, 400)
    rects = view.node_rects()
    assert len({r.top() for r in rects}) > 1
    assert all(not a.intersects(b) for i, a in enumerate(rects) for b in rects[i + 1:])
    assert all(view.rect().contains(r.toRect()) for r in rects)


@pytest.mark.parametrize('verdict,text', [(None, 'Not tested'), ('OK', 'Verified'),
                                         ('SKIPS_HOPS', 'Skips hops'), ('BROKEN_AT', 'Broken')])
def test_pill_and_metrics(app, verdict, text):
    ps = servers()
    card = ChainCard(Chain(hops=[p.uid for p in ps]), ps, {'verdict': verdict}, {})
    assert card.status.text() == text
    assert [v.text() for v in card.metric_values] == ['—', '—', '—']
    card.set_testing(True, 2, 3)
    assert card.status.text() == 'Testing…'
    assert card.path_view.testing_link == 2
    assert card.test_button.text() == 'Cancel test'
    card.set_testing(False)
    assert card.status.text() == text
    connected = ChainCard(Chain(hops=[p.uid for p in ps]), ps, {}, {}, True)
    assert connected.status.text() == 'Connected'


def test_relative_time(app):
    assert relative_time(700, now=1000) == 'Tested 5 min ago'
    assert relative_time(999, now=1000) == 'Tested just now'
    i18n.set_language('fa')
    assert relative_time(700, now=1000) == '۵ دقیقه پیش'


def test_editor_roles_and_inline_error(app):
    ps = servers()
    editor = ChainEditor(ps, {}, Chain(hops=[p.uid for p in ps]))
    assert '1 · Entry' in editor.path.item(0).text()
    assert '2 · Exit' in editor.path.item(1).text()
    editor.available.setCurrentRow(0)
    editor.add_hop()
    assert not editor.save_button.isEnabled()
    assert editor.validation.text()
    assert editor.path.item(2).data(Qt.UserRole) == ps[0].uid
    assert 'This server appears twice.' in editor.path.item(2).text()
    editor.remove_at(2)
    assert editor.save_button.isEnabled()


def test_duplicate_persists_new_identity(app, monkeypatch, tmp_path):
    from xrayui import paths
    from xrayui.ui.main_window import MainWindow
    monkeypatch.setattr(paths, 'base_dir', lambda: tmp_path)
    monkeypatch.setattr(paths, 'state_dir', lambda: tmp_path / 'state')
    monkeypatch.setattr(paths, 'profiles_dir', lambda: tmp_path / 'profiles')
    paths.ensure_dirs()
    window = MainWindow(elevated=False)
    try:
        original = Chain(name='Evening', hops=['p0', 'p1'])
        window.chain_store.save(original)
        window._reload_chains()
        window.chains_page.cards[0].duplicate_action.trigger()
        items = window.chain_store.list()
        assert len(items) == 2
        copy = next(c for c in items if c.uid != original.uid)
        assert copy.hops == original.hops
        assert copy.name == 'Evening (copy)'
    finally:
        window.close()


def test_testing_targets_one_card_and_cancels(app):
    from xrayui.ui.pages.chains_page import ChainsPage
    ps = servers()
    items = [Chain(hops=[p.uid for p in ps]) for _ in range(2)]
    page = ChainsPage()
    page.set_chains(items, ps, {})
    cancelled = []
    page.cancelRequested.connect(lambda: cancelled.append(True))
    page.set_testing(True, items[1].uid)
    page.set_progress(2, 3)
    assert not page.cards[0].test_button.isEnabled()
    assert page.cards[0].path_view.testing_link is None
    assert page.cards[1].path_view.testing_link == 2
    page.cards[1].test_button.click()
    assert cancelled == [True]
    page.set_testing(False)
    assert all(card.test_button.isEnabled() for card in page.cards)
    assert all(not card.path_view.timer.isActive() for card in page.cards)


def test_wiring_uses_interface_and_previous_outbound(app):
    ps = servers()
    card = ChainCard(Chain(hops=[p.uid for p in ps]), ps, {}, {}, interface_name=lambda: 'wlan0')
    card._toggle_wiring()
    assert card.wiring_table.item(0, 5).text() == 'wlan0'
    assert card.wiring_table.item(1, 5).text() == 'chain-1'


def test_editor_reorder_updates_preview_and_roles(app):
    ps = servers()
    editor = ChainEditor(ps, {}, Chain(hops=[p.uid for p in ps]))
    editor.path.setCurrentRow(1)
    editor.move(-1)
    assert editor.result_chain().hops == ['p1', 'p0']
    assert editor.path.item(0).text().startswith('1 · Entry')
    preview = editor.preview_host.itemAt(0).widget()
    assert [p.uid for p in preview.profiles] == ['p1', 'p0']


@pytest.mark.parametrize('language', ['en', 'fa'])
@pytest.mark.parametrize('problem', ['duplicate', 'missing', 'unsupported'])
def test_editor_validation_uses_display_names(app, language, problem):
    from PySide6.QtWidgets import QLabel
    i18n.set_language(language)
    ps = servers()
    hops = [p.uid for p in ps]
    if problem == 'duplicate':
        hops.append(ps[0].uid)
    elif problem == 'missing':
        hops.append('private-missing-id')
    else:
        ps[0].protocol = 'unsupported'
    editor = ChainEditor(ps, {}, Chain(hops=hops))
    texts = [editor.validation.text()]
    texts += [label.text() for label in editor.findChildren(QLabel)]
    texts += [editor.path.item(i).text() + editor.path.item(i).toolTip()
              for i in range(editor.path.count())]
    assert not editor.save_button.isEnabled()
    assert all(uid not in text for uid in hops for text in texts)
    if problem != 'missing':
        assert ps[0].name in editor.validation.text()
    editor.close()


@pytest.mark.parametrize('language', ['en', 'fa'])
def test_metric_units_and_alignment(app, language):
    from PySide6.QtWidgets import QFrame, QLabel

    from xrayui.ui.theme import STYLESHEET
    i18n.set_language(language)
    ps = servers()
    card = ChainCard(Chain(hops=[p.uid for p in ps]), ps,
                     dict(warm_ms=84, cold_ms=216, download_mbps=38,
                          country='de', exit_ip='203.0.113.42'), {})
    card.setStyleSheet(STYLESHEET)
    card.resize(900, 500)
    card.show()
    app.processEvents()
    for tile in card.findChildren(QFrame, 'ChainMetric')[:3]:
        number = tile.findChild(QLabel, 'ChainNumber')
        unit = tile.findChild(QLabel, 'ChainUnit')
        assert unit is not None
        nrect, urect = number.geometry(), unit.geometry()
        assert nrect.top() < urect.bottom() and urect.top() < nrect.bottom()
        assert number.font().pixelSize() > unit.font().pixelSize()
        assert '\n' not in unit.text()
    for tile in card.findChildren(QFrame, 'ChainMetric'):
        for label in tile.findChildren(QLabel):
            if label.text():
                assert label.alignment() & (Qt.AlignRight if language == 'fa' else Qt.AlignLeft)
                assert label.alignment() & Qt.AlignAbsolute
    card.close()


@pytest.mark.parametrize('language', ['en', 'fa'])
def test_wiring_headers_share_column_alignment(app, language):
    i18n.set_language(language)
    ps = servers()
    card = ChainCard(Chain(hops=[p.uid for p in ps]), ps, {}, {})
    card.resize(900, 600)
    card._toggle_wiring()
    card.show()
    app.processEvents()
    table = card.wiring_table
    header = table.horizontalHeader()
    alignment = Qt.AlignRight if language == 'fa' else Qt.AlignLeft
    assert header.defaultAlignment() & alignment
    positions = []
    for col in range(table.columnCount()):
        rect = table.visualItemRect(table.item(0, col))
        assert abs(rect.left() - header.sectionViewportPosition(col)) <= 1
        assert abs(rect.width() - header.sectionSize(col)) <= 1
        assert table.item(0, col).textAlignment() & alignment
        positions.append(rect.left())
    assert positions == sorted(positions, reverse=language == 'fa')
    card.close()
