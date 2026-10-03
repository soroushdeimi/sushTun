"""Restoring adapter DNS must check every server it writes back."""
from types import SimpleNamespace

import pytest

from xrayui.core.network import DnsState


@pytest.mark.parametrize("retries, expected", [(1, False), (2, True)])
def test_secondary_dns_failure_is_retried(win_net, monkeypatch, retries, expected):
    monkeypatch.setattr(win_net.proc, "powershell",
                        lambda *a, **k: SimpleNamespace(returncode=1))
    monkeypatch.setattr(win_net.time, "sleep", lambda delay: None)
    calls = []
    additions = []

    def run(args, **kwargs):
        calls.append(args)
        if "add" in args:
            additions.append(args)
            return SimpleNamespace(returncode=1 if len(additions) == 1 else 0)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(win_net.proc, "run", run)
    result = win_net.restore_dns("اترنت خانه", DnsState("STATIC", ["1.1.1.1", "8.8.8.8"]),
                                 retries=retries)
    assert result is expected
    assert len(additions) == retries
    assert (["ipconfig", "/flushdns"] in calls) is expected
