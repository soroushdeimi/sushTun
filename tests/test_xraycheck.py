from xrayui import paths
from xrayui.core import xraycheck


def _skip_if_no_binary():
    import pytest
    if not paths.xray_exe().exists():
        pytest.skip("bundled xray binary not present")


def test_a_valid_rule_passes(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    error = xraycheck.check_rules(
        [{"type": "field", "domain": ["geosite:google"], "outboundTag": "direct"}]
    )
    assert error is None


def test_an_unknown_geosite_category_fails_with_a_short_reason(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    error = xraycheck.check_rules(
        [{"type": "field", "domain": ["geosite:not-a-real-category-xyz"], "outboundTag": "direct"}]
    )
    assert error is not None
    assert "not-a-real-category-xyz" in error.upper() or "NOT-A-REAL-CATEGORY-XYZ" in error
    assert "\n" not in error  # a short reason, not the whole multi-line log


def test_check_config_validates_a_complete_rendered_config(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    from xrayui.core import render
    from xrayui.core.importer import parse_vless
    text = render.build_text(
        parse_vless("vless://u@1.2.3.4:443?type=tcp&security=none#x"),
        "lo", include_tun=False,
    )
    assert xraycheck.check_config(text) is None


def test_check_config_reports_a_short_reason_for_a_bad_config(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    import json
    bad = json.dumps({
        "routing": {"rules": [{"type": "field",
                               "domain": ["geosite:not-a-real-category-xyz"],
                               "outboundTag": "direct"}]},
        "outbounds": [{"tag": "direct", "protocol": "freedom"}],
    })
    error = xraycheck.check_config(bad)
    assert error is not None
    assert "\n" not in error


def test_concurrent_calls_use_separate_config_files(tmp_path, monkeypatch):
    # A geo update and a routing dialog Save could both validate at once;
    # each call must get its own file rather than sharing a fixed name.
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    import threading

    errors: list[str | None] = [None, None]

    def run(i: int, ok: bool) -> None:
        domain = "geosite:google" if ok else "geosite:not-a-real-category-xyz"
        errors[i] = xraycheck.check_rules(
            [{"type": "field", "domain": [domain], "outboundTag": "direct"}]
        )

    threads = [threading.Thread(target=run, args=(0, True)),
               threading.Thread(target=run, args=(1, False))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors[0] is None
    assert errors[1] is not None
    # No leftover config files from either call.
    assert list(tmp_path.glob("xraycheck-*.json")) == []
