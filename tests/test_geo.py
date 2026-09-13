import pytest

from xrayui import paths
from xrayui.core import geo

REAL_GEOIP = paths.xray_exe().parent / "geoip.dat"
REAL_GEOSITE = paths.xray_exe().parent / "geosite.dat"


def _skip_if_no_binary_or_real_geo_data():
    if not paths.xray_exe().exists() or not REAL_GEOIP.exists() or not REAL_GEOSITE.exists():
        pytest.skip("bundled xray binary or geo data not present")


def _setup(tmp_path, monkeypatch, real: bool = False) -> None:
    if real:
        # Resolve the real binary's path *before* base_dir() is overridden
        # below -- xray_exe() falls back to base_dir() in a dev run, so
        # computing it after the patch would resolve to tmp_path/xray.
        real_exe = paths.xray_exe()
        monkeypatch.setattr(geo.paths, "xray_exe", lambda: real_exe)
    # geo.paths, xraycheck.paths and app_settings.paths are all the same
    # xrayui.paths module object, so patching base_dir once covers all of
    # them (state_dir() is derived from base_dir() too).
    monkeypatch.setattr(geo.paths, "base_dir", lambda: tmp_path)
    (tmp_path / "geo").mkdir()
    if real:
        geoip, geosite = REAL_GEOIP.read_bytes(), REAL_GEOSITE.read_bytes()
    else:
        # Only used by tests that fail before ever reading these bytes.
        geoip, geosite = b"placeholder-geoip", b"placeholder-geosite"
    (tmp_path / "geo" / "geoip.dat").write_bytes(geoip)
    (tmp_path / "geo" / "geosite.dat").write_bytes(geosite)


def test_successful_update_swaps_the_geo_directory(tmp_path, monkeypatch):
    _skip_if_no_binary_or_real_geo_data()
    _setup(tmp_path, monkeypatch, real=True)
    real_geoip = REAL_GEOIP.read_bytes()
    real_geosite = REAL_GEOSITE.read_bytes()

    def fetch(url):
        return real_geoip if "geoip" in url else real_geosite

    geo.update("Loyalsoldier", fetch=fetch)

    assert (tmp_path / "geo" / "geoip.dat").exists()
    assert (tmp_path / "geo" / "geosite.dat").exists()
    assert not (tmp_path / "geo.new").exists()
    assert not (tmp_path / "geo.old").exists()


def test_failed_validation_keeps_the_old_files_and_removes_geo_new(tmp_path, monkeypatch):
    _skip_if_no_binary_or_real_geo_data()
    _setup(tmp_path, monkeypatch, real=True)
    before = (tmp_path / "geo" / "geoip.dat").read_bytes()

    def fetch(url):
        return b"not a real geo dat file, just padding to clear the size floor" * 2000

    with pytest.raises(geo.GeoUpdateError):
        geo.update("Loyalsoldier", fetch=fetch)

    assert (tmp_path / "geo" / "geoip.dat").read_bytes() == before
    assert not (tmp_path / "geo.new").exists()


def test_too_small_a_download_is_rejected_before_validation(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    with pytest.raises(geo.GeoUpdateError, match="truncated"):
        geo.update("Loyalsoldier", fetch=lambda url: b"tiny")

    assert not (tmp_path / "geo.new").exists()


def test_unknown_source_raises_without_fetching(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    with pytest.raises(geo.GeoUpdateError):
        geo.update("NotASource", fetch=lambda url: (_ for _ in ()).throw(
            AssertionError("should not fetch")))


def test_garbage_over_min_size_is_rejected_even_with_zero_user_rules(tmp_path, monkeypatch):
    # A user with every routing toggle off produces zero rules from
    # build_rules(); without baseline geosite:private/geoip:private rules,
    # a truncated-but->100KB download would sail through unvalidated
    # because nothing would ever ask Xray to actually parse either file.
    _skip_if_no_binary_or_real_geo_data()
    _setup(tmp_path, monkeypatch, real=True)
    import json
    (tmp_path / "settings.json").write_text(json.dumps({
        "routing": {"block_ads": False, "direct_iran": False, "direct_russia": False,
                    "direct_china": False, "direct_private": False, "low_usage": False,
                    "mode": "simple", "sets": []},
    }), encoding="utf-8")

    from xrayui.core import routing
    from xrayui.core import settings as app_settings
    assert routing.build_rules(app_settings.load()["routing"]) == []

    def fetch(url):
        return b"garbage padding, not a real geo file at all " * 3000  # > 100 KB

    with pytest.raises(geo.GeoUpdateError):
        geo.update("Loyalsoldier", fetch=fetch)
    assert not (tmp_path / "geo.new").exists()


def test_default_fetch_rejects_a_content_length_mismatch(monkeypatch):
    import http.server
    import threading

    body = b"short body"

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", str(len(body) + 500))  # lies
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(geo.GeoUpdateError, match="incomplete"):
            geo._default_fetch(f"http://127.0.0.1:{port}/geoip.dat", timeout=5)
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


def test_asset_dir_prefers_geo_dir_only_when_both_files_are_present(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "resource_dir", lambda: tmp_path)
    (tmp_path / "geoip.dat").write_bytes(b"bundled-geoip")
    (tmp_path / "geosite.dat").write_bytes(b"bundled-geosite")

    assert paths.asset_dir() == tmp_path  # falls back to the bundled pair

    geo_dir = tmp_path / "geo"
    geo_dir.mkdir()
    (geo_dir / "geoip.dat").write_bytes(b"updated-geoip")
    # geosite.dat missing from geo/: must NOT prefer a partial pair
    assert paths.asset_dir() == tmp_path

    (geo_dir / "geosite.dat").write_bytes(b"updated-geosite")
    assert paths.asset_dir() == geo_dir


# -- is_due ------------------------------------------------------------
def test_is_due_off_when_hours_is_zero():
    assert geo.is_due(0, 0, now=1_000_000) is False
    assert geo.is_due(1_000_000, 0, now=2_000_000) is False  # even if very stale


def test_is_due_never_updated_is_due_once_auto_update_is_on():
    assert geo.is_due(0, 6, now=1_000_000) is True


def test_is_due_not_yet_due():
    last = 1_000_000
    assert geo.is_due(last, 6, now=last + 5 * 3600) is False


def test_is_due_exactly_due():
    last = 1_000_000
    assert geo.is_due(last, 6, now=last + 6 * 3600) is True
    assert geo.is_due(last, 6, now=last + 7 * 3600) is True
