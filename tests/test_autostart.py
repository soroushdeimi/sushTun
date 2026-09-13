"""Start-at-login: polkit rule + desktop file (Linux, .deb only), scheduled
task (Windows). No real system state is ever touched -- every filesystem
path and subprocess call is monkeypatched.
"""
from __future__ import annotations

import os
import types

import pytest

from xrayui.core import autostart


# -- polkit rule / desktop file text -----------------------------------------
def test_polkit_rule_text_for_a_given_user():
    text = autostart.polkit_rule_text("alice")
    assert 'action.id == "io.github.soroushdeimi.sushtun"' in text
    assert 'subject.user == "alice"' in text
    assert "subject.local" in text
    assert "subject.active" in text
    assert "polkit.Result.YES" in text
    # Never the broad exec grant -- that would let anyone run any command.
    assert "org.freedesktop.policykit.exec" not in text


def test_polkit_rule_text_refuses_a_username_with_a_quote():
    # A crafted account name must never be interpolated raw into the JS rule.
    with pytest.raises(ValueError):
        autostart.polkit_rule_text('alice" || true; //')


def test_desktop_file_text_points_at_the_installed_exe_with_autostart_flag():
    text = autostart._desktop_file_text()
    assert "Exec=/opt/sushtun/sushtun --autostart" in text
    assert "Type=Application" in text


# -- _real_user: PKEXEC_UID vs SUDO_UID vs neither ---------------------------
def test_real_user_prefers_pkexec_uid(monkeypatch):
    monkeypatch.setenv("PKEXEC_UID", "1000")
    monkeypatch.setenv("SUDO_UID", "1001")
    monkeypatch.setattr(
        "pwd.getpwuid", lambda uid: types.SimpleNamespace(pw_name="alice") if uid == 1000 else None
    )
    assert autostart._real_user() == "alice"


def test_real_user_falls_back_to_sudo_uid(monkeypatch):
    monkeypatch.delenv("PKEXEC_UID", raising=False)
    monkeypatch.setenv("SUDO_UID", "1001")
    monkeypatch.setattr(
        "pwd.getpwuid", lambda uid: types.SimpleNamespace(pw_name="bob") if uid == 1001 else None
    )
    assert autostart._real_user() == "bob"


def test_real_user_none_when_neither_is_set(monkeypatch):
    monkeypatch.delenv("PKEXEC_UID", raising=False)
    monkeypatch.delenv("SUDO_UID", raising=False)
    assert autostart._real_user() is None


# -- is_supported -------------------------------------------------------------
def test_is_supported_macos_unsupported(monkeypatch):
    monkeypatch.setattr(autostart, "IS_MAC", True)
    monkeypatch.setattr(autostart, "IS_WIN", False)
    ok, reason = autostart.is_supported()
    assert ok is False
    assert "macOS" in reason


def test_is_supported_windows_always_true(monkeypatch):
    monkeypatch.setattr(autostart, "IS_WIN", True)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    ok, reason = autostart.is_supported()
    assert ok is True


def test_is_supported_linux_portable_build_unsupported(monkeypatch):
    monkeypatch.setattr(autostart, "IS_WIN", False)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    monkeypatch.setattr(autostart.paths, "installed", lambda: False)
    ok, reason = autostart.is_supported()
    assert ok is False
    assert ".deb" in reason


def test_is_supported_linux_installed_but_no_real_user(monkeypatch):
    monkeypatch.setattr(autostart, "IS_WIN", False)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    monkeypatch.setattr(autostart.paths, "installed", lambda: True)
    monkeypatch.setattr(autostart, "_real_user", lambda: None)
    ok, reason = autostart.is_supported()
    assert ok is False
    assert "user" in reason.lower()


def test_is_supported_linux_installed_with_a_real_user(monkeypatch):
    monkeypatch.setattr(autostart, "IS_WIN", False)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    monkeypatch.setattr(autostart.paths, "installed", lambda: True)
    monkeypatch.setattr(autostart, "_real_user", lambda: "alice")
    ok, reason = autostart.is_supported()
    assert ok is True


