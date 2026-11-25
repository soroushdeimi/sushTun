"""MASQUE editor: H2/H3, masked private key, WARP identity import, validation.

The identity helper (worker 2) is not cherry-picked yet, so the import path is
tested against a stubbed module; everything else runs against the real editor.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox  # noqa: E402

from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.i18n import set_language, tr  # noqa: E402
from xrayui.ui.dialogs import ProfileEditDialog  # noqa: E402


@pytest.fixture
def qapp(monkeypatch, flush_widgets):
    app = QApplication.instance() or QApplication([])
    set_language("en")
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: pytest.fail(str(a[2])))
    yield app
    set_language("en")
    flush_widgets()


def _masque_profile(**kw):
    base = dict(name="m", protocol="masque", address="warp.example.com", port=443)
    base.update(kw)
    return Profile(**base)


# -- panel basics ---------------------------------------------------------------

def test_panel_defaults_to_h2(qapp):
    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    try:
        assert dlg._masque.f_http_version.currentText() == "h2"
    finally:
        dlg.close()


def test_panel_h3_preserved(qapp):
    p = _masque_profile()
    p.masque_http_version = "h3"
    dlg = ProfileEditDialog(p)
    try:
        assert dlg._masque.f_http_version.currentText() == "h3"
        dlg._masque.f_http_version.setCurrentText("h2")
        dlg._save()
        assert dlg.result() == QDialog.Accepted
        assert dlg.result_profile().masque_http_version == "h2"
    finally:
        dlg.close()


def test_private_key_is_masked(qapp):
    p = _masque_profile()
    p.masque_private_key = "SECRET-KEY"
    dlg = ProfileEditDialog(p)
    try:
        assert dlg._masque.f_private_key.echoMode() == QLineEdit.Password
        # The masked field still holds the value for round-trip, but the
        # visible text is not the raw key.
        assert dlg._masque.f_private_key.text() == "SECRET-KEY"
    finally:
        dlg.close()


def test_masque_fields_are_ltr(qapp):
    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    try:
        for f in (dlg._masque.f_private_key, dlg._masque.f_public_key,
                  dlg._masque.f_addresses, dlg._masque.f_remote_dns):
            assert f.layoutDirection() == Qt.LeftToRight
    finally:
        dlg.close()


# -- round trip -----------------------------------------------------------------

def test_round_trip_preserves_fields(qapp):
    p = _masque_profile()
    p.masque_http_version = "h3"
    p.masque_private_key = "priv"
    p.masque_public_key = "pub"
    p.masque_addresses = "162.158.74.187/32, 2606:4700::/48"
    p.masque_remote_dns = "1.1.1.1"
    dlg = ProfileEditDialog(p)
    try:
        assert dlg._masque.f_public_key.text() == "pub"
        assert dlg._masque.f_addresses.text() == "162.158.74.187/32, 2606:4700::/48"
        dlg._masque.f_remote_dns.setText("9.9.9.9")
        dlg._save()
        assert dlg.result() == QDialog.Accepted
        r = dlg.result_profile()
        assert (r.masque_http_version, r.masque_private_key, r.masque_public_key) == (
            "h3", "priv", "pub")
        assert r.masque_addresses == "162.158.74.187/32, 2606:4700::/48"
        assert r.masque_remote_dns == "9.9.9.9"
    finally:
        dlg.close()


# -- forced carrier -------------------------------------------------------------

def test_masque_forces_network_and_tls(qapp):
    p = _masque_profile()
    p.masque_http_version = "h3"
    dlg = ProfileEditDialog(p)
    try:
        dlg._save()
        assert dlg.result() == QDialog.Accepted
        r = dlg.result_profile()
        assert r.network == "masque"
        assert r.security == "tls"
        # single carrier: alpn mirrors the chosen http version
        assert r.alpn == "h3"
    finally:
        dlg.close()


def test_masque_hides_irrelevant_controls(qapp):
    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    dlg.show()
    try:
        assert dlg._masque.isVisible()
        assert not dlg.f_network.isVisible()
        assert not dlg.f_security.isVisible()
        assert not dlg.f_sid.isVisible()      # reality
        assert not dlg.f_flow.isVisible()     # vision
        assert not dlg._advanced.isVisible()  # legacy/advanced
    finally:
        dlg.close()


def test_other_protocol_hides_masque_panel(qapp):
    dlg = ProfileEditDialog(Profile(name="v", protocol="vless",
                                    address="a.example.com", port=443, id="u"))
    dlg.show()
    try:
        assert not dlg._masque.isVisible()
        assert dlg.f_network.isVisible()
    finally:
        dlg.close()


# -- validation -----------------------------------------------------------------

def test_partial_warp_identity_rejected(qapp, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.f_private_key.setText("only-priv")
        dlg._save()
        assert dlg.result() != QDialog.Accepted
        assert len(warnings) == 1
    finally:
        dlg.close()


def test_missing_address_rejected(qapp, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile(address="")
    dlg = ProfileEditDialog(p)
    try:
        dlg._save()
        assert dlg.result() != QDialog.Accepted
        assert warnings == ["Address is required."]
    finally:
        dlg.close()


def test_generic_masque_without_auth_saves(qapp):
    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    try:
        dlg._save()
        assert dlg.result() == QDialog.Accepted
        assert dlg.result_profile().id == ""
    finally:
        dlg.close()


# -- identity import ------------------------------------------------------------

def test_import_identity_applies_fields(qapp, monkeypatch):
    import types

    calls = {}

    def parse_identity(text):
        calls["text"] = text
        return object()

    def profile_fields(identity):
        return {"masque_private_key": "imp-priv",
                "masque_public_key": "imp-pub",
                "masque_addresses": "1.2.3.4/32"}

    stub = types.ModuleType("xrayui.core.masque_identity")
    stub.parse_identity = parse_identity
    stub.profile_fields = profile_fields
    monkeypatch.setitem(__import__("sys").modules,
                        "xrayui.core.masque_identity", stub)

    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        lambda *a, **k: ("{\"privateKey\":\"x\"}", True))

    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_import.click()
        assert dlg._masque.f_private_key.text() == "imp-priv"
        assert dlg._masque.f_public_key.text() == "imp-pub"
        assert dlg._masque.f_addresses.text() == "1.2.3.4/32"
    finally:
        dlg.close()


def test_import_identity_malformed_does_not_leak(qapp, monkeypatch):
    import types

    def parse_identity(text):
        raise ValueError("bad secret=TOPSECRET")

    def profile_fields(identity):
        raise AssertionError("must not be reached")

    stub = types.ModuleType("xrayui.core.masque_identity")
    stub.parse_identity = parse_identity
    stub.profile_fields = profile_fields
    monkeypatch.setitem(__import__("sys").modules,
                        "xrayui.core.masque_identity", stub)

    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        lambda *a, **k: ("{", True))

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_import.click()
        assert len(warnings) == 1
        # the raw exception (which carries the secret) must not be surfaced
        assert "TOPSECRET" not in warnings[0]
    finally:
        dlg.close()


# -- translations ---------------------------------------------------------------

def test_masque_strings_translated():
    set_language("fa")
    for source in ("HTTP version", "Public key", "Tunnel addresses",
                   "Remote DNS", "Import identity…", "MASQUE"):
        assert tr(source) != source
    set_language("en")
