"""Windows UAC command lines preserve arguments, including empty ones."""
import ctypes
import sys
from types import SimpleNamespace

import pytest

from xrayui import elevate


@pytest.mark.parametrize("arg, encoded", [
    ('', '""'),
    ('a"b', 'a\\"b'),
    ('two\twords', '"two\twords"'),
    ('C:\\Users\\نام کاربر\\', '"C:\\Users\\نام کاربر\\\\"'),
])
@pytest.mark.parametrize("frozen", [True, False])
def test_uac_preserves_argument_boundaries(monkeypatch, arg, encoded, frozen):
    calls = []
    shell = SimpleNamespace(ShellExecuteW=lambda *args: calls.append(args) or 33)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(shell32=shell), raising=False)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\sushTun\sushTun.exe")
    monkeypatch.setattr(sys, "argv", ["sushtun", arg, "--autostart"])
    assert elevate._relaunch_windows()
    assert calls[0][3] == ("" if frozen else "-m xrayui ") + encoded + " --autostart"
    assert calls[0][2] == sys.executable
