"""On Windows the core must be identified by its config, not by its name."""
from types import SimpleNamespace

import pytest

from xrayui import paths
from xrayui.core import xray


@pytest.fixture
def win_xray(monkeypatch, tmp_path):
    # A base directory with a space and Persian text in it: the command line
    # then quotes the config path, which is the case that used to be matched by
    # image name alone.
    base = tmp_path / "نام کاربر" / "sushTun build"
    base.mkdir(parents=True)
    monkeypatch.setattr(xray, "IS_WIN", True)
    monkeypatch.setattr(paths, "base_dir", lambda: base)
    calls = []
    monkeypatch.setattr(xray.proc, "run", lambda args, **kw: calls.append(args)
                        or SimpleNamespace(returncode=0, stdout="", stderr=""))
    return calls


def _script_output(monkeypatch, lines):
    monkeypatch.setattr(xray.proc, "ps_lines", lambda script, **kw: lines)


def _ours(*pids):
    """Command lines for our own xray, as Windows reports them."""
    return [f'{pid}|"xray.exe" run -c "{paths.runtime_config()}"' for pid in pids]


THEIRS = '4321|"xray.exe" run -c "C:\\Tools\\v2rayN\\bin\\config.json"'


def test_a_foreign_core_does_not_look_like_our_session(win_xray, monkeypatch):
    _script_output(monkeypatch, [THEIRS])
    assert xray.is_xray_running() is False


def test_our_own_core_is_found(win_xray, monkeypatch):
    _script_output(monkeypatch, _ours(1234))
    assert xray.is_xray_running() is True


def test_disconnecting_leaves_another_clients_core_alone(win_xray, monkeypatch):
    _script_output(monkeypatch, [THEIRS])
    xray._kill_all()
    assert [a for a in win_xray if a[0] == "taskkill"] == []


def test_disconnecting_kills_only_our_own_pids(win_xray, monkeypatch):
    _script_output(monkeypatch, [*_ours(1234), THEIRS, *_ours(5678)])
    xray._kill_all()
    killed = [a for a in win_xray if a[0] == "taskkill"]
    assert killed == [["taskkill", "/f", "/pid", "1234", "/t"],
                      ["taskkill", "/f", "/pid", "5678", "/t"]]


def test_a_config_path_that_is_a_prefix_of_ours_is_not_ours(win_xray, monkeypatch):
    _script_output(monkeypatch, [f'9999|"xray.exe" run -c "{paths.runtime_config()}.bak"'])
    assert xray.is_xray_running() is False


def test_output_we_cannot_read_is_not_a_live_session(win_xray, monkeypatch):
    # A process we may not inspect reports no command line at all.
    _script_output(monkeypatch, ["9999|"])
    assert xray.is_xray_running() is False


def test_the_query_asks_for_xray_processes_with_their_command_lines(win_xray, monkeypatch):
    scripts = []
    monkeypatch.setattr(xray.proc, "ps_lines", lambda script, **kw: scripts.append(script) or [])
    xray.is_xray_running()
    assert "Win32_Process" in scripts[0] and "xray.exe" in scripts[0]