# -- enable/disable: Linux ----------------------------------------------------
def test_enable_linux_writes_the_rule_and_desktop_file_without_chowning(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart, "IS_WIN", False)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    monkeypatch.setattr(autostart.paths, "installed", lambda: True)
    monkeypatch.setattr(autostart, "_real_user", lambda: "alice")

    rule_path = tmp_path / "49-sushtun.rules"
    monkeypatch.setattr(autostart, "POLKIT_RULE", rule_path)
    home = tmp_path / "home" / "alice"
    monkeypatch.setattr(autostart, "_desktop_file",
                        lambda user: home / ".config" / "autostart" / "sushtun.desktop")

    # The desktop file is now written as the real user (core/userfs.py), so
    # it is already owned by them the moment it's created -- a chown here
    # would mean root touched a user-controlled path, exactly the bug this
    # was fixed for.
    def raise_chown(*a, **k):
        raise AssertionError("must never chown: the file is created by the user, not root")
    monkeypatch.setattr(autostart.os, "chown", raise_chown)
    monkeypatch.setattr(
        "pwd.getpwnam",
        lambda name: types.SimpleNamespace(pw_name=name, pw_uid=os.getuid(), pw_gid=os.getgid(),
                                            pw_dir=str(home)),
    )

    autostart.enable()

    assert rule_path.exists()
    assert 'subject.user == "alice"' in rule_path.read_text()
    desktop = home / ".config" / "autostart" / "sushtun.desktop"
    assert desktop.exists()
    assert "--autostart" in desktop.read_text()


def test_write_polkit_rule_refuses_a_pre_existing_symlink(monkeypatch, tmp_path):
    real = tmp_path / "real.rules"
    real.write_text("old", encoding="utf-8")
    link = tmp_path / "49-sushtun.rules"
    link.symlink_to(real)
    monkeypatch.setattr(autostart, "POLKIT_RULE", link)

    with pytest.raises(RuntimeError):
        autostart._write_polkit_rule("alice")

    assert real.read_text(encoding="utf-8") == "old"


def test_disable_linux_removes_both_files(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart, "IS_WIN", False)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    rule_path = tmp_path / "49-sushtun.rules"
    rule_path.write_text("x")
    monkeypatch.setattr(autostart, "POLKIT_RULE", rule_path)
    desktop = tmp_path / "sushtun.desktop"
    desktop.write_text("x")
    monkeypatch.setattr(autostart, "_real_user", lambda: "alice")
    monkeypatch.setattr(autostart, "_desktop_file", lambda user: desktop)
    monkeypatch.setattr(
        "pwd.getpwnam",
        lambda name: types.SimpleNamespace(pw_name=name, pw_uid=os.getuid(), pw_gid=os.getgid()),
    )

    autostart.disable()

    assert not rule_path.exists()
    assert not desktop.exists()


def test_enable_linux_raises_when_unsupported(monkeypatch):
    monkeypatch.setattr(autostart, "IS_WIN", False)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    monkeypatch.setattr(autostart.paths, "installed", lambda: False)
    with pytest.raises(RuntimeError):
        autostart.enable()


# -- enable/disable: Windows --------------------------------------------------
def test_enable_windows_registers_a_task_with_values_via_env_not_interpolation(monkeypatch):
    monkeypatch.setattr(autostart, "IS_WIN", True)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", r"C:\Users\a b\sushTun.exe")

    captured = {}

    def fake_ps(script, *, env=None, timeout=None):
        captured["script"] = script
        captured["env"] = env
        return types.SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(autostart.proc, "powershell", fake_ps)

    autostart.enable()

    # The exe path (which can contain spaces) never gets string-interpolated
    # into the PowerShell text -- only $env:SUSH_EXE references appear.
    assert r"C:\Users\a b\sushTun.exe" not in captured["script"]
    assert "$env:SUSH_EXE" in captured["script"]
    assert captured["env"]["SUSH_EXE"] == r"C:\Users\a b\sushTun.exe"
    assert captured["env"]["SUSH_ARG"] == "--autostart"
    assert captured["env"]["SUSH_TASK"] == autostart.TASK_NAME
    assert "AtLogOn" in captured["script"]
    assert "RunLevel Highest" in captured["script"]


def test_disable_windows_deletes_the_task(monkeypatch):
    monkeypatch.setattr(autostart, "IS_WIN", True)
    monkeypatch.setattr(autostart, "IS_MAC", False)
    captured = {}
    monkeypatch.setattr(
        autostart.proc, "run",
        lambda args, **k: captured.setdefault("args", args) or types.SimpleNamespace(returncode=0),
    )
    autostart.disable()
    assert captured["args"] == ["schtasks", "/Delete", "/TN", autostart.TASK_NAME, "/F"]
