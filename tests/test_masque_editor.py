"""MASQUE editor: H2/H3, masked private key, WARP identity import, validation.

The import path runs against the real core.warp_identity parser with dummy
base64 keys; everything else runs against the real editor.
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
        # Advanced stays available for MASQUE (pin cert / verify name are
        # TLS options); the irrelevant rows inside it stay hidden.
        assert dlg._advanced.isVisible()
        assert dlg._advanced.toggle.isVisible()
        dlg._advanced.set_expanded(True)
        assert dlg.f_pcs.isVisible()
        assert dlg.f_vcn.isVisible()
        assert not dlg.f_header_type.isVisible()
        assert not dlg.f_xhttp_mode.isVisible()
        assert not dlg.f_xhttp_extra.isVisible()
        assert not dlg.f_ech.isVisible()
        assert not dlg.f_hy2_pcs.isVisible()
        assert not dlg.f_hy2_obfs_password.isVisible()
    finally:
        dlg.close()


def test_masque_pcs_vcn_save_and_render(qapp):
    import json as _json

    from xrayui.core import render

    pin = "ab" * 32
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        dlg._advanced.set_expanded(True)
        dlg.f_pcs.setText(pin)
        dlg.f_vcn.setText("warp.example.com")
        dlg._save()
        assert dlg.result() == QDialog.Accepted
        r = dlg.result_profile()
        assert r.pcs == pin
        assert r.vcn == "warp.example.com"
        cfg = _json.loads(render.build_text(r, "utun99"))
        out = next(o for o in cfg["outbounds"] if o.get("tag") == "proxy")
        tls = out["streamSettings"]["tlsSettings"]
        assert tls["pinnedPeerCertSha256"] == pin
        assert tls["verifyPeerCertByName"] == "warp.example.com"
    finally:
        dlg.close()


def test_masque_exposes_auth_sni_fp_host_path(qapp):
    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    dlg.show()
    try:
        assert dlg._lab_username.isVisible()
        assert dlg.f_username.isVisible()
        assert dlg._lab_id.isVisible()
        assert dlg.f_id.isVisible()
        assert dlg._lab_id.text() == "Password"
        assert dlg.f_id.echoMode() == QLineEdit.Password
        assert dlg.f_sni.isVisible()
        assert dlg.f_fp.isVisible()
        assert dlg.f_host.isVisible()
        assert dlg.f_path.isVisible()
        # forced TLS: no security/network choice, no Reality/Vision rows
        assert not dlg.f_security.isVisible()
        assert not dlg.f_network.isVisible()
        assert not dlg.f_sid.isVisible()
        assert not dlg.f_flow.isVisible()
    finally:
        dlg.close()


def test_masque_enter_fields_save_serialize_render(qapp):
    from xrayui.core import render

    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        dlg.f_username.setText("alice")
        dlg.f_id.setText("s3cret")
        dlg.f_sni.setText("warp.example.com")
        dlg.f_fp.setText("chrome")
        dlg.f_host.setText("warp.example.com")
        dlg.f_path.setText("/masque")
        dlg._masque.f_http_version.setCurrentText("h3")
        dlg._save()
        assert dlg.result() == QDialog.Accepted
        r = dlg.result_profile()
        assert (r.username, r.id, r.sni, r.fp, r.host, r.path) == (
            "alice", "s3cret", "warp.example.com", "chrome",
            "warp.example.com", "/masque")
        assert r.is_valid()
        # serialize + render: the entered fields reach the Xray config
        import json as _json
        cfg = _json.loads(render.build_text(r, "utun99"))
        out = next(o for o in cfg["outbounds"] if o.get("tag") == "proxy")
        ms = out["streamSettings"]["masqueSettings"]
        assert ms["user"] == "alice"
        assert ms["pass"] == "s3cret"
        assert ms["host"] == "warp.example.com"
        assert ms["path"] == "/masque"
        tls = out["streamSettings"]["tlsSettings"]
        assert tls["serverName"] == "warp.example.com"
        assert tls["fingerprint"] == "chrome"
        assert tls["alpn"] == ["h3"]
    finally:
        dlg.close()


def test_masque_one_sided_auth_rejected(qapp, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    try:
        dlg.f_username.setText("alice")  # no password
        dlg._save()
        assert dlg.result() != QDialog.Accepted
        assert len(warnings) == 1
    finally:
        dlg.close()


def test_masque_bad_remote_dns_rejected(qapp, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.f_remote_dns.setText("not-an-ip")
        dlg._save()
        assert dlg.result() != QDialog.Accepted
        assert len(warnings) == 1
    finally:
        dlg.close()


def test_masque_warp_identity_saves(qapp):
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.f_private_key.setText(_DUMMY_PRIV)
        dlg._masque.f_public_key.setText(_DUMMY_PUB)
        dlg._masque.f_addresses.setText("198.51.100.7/32")
        dlg._save()
        assert dlg.result() == QDialog.Accepted
        r = dlg.result_profile()
        assert r.masque_private_key == _DUMMY_PRIV
        assert r.masque_public_key == _DUMMY_PUB
        assert r.masque_addresses == "198.51.100.7/32"
        assert r.is_valid()
    finally:
        dlg.close()


def test_masque_save_clears_reality_vision(qapp):
    p = _masque_profile()
    p.flow = "xtls-rprx-vision"
    p.sid = "deadbeef"
    p.spx = "/"
    p.pqv = "x" * 2603
    dlg = ProfileEditDialog(p)
    try:
        dlg._save()
        assert dlg.result() == QDialog.Accepted
        r = dlg.result_profile()
        assert (r.flow, r.sid, r.spx, r.pqv) == ("", "", "", "")
    finally:
        dlg.close()


def test_switch_to_masque_clears_stale_credentials(qapp):
    p = Profile(name="v", protocol="vless", address="a.example.com", port=443,
                id="11111111-1111-1111-1111-111111111111")
    dlg = ProfileEditDialog(p)
    try:
        assert dlg.f_id.text() == "11111111-1111-1111-1111-111111111111"
        dlg.f_protocol.setCurrentText("masque")
        assert dlg.f_id.text() == ""
        assert dlg.f_username.text() == ""
        # switching back must not clear the user's new entries again
        dlg.f_id.setText("newpass")
        dlg.f_protocol.setCurrentText("vless")
        dlg.f_protocol.setCurrentText("masque")
        assert dlg.f_id.text() == "newpass"
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

# Dummy base64 keys: valid base64 syntax, no real key material.
_DUMMY_PRIV = "ZHVtbXktcHJpdmF0ZS1rZXktMDEyMzQ1Njc4OQ=="
_DUMMY_PUB = "ZHVtbXktcHVibGljLWtleS0wMTIzNDU2Nzg5"
_DUMMY_IDENTITY = ('{"privateKey": "' + _DUMMY_PRIV + '", "publicKey": "'
                   + _DUMMY_PUB + '", "address": ["198.51.100.7/32", '
                   '"2001:db8::5/128"]}')


def test_import_identity_applies_fields(qapp, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        lambda *a, **k: (_DUMMY_IDENTITY, True))

    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_import.click()
        assert dlg._masque.f_private_key.text() == _DUMMY_PRIV
        assert dlg._masque.f_public_key.text() == _DUMMY_PUB
        assert dlg._masque.f_addresses.text() == "198.51.100.7/32, 2001:db8::5/128"
    finally:
        dlg.close()


def test_import_identity_clears_generic_credentials(qapp, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        lambda *a, **k: (_DUMMY_IDENTITY, True))

    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        # A stale basic-auth pair from before the import must not survive.
        dlg.f_username.setText("alice")
        dlg.f_id.setText("s3cret")
        dlg._masque.btn_import.click()
        assert dlg._masque.f_private_key.text() == _DUMMY_PRIV
        assert dlg.f_username.text() == ""
        assert dlg.f_id.text() == ""
        # and the now-consistent WARP-only profile saves
        dlg._save()
        assert dlg.result() == QDialog.Accepted
    finally:
        dlg.close()


def test_masque_warp_plus_basic_auth_rejected(qapp, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.f_private_key.setText(_DUMMY_PRIV)
        dlg._masque.f_public_key.setText(_DUMMY_PUB)
        dlg._masque.f_addresses.setText("198.51.100.7/32")
        dlg.f_username.setText("alice")
        dlg.f_id.setText("s3cret")
        dlg._save()
        assert dlg.result() != QDialog.Accepted
        assert len(warnings) == 1
        assert "auth modes" in warnings[0]
    finally:
        dlg.close()


def _save_raw(dlg, **overrides):
    """Edit the profile through the Raw JSON tab and save from there."""
    import json as _json

    data = dlg._profile.to_dict()
    data.update(overrides)
    dlg.tabs.setCurrentIndex(1)
    dlg.raw.setPlainText(_json.dumps(data))
    dlg._save()


def test_raw_masque_invalid_security_rejected(qapp, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        _save_raw(dlg, security="none")
        assert dlg.result() != QDialog.Accepted
        assert len(warnings) == 1
        assert "incomplete" in warnings[0]
    finally:
        dlg.close()


def test_raw_masque_one_sided_auth_rejected(qapp, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        _save_raw(dlg, username="alice")  # no password
        assert dlg.result() != QDialog.Accepted
        assert len(warnings) == 1
        assert "incomplete" in warnings[0]
    finally:
        dlg.close()


def test_raw_masque_valid_round_trip(qapp):
    p = _masque_profile(address="198.51.100.9")
    p.masque_http_version = "h3"
    p.masque_remote_dns = "1.1.1.1\n9.9.9.9"
    dlg = ProfileEditDialog(p)
    try:
        _save_raw(dlg, network="masque", security="tls", alpn="h3",
                  username="alice", id="s3cret", sni="warp.example.com")
        assert dlg.result() == QDialog.Accepted
        r = dlg.result_profile()
        assert (r.protocol, r.network, r.security, r.masque_http_version) == (
            "masque", "masque", "tls", "h3")
        assert (r.username, r.id, r.sni) == ("alice", "s3cret", "warp.example.com")
        assert r.masque_remote_dns == "1.1.1.1\n9.9.9.9"
        assert r.is_valid()
    finally:
        dlg.close()


def test_import_identity_malformed_does_not_leak(qapp, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    # Valid base64 key, but /48 is not a host prefix: the real parser rejects it.
    bad = ('{"privateKey": "' + _DUMMY_PRIV + '", "publicKey": "' + _DUMMY_PUB
           + '", "address": ["2001:db8::/48"]}')
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        lambda *a, **k: (bad, True))

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile()
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_import.click()
        assert len(warnings) == 1
        # the pasted secret must not be echoed in the warning
        assert _DUMMY_PRIV not in warnings[0]
        assert dlg._masque.f_private_key.text() == ""
    finally:
        dlg.close()


# -- test endpoint --------------------------------------------------------------

def _fake_iface():
    from xrayui.core._net_common import Interface
    return Interface("en0", "192.0.2.1", "192.0.2.254", None)


def _pump_until(qapp, cond, timeout_s=5.0):
    # The probe runs on a QThreadPool thread; its finished signal is queued to
    # the main thread, so pump events until the worker's result is delivered.
    import time

    deadline = time.monotonic() + timeout_s
    while not cond():
        if time.monotonic() > deadline:
            break
        qapp.processEvents()
        time.sleep(0.01)
    return cond()


def _pump_for(qapp, seconds):
    # Pump events for a fixed duration so a queued worker signal is delivered.
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def test_test_endpoint_runs_async_and_reports(qapp, monkeypatch):
    import threading

    from xrayui.core import masque_probe

    seen = {}

    def fake_probe(profile, *, xray_path, timeout=8.0, cancel_event=None,
                   iface_alias=None, health_url=masque_probe.DEFAULT_HEALTH_URL):
        seen["thread"] = threading.current_thread()
        seen["profile"] = profile
        seen["iface"] = iface_alias
        return masque_probe.ProbeResult("198.51.100.9:443", "h2", True, 12.3, "")

    monkeypatch.setattr("xrayui.ui.dialogs.masque_probe.probe_endpoint", fake_probe)
    monkeypatch.setattr("xrayui.ui.dialogs.network.detect_interface",
                        lambda: _fake_iface())
    infos = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a: infos.append(a[2]))
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_test.click()
        assert _pump_until(qapp, lambda: seen.get("thread") is not None)
        assert seen["thread"] is not threading.main_thread()
        snap = seen["profile"]
        assert snap.address == "198.51.100.9"
        assert (snap.protocol, snap.network, snap.security) == (
            "masque", "masque", "tls")
        # the worker got a snapshot, not the dialog's live profile
        assert snap is not dlg._profile
        assert seen["iface"] == "en0"
        assert _pump_until(qapp, lambda: len(infos) == 1)
        assert dlg._masque.btn_test.text() == "Test endpoint"
        assert "12 ms" in infos[0]
    finally:
        dlg.close()


def test_test_endpoint_no_interface(qapp, monkeypatch):

    monkeypatch.setattr("xrayui.ui.dialogs.masque_probe.probe_endpoint",
                        lambda *a, **k: pytest.fail("must not probe"))
    monkeypatch.setattr("xrayui.ui.dialogs.network.detect_interface",
                        lambda: None)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_test.click()
        assert _pump_until(qapp, lambda: len(warnings) == 1)
        assert "interface" in warnings[0]
        assert dlg._masque.btn_test.text() == "Test endpoint"
    finally:
        dlg.close()


def test_test_endpoint_cancelable(qapp, monkeypatch):
    from xrayui.core import masque_probe

    seen = {}

    def fake_probe(profile, *, xray_path, timeout=8.0, cancel_event=None,
                   iface_alias=None, health_url=masque_probe.DEFAULT_HEALTH_URL):
        seen["cancel"] = cancel_event
        # Block until the test cancels, so the probe is genuinely in flight.
        cancel_event.wait(5.0)
        return masque_probe.ProbeResult("198.51.100.9:443", "h2",
                                        False, None, "cancelled")

    monkeypatch.setattr("xrayui.ui.dialogs.masque_probe.probe_endpoint", fake_probe)
    monkeypatch.setattr("xrayui.ui.dialogs.network.detect_interface",
                        lambda: _fake_iface())
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_test.click()
        assert _pump_until(qapp, lambda: seen.get("cancel") is not None)
        # the button stays clickable so the user can cancel
        assert dlg._masque.btn_test.isEnabled()
        assert dlg._masque.btn_test.text() == "Cancel"
        seen["cancel"].set()
        assert _pump_until(qapp, lambda: dlg._masque.btn_test.text() == "Test endpoint")
    finally:
        dlg.close()


def test_test_endpoint_cancel_on_reject(qapp, monkeypatch):
    from xrayui.core import masque_probe

    def fake_probe(profile, *, xray_path, timeout=8.0, cancel_event=None,
                   iface_alias=None, health_url=masque_probe.DEFAULT_HEALTH_URL):
        raise AssertionError("must not be reached")

    monkeypatch.setattr("xrayui.ui.dialogs.masque_probe.probe_endpoint", fake_probe)
    monkeypatch.setattr("xrayui.ui.dialogs.network.detect_interface",
                        lambda: _fake_iface())
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_test.click()
        assert dlg._probe_cancel is not None
        dlg.reject()
        assert dlg._probe_cancel.is_set()
    finally:
        dlg.close()


def test_test_endpoint_worker_error_shows_fixed_message(qapp, monkeypatch):
    from xrayui.core import masque_probe

    def fake_probe(profile, *, xray_path, timeout=8.0, cancel_event=None,
                   iface_alias=None, health_url=masque_probe.DEFAULT_HEALTH_URL):
        raise RuntimeError("internal detail / secret=TOPSECRET")

    monkeypatch.setattr("xrayui.ui.dialogs.masque_probe.probe_endpoint", fake_probe)
    monkeypatch.setattr("xrayui.ui.dialogs.network.detect_interface",
                        lambda: _fake_iface())
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_test.click()
        assert _pump_until(qapp, lambda: len(warnings) == 1)
        # the raw exception text (with the secret) must not be surfaced
        assert "TOPSECRET" not in warnings[0]
        assert "internal detail" not in warnings[0]
        assert warnings[0] == "The endpoint test could not be run."
    finally:
        dlg.close()


def test_test_endpoint_translates_error_categories(qapp, monkeypatch):
    from xrayui.core import masque_probe

    def fake_probe(profile, *, xray_path, timeout=8.0, cancel_event=None,
                   iface_alias=None, health_url=masque_probe.DEFAULT_HEALTH_URL):
        return masque_probe.ProbeResult("198.51.100.9:443", "h2",
                                        False, None, "connection failed")

    monkeypatch.setattr("xrayui.ui.dialogs.masque_probe.probe_endpoint", fake_probe)
    monkeypatch.setattr("xrayui.ui.dialogs.network.detect_interface",
                        lambda: _fake_iface())
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_test.click()
        assert _pump_until(qapp, lambda: len(warnings) == 1)
        assert warnings[0] == "The endpoint could not be reached."
    finally:
        dlg.close()


def test_test_endpoint_late_success_after_close_is_dropped(qapp, monkeypatch):
    from xrayui.core import masque_probe

    def fake_probe(profile, *, xray_path, timeout=8.0, cancel_event=None,
                   iface_alias=None, health_url=masque_probe.DEFAULT_HEALTH_URL):
        cancel_event.wait(5.0)
        # A success that arrives only after the dialog is already closed.
        return masque_probe.ProbeResult("198.51.100.9:443", "h2", True, 9.0, "")

    monkeypatch.setattr("xrayui.ui.dialogs.masque_probe.probe_endpoint", fake_probe)
    monkeypatch.setattr("xrayui.ui.dialogs.network.detect_interface",
                        lambda: _fake_iface())
    infos = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a: infos.append(a[2]))
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    dlg._masque.btn_test.click()
    assert _pump_until(qapp, lambda: dlg._probe_cancel is not None)
    # Close the dialog while the probe is in flight; the late success must not
    # pop up a dialog on a closed window.
    dlg.close()
    assert dlg._probe_cancel.is_set()
    _pump_for(qapp, 1.0)  # let the late signal land
    assert infos == []


def test_test_endpoint_late_error_after_save_is_dropped(qapp, monkeypatch):
    from xrayui.core import masque_probe

    def fake_probe(profile, *, xray_path, timeout=8.0, cancel_event=None,
                   iface_alias=None, health_url=masque_probe.DEFAULT_HEALTH_URL):
        cancel_event.wait(5.0)
        return masque_probe.ProbeResult("198.51.100.9:443", "h2",
                                        False, None, "boom")

    monkeypatch.setattr("xrayui.ui.dialogs.masque_probe.probe_endpoint", fake_probe)
    monkeypatch.setattr("xrayui.ui.dialogs.network.detect_interface",
                        lambda: _fake_iface())
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile(address="198.51.100.9")
    dlg = ProfileEditDialog(p)
    dlg._masque.btn_test.click()
    assert _pump_until(qapp, lambda: dlg._probe_cancel is not None)
    # Save (accept) also funnels through done(): it must cancel and mark closed.
    dlg._save()
    assert dlg.result() == QDialog.Accepted
    assert dlg._probe_cancel.is_set()
    _pump_for(qapp, 1.0)  # let the late signal land
    assert warnings == []


def test_test_endpoint_snapshot_clears_reality(qapp, monkeypatch):
    from xrayui.core import masque_probe

    seen = {}

    def fake_probe(profile, *, xray_path, timeout=8.0, cancel_event=None,
                   iface_alias=None, health_url=masque_probe.DEFAULT_HEALTH_URL):
        seen["profile"] = profile
        return masque_probe.ProbeResult("198.51.100.9:443", "h2", True, 1.0, "")

    monkeypatch.setattr("xrayui.ui.dialogs.masque_probe.probe_endpoint", fake_probe)
    monkeypatch.setattr("xrayui.ui.dialogs.network.detect_interface",
                        lambda: _fake_iface())
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    p = _masque_profile(address="198.51.100.9")
    p.flow = "xtls-rprx-vision"
    p.sid = "deadbeef"
    p.spx = "/"
    p.pqv = "x" * 2603
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_test.click()
        assert _pump_until(qapp, lambda: "profile" in seen)
        snap = seen["profile"]
        assert (snap.flow, snap.sid, snap.spx, snap.pqv) == ("", "", "", "")
    finally:
        dlg.close()


def test_test_endpoint_without_address_refused(qapp, monkeypatch):

    monkeypatch.setattr("xrayui.ui.dialogs.masque_probe.probe_endpoint",
                        lambda *a, **k: pytest.fail("must not probe"))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))
    p = _masque_profile(address="")
    dlg = ProfileEditDialog(p)
    try:
        dlg._masque.btn_test.click()
        assert warnings == ["Address is required."]
        assert dlg._masque.btn_test.text() == "Test endpoint"
    finally:
        dlg.close()


# -- translations ---------------------------------------------------------------

def test_masque_strings_translated():
    set_language("fa")
    for source in ("HTTP version", "Public key", "Tunnel addresses",
                   "Remote DNS", "Import identity…", "MASQUE",
                   "Test endpoint", "Remote DNS must be literal IP addresses.",
                   "This MASQUE profile is incomplete."):
        assert tr(source) != source
    # parameterized results keep their values after translation
    assert "h2" in tr("Endpoint answered over {v} in {ms} ms.", v="h2", ms=12)
    assert "12" in tr("Endpoint answered over {v} in {ms} ms.", v="h2", ms=12)
    set_language("en")
