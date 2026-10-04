"""HTTP and SOCKS editor fields, credentials, and translations."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.i18n import set_language, tr  # noqa: E402
from xrayui.ui.dialogs import ProfileEditDialog  # noqa: E402
from xrayui.ui.help import is_help  # noqa: E402
from xrayui.ui.server_table import _transport_text  # noqa: E402


@pytest.fixture
def qapp(monkeypatch, flush_widgets):
    app = QApplication.instance() or QApplication([])
    set_language("en")
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: pytest.fail(str(a[2])))
    yield app
    set_language("en")
    flush_widgets()


@pytest.mark.parametrize("protocol,security", [("http", "none"), ("http", "tls"),
                                              ("socks", "none")])
def test_fields(qapp, protocol, security):
    dlg = ProfileEditDialog(Profile(protocol=protocol, address="proxy.example.com",
                                    port=3128, security=security))
    dlg.show()
    for field in (dlg.f_name, dlg.f_protocol, dlg.f_address, dlg.f_port,
                  dlg.f_username, dlg.f_id):
        assert field.isVisible()
        assert is_help(field.toolTip())
    assert dlg._lab_id.text() == "Password"
    assert dlg.f_security.isVisible() == (protocol == "http")
    for field in (dlg.f_sni, dlg.f_fp, dlg.f_alpn):
        assert field.isVisible() == (security == "tls")
    for field in (dlg.f_network, dlg.f_flow, dlg.f_pbk, dlg.f_sid, dlg.f_vmess_security,
                  dlg.f_ss_method, dlg.f_hy2_pcs, dlg.f_wg_local, dlg._advanced):
        assert not field.isVisible()
    if protocol == "http":
        assert [dlg.f_security.itemText(i) for i in range(dlg.f_security.count())] == [
            "none", "tls"]
    dlg.close()


@pytest.mark.parametrize("protocol", ["http", "socks"])
@pytest.mark.parametrize("username,password", [("", ""), ("user", "secret"), ("user", "")])
def test_save(qapp, protocol, username, password):
    dlg = ProfileEditDialog(Profile(protocol=protocol, address="proxy.example.com", port=1080,
                                    network="ws", security="none"))
    dlg.f_username.setText(username)
    dlg.f_id.setText(password)
    dlg._save()
    assert dlg.result() == QDialog.Accepted
    p = dlg.result_profile()
    assert (p.username, p.id, p.network, p.security) == (username, password, "tcp", "none")


def test_load_and_save_http_tls(qapp):
    dlg = ProfileEditDialog(Profile(protocol="http", address="proxy.example.com", port=443,
                                    username="alice", id="secret", security="tls",
                                    sni="tls.example.com", alpn="h2", fp="chrome",
                                    allow_insecure=True))
    assert dlg.f_username.text() == "alice"
    assert dlg.f_id.text() == "secret"
    assert dlg.f_security.currentText() == "tls"
    dlg._save()
    p = dlg.result_profile()
    assert (p.security, p.sni, p.alpn, p.fp) == ("tls", "tls.example.com", "h2", "chrome")
    assert p.allow_insecure


def test_switch_protocol(qapp):
    dlg = ProfileEditDialog(Profile(protocol="vless", security="reality"))
    dlg.f_protocol.setCurrentText("http")
    assert dlg.f_security.currentText() == "none"
    dlg.f_security.setCurrentText("tls")
    dlg.f_protocol.setCurrentText("socks")
    assert dlg.f_security.currentText() == "none"
    dlg.f_protocol.setCurrentText("vless")
    assert dlg.f_security.findText("reality") >= 0
    assert dlg.f_username.isHidden()


@pytest.mark.parametrize("protocol,security,text", [("http", "none", "http"),
                                                   ("http", "tls", "http/tls"),
                                                   ("socks", "none", "socks")])
def test_transport(protocol, security, text):
    assert _transport_text(Profile(protocol=protocol, security=security)) == text


def test_persian(qapp):
    set_language("fa")
    for source in ("Username", "The username for logging in to the proxy.",
                   "Only needed if the proxy requires authentication.",
                   "HTTP (optionally over TLS), SOCKS5, or others. "
                   "A proxy your office gives you, like proxy.example.com:3128? Pick http."):
        assert tr(source) != source


@pytest.mark.parametrize("protocol", ["http", "socks"])
def test_address_required(qapp, monkeypatch, protocol):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    dlg = ProfileEditDialog(Profile(protocol=protocol, address="", port=1080))
    dlg._save()
    assert dlg.result() != QDialog.Accepted
    assert warnings == ["Address is required."]


@pytest.mark.parametrize("protocol", ["http", "socks"])
def test_hidden_transport_fields_do_not_block_save(qapp, protocol):
    dlg = ProfileEditDialog(Profile(protocol=protocol, address="proxy.example.com", port=1080))
    dlg.f_xhttp_extra.setText("invalid json")
    dlg.f_hy2_ports.setText("invalid ports")
    dlg._save()
    assert dlg.result() == QDialog.Accepted
