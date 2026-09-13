"""Backup/restore: contents, exclusions, and the restore safety checks."""
from __future__ import annotations

import json
import zipfile

import pytest

from xrayui import paths
from xrayui.core import backup
from xrayui.core.profiles import Profile, ProfileStore
from xrayui.core.subscription import Subscription, SubscriptionStore


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    paths.ensure_dirs()
    return tmp_path


def test_backup_contains_the_expected_files_and_excludes_the_rest(tmp_path, monkeypatch):
    base = _setup(tmp_path, monkeypatch)
    (base / "settings.json").write_text("{}", encoding="utf-8")
    profiles = ProfileStore()
    p = profiles.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    profiles.set_active(p.uid)
    subs = SubscriptionStore()
    subs.save(Subscription(name="s", url="https://x"))
    (base / "profile_stats.json").write_text("{}", encoding="utf-8")
    # Things that must NOT end up in the backup.
    (base / "geo").mkdir(exist_ok=True)
    (base / "geo" / "geoip.dat").write_bytes(b"x")
    (base / "state").mkdir(exist_ok=True)
    (base / "state" / "something").write_text("x", encoding="utf-8")
    (base / "xray.log").write_text("log", encoding="utf-8")
    (base / "config.runtime.json").write_text("{}", encoding="utf-8")

    dest = tmp_path / "out.zip"
    backup.backup(dest)

    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))

    assert manifest["app"] == "sushTun"
    assert "version" in manifest and "created" in manifest
    assert "settings.json" in names
    assert "profiles/active.txt" in names
    assert "profiles/subscriptions.json" in names
    assert f"profiles/{p.uid}.json" in names
    assert "profile_stats.json" in names
    assert not any(n.startswith("geo/") for n in names)
    assert not any(n.startswith("state/") for n in names)
    assert "xray.log" not in names
    assert "config.runtime.json" not in names


def test_restore_round_trips_everything(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr(paths, "base_dir", lambda: src)
    paths.ensure_dirs()
    (src / "settings.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    profiles = ProfileStore()
    p = profiles.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    profiles.set_active(p.uid)
    subs = SubscriptionStore()
    subs.save(Subscription(name="s", url="https://x"))
    (src / "profile_stats.json").write_text(json.dumps({"x": 1}), encoding="utf-8")

    dest = tmp_path / "out.zip"
    backup.backup(dest)

    restored = tmp_path / "restored"
    restored.mkdir()
    monkeypatch.setattr(paths, "base_dir", lambda: restored)
    paths.ensure_dirs()
    backup.restore(dest)

    assert json.loads((restored / "settings.json").read_text()) == {"a": 1}
    assert (restored / "profiles" / f"{p.uid}.json").exists()
    assert (restored / "profiles" / "active.txt").read_text() == p.uid
    assert (restored / "profiles" / "subscriptions.json").exists()
    assert json.loads((restored / "profile_stats.json").read_text()) == {"x": 1}


def test_restore_replaces_the_server_list_wholesale(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr(paths, "base_dir", lambda: src)
    paths.ensure_dirs()
    ProfileStore().save(Profile(name="only", address="a.example.com", port=443, id="u"))
    dest = tmp_path / "out.zip"
    backup.backup(dest)

    restored = tmp_path / "restored"
    restored.mkdir()
    monkeypatch.setattr(paths, "base_dir", lambda: restored)
    paths.ensure_dirs()
    stale = ProfileStore().save(Profile(name="stale", address="b.example.com", port=443, id="u2"))
    assert (restored / "profiles" / f"{stale.uid}.json").exists()

    backup.restore(dest)

    assert not (restored / "profiles" / f"{stale.uid}.json").exists()
    remaining = list((restored / "profiles").glob("*.json"))
    names = [json.loads(p.read_text())["name"] for p in remaining
            if p.name != "subscriptions.json"]
    assert names == ["only"]


def test_restore_rejects_zip_slip(tmp_path, monkeypatch):
    base = _setup(tmp_path, monkeypatch)
    (base / "settings.json").write_text(json.dumps({"marker": "original"}), encoding="utf-8")
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"app": "sushTun"}))
        zf.writestr("../../etc/passwd", "evil")

    with pytest.raises(ValueError):
        backup.restore(evil)
    assert json.loads((base / "settings.json").read_text()) == {"marker": "original"}


def test_restore_rejects_an_unexpected_file(tmp_path, monkeypatch):
    base = _setup(tmp_path, monkeypatch)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"app": "sushTun"}))
        zf.writestr("xray.log", "not part of a backup")
    with pytest.raises(ValueError):
        backup.restore(bad)
    assert not (base / "xray.log").exists()


def test_restore_rejects_a_foreign_manifest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    foreign = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"app": "SomeOtherApp"}))
    with pytest.raises(ValueError):
        backup.restore(foreign)


def test_restore_rejects_a_missing_manifest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    no_manifest = tmp_path / "no_manifest.zip"
    with zipfile.ZipFile(no_manifest, "w") as zf:
        zf.writestr("settings.json", "{}")
    with pytest.raises(ValueError):
        backup.restore(no_manifest)


def test_restore_a_corrupt_zip_changes_nothing(tmp_path, monkeypatch):
    base = _setup(tmp_path, monkeypatch)
    (base / "settings.json").write_text(json.dumps({"marker": "original"}), encoding="utf-8")
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"not a zip file at all, just garbage bytes")

    with pytest.raises(ValueError):
        backup.restore(corrupt)
    assert json.loads((base / "settings.json").read_text()) == {"marker": "original"}


def test_restore_rejects_corrupt_json_inside_an_otherwise_valid_zip(tmp_path, monkeypatch):
    base = _setup(tmp_path, monkeypatch)
    (base / "settings.json").write_text(json.dumps({"marker": "original"}), encoding="utf-8")
    bad_json = tmp_path / "bad_json.zip"
    with zipfile.ZipFile(bad_json, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"app": "sushTun"}))
        zf.writestr("settings.json", "{not valid json")

    with pytest.raises(ValueError):
        backup.restore(bad_json)
    assert json.loads((base / "settings.json").read_text()) == {"marker": "original"}
