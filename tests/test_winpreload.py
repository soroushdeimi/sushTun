"""winpreload: our C++ runtime DLLs bind before any Qt import (Windows only)."""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from xrayui import winpreload


def _win32_frozen(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def _fake_windll(monkeypatch, fail=()):
    calls = []

    def fake(path):
        calls.append(path)
        if Path(path).name in fail:
            raise OSError("simulated load failure")
        return object()

    monkeypatch.setattr(ctypes, "WinDLL", fake, raising=False)
    return calls


def test_not_win32_returns_empty_and_never_loads(monkeypatch, tmp_path):
    (tmp_path / "msvcp140.dll").write_bytes(b"x")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    calls = _fake_windll(monkeypatch)
    assert winpreload.preload_runtime(tmp_path) == []
    assert calls == []


def test_win32_but_not_frozen_returns_empty(monkeypatch, tmp_path):
    (tmp_path / "msvcp140.dll").write_bytes(b"x")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    calls = _fake_windll(monkeypatch)
    assert winpreload.preload_runtime(tmp_path) == []
    assert calls == []


def test_loads_existing_files_in_tuple_order_by_full_path(monkeypatch, tmp_path):
    (tmp_path / "msvcp140.dll").write_bytes(b"x")
    (tmp_path / "MSVCP140_1.dll").write_bytes(b"x")  # upper-case on disk
    (tmp_path / "vcruntime140.dll").write_bytes(b"x")
    _win32_frozen(monkeypatch)
    calls = _fake_windll(monkeypatch)
    monkeypatch.setattr(os, "add_dll_directory", lambda p: None, raising=False)
    assert winpreload.preload_runtime(tmp_path) == [
        "vcruntime140.dll", "msvcp140.dll", "msvcp140_1.dll"]
    assert calls == [
        str(tmp_path / "vcruntime140.dll"),
        str(tmp_path / "msvcp140.dll"),
        str(tmp_path / "MSVCP140_1.dll"),
    ]


def test_missing_files_are_skipped(monkeypatch, tmp_path):
    (tmp_path / "msvcp140.dll").write_bytes(b"x")
    _win32_frozen(monkeypatch)
    calls = _fake_windll(monkeypatch)
    monkeypatch.setattr(os, "add_dll_directory", lambda p: None, raising=False)
    assert winpreload.preload_runtime(tmp_path) == ["msvcp140.dll"]
    assert calls == [str(tmp_path / "msvcp140.dll")]


def test_load_failure_on_one_file_does_not_stop_the_others(monkeypatch, tmp_path):
    (tmp_path / "vcruntime140.dll").write_bytes(b"x")
    (tmp_path / "msvcp140.dll").write_bytes(b"x")
    (tmp_path / "concrt140.dll").write_bytes(b"x")
    _win32_frozen(monkeypatch)
    calls = _fake_windll(monkeypatch, fail={"msvcp140.dll"})
    monkeypatch.setattr(os, "add_dll_directory", lambda p: None, raising=False)
    assert winpreload.preload_runtime(tmp_path) == [
        "vcruntime140.dll", "concrt140.dll"]
    assert len(calls) == 3  # the failing one was attempted, then skipped


def test_add_dll_directory_failure_is_ignored(monkeypatch, tmp_path):
    (tmp_path / "msvcp140.dll").write_bytes(b"x")
    _win32_frozen(monkeypatch)
    _fake_windll(monkeypatch)

    def boom(p):
        raise OSError("simulated")

    monkeypatch.setattr(os, "add_dll_directory", boom, raising=False)
    assert winpreload.preload_runtime(tmp_path) == ["msvcp140.dll"]


def test_base_none_uses_meipass(monkeypatch, tmp_path):
    (tmp_path / "msvcp140.dll").write_bytes(b"x")
    _win32_frozen(monkeypatch)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    calls = _fake_windll(monkeypatch)
    monkeypatch.setattr(os, "add_dll_directory", lambda p: None, raising=False)
    assert winpreload.preload_runtime() == ["msvcp140.dll"]
    assert calls == [str(tmp_path / "msvcp140.dll")]


def test_app_main_preloads_before_importing_main():
    text = (Path(__file__).resolve().parent.parent / "app_main.py").read_text()
    assert "preload_runtime" in text
    assert text.index("preload_runtime") < text.index("from xrayui.__main__")
