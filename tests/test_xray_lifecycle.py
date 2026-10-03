"""Child handles remain authoritative even when orphan discovery misses."""
from unittest.mock import Mock

import pytest

from xrayui.core import xray


@pytest.mark.parametrize("windows", [True, False])
def test_stop_kills_child_before_orphan_sweep(monkeypatch, windows):
    monkeypatch.setattr(xray, "IS_WIN", windows)
    events = []
    child = Mock(pid=1234)
    child.poll.return_value = None
    child.kill.side_effect = lambda: events.append("child")
    monkeypatch.setattr(xray.proc, "run", lambda *a, **k: events.append(a[0]))
    monkeypatch.setattr(xray, "_kill_all", lambda: events.append("sweep"))
    process = xray.XrayProcess()
    process._proc = child
    process.stop()
    assert events == ([['taskkill', '/f', '/t', '/pid', '1234'], "sweep"]
                      if windows else ["child", "sweep"])
    child.wait.assert_called_once_with(timeout=3)
    assert not process.is_running()

