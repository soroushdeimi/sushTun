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
