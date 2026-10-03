import subprocess
import sys
from unittest.mock import MagicMock

from xrayui import elevate


def test_relaunch_macos_escaping(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(elevate, "IS_MAC", True)

    script_passed = []

    def fake_run(args, **kwargs):
        if args[0] == "osascript":
            script_passed.append(args[2])
            return MagicMock(returncode=0, stderr="")
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    # The actual paths can contain single quotes too, e.g. John's App
    monkeypatch.setattr(elevate, "_elevated_cmd", lambda: ["/path/to/John's app/xrayui", "--some-arg", "He said \"Hello\\World\""])
    monkeypatch.setattr(elevate, "_session_args", lambda: [])

    assert elevate._relaunch_macos() is True

    assert len(script_passed) == 1
    script = script_passed[0]
    prefix = 'do shell script "'
    suffix = '" with administrator privileges'
    assert script.startswith(prefix)
    assert script.endswith(suffix)
    literal = script[len(prefix):-len(suffix)]

    import ast
    evaluated = ast.literal_eval('"' + literal + '"')

    import shlex
    parsed = shlex.split(evaluated)
    assert parsed == ["/path/to/John's app/xrayui", "--some-arg", 'He said "Hello\\World"']
