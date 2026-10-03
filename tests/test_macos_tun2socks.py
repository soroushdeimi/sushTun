import subprocess

import pytest

from xrayui import paths
from xrayui.core import tun2socks


def test_tun2socks_failure_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    t = tun2socks.Tun2socks()

    orig_popen = subprocess.Popen
    def fake_popen(args, **kwargs):
        if "tun2socks" in str(args[0]):
            raise OSError("binary missing")
        return orig_popen(args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    with pytest.raises(OSError, match="binary missing"):
        t.start("127.0.0.1", 1080)

    assert t._log is None










