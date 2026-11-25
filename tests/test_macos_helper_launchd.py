"""Two things the first release of the helper got wrong, found only on a real Mac.

* the install/uninstall AppleScript used a shell-quoted string, a syntax error
  in AppleScript, so the admin prompt never even appeared;
* the daemon opened a library that does not exist and called
  launch_activate_socket with the wrong signature, so it exited at once and
  never served its socket.
"""
from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys

import pytest

from xrayui.core import macos_helper as h


def test_admin_script_is_a_double_quoted_applescript_string():
    script = h._admin_script('echo "a\\b" \'c\'')
    assert script.startswith('do shell script "')
    assert script.endswith('" with administrator privileges')
    assert '\\"a\\\\b\\"' in script            # quote and backslash escaped


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("osacompile"),
                    reason="needs macOS osacompile")
@pytest.mark.parametrize("argv", [h.install_commands()[0], h.uninstall_commands()[0]])
def test_install_and_uninstall_applescript_compile(argv, tmp_path):
    src = tmp_path / "s.applescript"
    src.write_text(argv[2])
    result = subprocess.run(["osacompile", "-o", str(tmp_path / "s.scpt"), str(src)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_activated_socket_opens_libsystem_not_a_missing_library(monkeypatch):
    opened = []

    def cdll(path, *a, **k):
        opened.append(path)
        raise OSError("stop here")

    monkeypatch.setattr(h.ctypes, "CDLL", cdll)
    with pytest.raises(OSError):
        h._activated_socket()
    assert opened == ["/usr/lib/libSystem.B.dylib"]


def test_activated_socket_declares_the_out_pointer_signature(monkeypatch):
    seen = {}

    class Fn:
        def __setattr__(self, name, value):
            seen[name] = value

        def __call__(self, *args):
            return 22                           # EINVAL: nothing activated

    class Lib:
        launch_activate_socket = Fn()

    monkeypatch.setattr(h.ctypes, "CDLL", lambda *a, **k: Lib())
    with pytest.raises(OSError):
        h._activated_socket()
    assert len(seen["argtypes"]) == 3           # name, int **fds, size_t *count
    assert seen["restype"] is ctypes.c_int
