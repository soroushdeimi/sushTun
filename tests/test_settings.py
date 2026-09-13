import json

from xrayui.core import settings as app_settings


def _load_from(tmp_path, monkeypatch, data: dict) -> dict:
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    return app_settings.load()


def test_legacy_file_without_schema_version_gets_stamped(tmp_path, monkeypatch):
    got = _load_from(tmp_path, monkeypatch, {"ping_target": "9.9.9.9"})
    assert got["schema_version"] == app_settings.SCHEMA_VERSION
    assert got["ping_target"] == "9.9.9.9"


def test_file_already_at_current_version_is_unchanged(tmp_path, monkeypatch):
    got = _load_from(
        tmp_path, monkeypatch,
        {"schema_version": app_settings.SCHEMA_VERSION, "ping_target": "1.2.3.4"},
    )
    assert got["schema_version"] == app_settings.SCHEMA_VERSION
    assert got["ping_target"] == "1.2.3.4"


def test_stale_unknown_keys_are_still_dropped(tmp_path, monkeypatch):
    got = _load_from(tmp_path, monkeypatch, {"no_longer_a_setting": True})
    assert "no_longer_a_setting" not in got


def test_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    got = app_settings.load()
    assert got == app_settings.DEFAULTS
    assert got is not app_settings.DEFAULTS
