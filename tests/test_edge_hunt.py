"""Edge-case bugs pinned by a targeted hunt.

Each test asserts the CORRECT behaviour and is marked xfail(strict) so it
turns red the day the bug is fixed, which is the cue to drop the marker.
"""
from __future__ import annotations

import base64
import json

import pytest

from xrayui import paths
from xrayui.core import dns, importer, routing, routing_io, settings
from xrayui.core import subscription as sub_mod
from xrayui.core.profiles import Profile, ProfileStore

UID = "11111111-1111-1111-1111-111111111111"
VLESS = f"vless://{UID}@example.com:443?security=none#n"
WG_CONF = ("[Interface]\nPrivateKey = aaaa\nAddress = 10.0.0.2/32\n"
           "[Peer]\nPublicKey = bbbb\nEndpoint = {}\nAllowedIPs = 0.0.0.0/0\n")


def _vmess(port) -> str:
    data = {"add": "e.com", "port": port, "id": UID}
    return "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    return tmp_path


# 1
@pytest.mark.xfail(strict=True, reason="BUG: parse_share_text lets ValueError escape for a "
                   "WireGuard .conf with a bad or missing Endpoint")
@pytest.mark.parametrize("endpoint", ["1.2.3.4:abc", ""])
def test_bad_wg_conf_is_skipped_not_raised(endpoint):
    assert importer.parse_share_text(WG_CONF.format(endpoint)) == []


# 2
@pytest.mark.xfail(strict=True, reason="BUG: a leading BOM (Notepad files) makes every share "
                   "link, base64 body and wg .conf import as nothing")
@pytest.mark.parametrize("body", [VLESS, base64.b64encode(VLESS.encode()).decode()])
def test_share_text_with_bom_imports(body):
    assert len(importer.parse_share_text("﻿" + body)) == 1


@pytest.mark.xfail(strict=True, reason="BUG: a BOM-prefixed routing JSON file imports as nothing")
def test_routing_import_with_bom():
    text = "﻿" + json.dumps([{"outboundTag": "direct", "domain": ["a.com"]}])
    sets, _ = routing_io.import_rules(text)
    assert sets


# 3
@pytest.mark.xfail(strict=True, reason="BUG: out-of-range server ports (0, 65536, -1) are "
                   "accepted from a vmess JSON link and a wg .conf endpoint")
@pytest.mark.parametrize("text", [_vmess(65536), _vmess(-1), _vmess(0),
                                  WG_CONF.format("1.2.3.4:99999")])
def test_out_of_range_server_port_is_rejected(text):
    assert importer.parse_share_text(text) == []


# 4
@pytest.mark.xfail(strict=True, reason="BUG: routing rule ports above 65535 pass through and "
                   "make Xray refuse to start")
@pytest.mark.parametrize("port", ["99999", "0", "70000-80000"])
def test_rule_port_out_of_range_is_dropped(port):
    out = routing.convert_user_rule({"enabled": True, "outbound": "direct",
                                     "port": port, "domain": ["x.com"]})
    assert all(r.get("port") != port for r in out)


# 5
@pytest.mark.xfail(strict=True, reason="BUG: DNS servers with a scheme accept any port text "
                   "and unbalanced brackets")
@pytest.mark.parametrize("entry", ["udp://8.8.8.8:99999", "udp://8.8.8.8:abc",
                                   "tcp://1.1.1.1:0", "udp://[::1"])
def test_dns_scheme_server_with_bad_port_is_rejected(entry):
    assert dns.validate_server(entry) != ""


# 6
@pytest.mark.xfail(strict=True, reason="BUG: settings.load raises TypeError when "
                   "schema_version is not an int")
@pytest.mark.parametrize("value", ['"x"', "[]"])
def test_settings_with_non_int_schema_version_loads(base, value):
    (base / "settings.json").write_text(f'{{"schema_version": {value}}}', encoding="utf-8")
    assert isinstance(settings.load(), dict)


# 7
@pytest.mark.xfail(strict=True, reason="BUG: ProfileStore.get/active raise on an empty, "
                   "truncated or non-object active profile file (list() skips them)")
@pytest.mark.parametrize("content", ["", '{"name": "x", "por', "[]"])
def test_active_profile_with_corrupt_file_is_none(base, content):
    store = ProfileStore()
    store.dir.mkdir(parents=True, exist_ok=True)
    (store.dir / "abc.json").write_text(content, encoding="utf-8")
    store.set_active("abc")
    assert store.active() is None


# 8
@pytest.mark.xfail(strict=True, reason="BUG: one profile file with a null/non-string name "
                   "makes ProfileStore.list raise, emptying the whole server list")
@pytest.mark.parametrize("name", ["null", "5", '["a"]'])
def test_profile_list_survives_a_non_string_name(base, name):
    store = ProfileStore()
    kept = store.save(Profile(name="a", address="x", port=1, id="y"))
    (store.dir / "bad.json").write_text(f'{{"name": {name}}}', encoding="utf-8")
    assert kept.uid in [p.uid for p in store.list()]


# 9
@pytest.mark.xfail(strict=True, reason="BUG: SubscriptionStore.list raises on a subscriptions "
                   "file that is an object or holds non-object / mistyped entries")
@pytest.mark.parametrize("text", ['{"a": 1}', '["a"]', "[null]", '[{"usage": "x"}]',
                                  '[{"profile_uids": 5}]'])
def test_subscription_list_survives_wrong_shapes(base, text):
    store = sub_mod.SubscriptionStore()
    store.file.parent.mkdir(parents=True, exist_ok=True)
    store.file.write_text(text, encoding="utf-8")
    assert isinstance(store.list(), list)


# 10
@pytest.mark.xfail(strict=True, reason="BUG: the profile editor's raw JSON tab raises "
                   "TypeError when the JSON is not an object")
@pytest.mark.parametrize("raw", ["[]", "null", "5"])
def test_edit_dialog_raw_json_must_be_an_object(raw, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    from xrayui.ui.dialogs import ProfileEditDialog

    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    dlg = ProfileEditDialog(Profile(name="a", address="x", id="y"))
    dlg.tabs.setCurrentIndex(1)
    dlg.raw.setPlainText(raw)
    dlg._save()  # must warn and return, not raise
    dlg.close()
