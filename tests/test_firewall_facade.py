"""The firewall facade: platform dispatch, delegation, and the status string.

The facade picks a backend per platform; tests swap `_backend` for a stub to
prove delegation without touching the real system.
"""
from __future__ import annotations

import pytest

from xrayui.core import firewall
from xrayui.core._firewall_common import FirewallError


class StubBackend:
    def __init__(self, supported=True, active=False):
        self._supported = supported
        self._active = active
        self.installed = None
        self.removed = 0
        self.install_error = None

    def supported(self):
        return self._supported

    def install(self, tun_alias, server_ips, allow_lan):
        if self.install_error:
            raise self.install_error
        self.installed = (tun_alias, list(server_ips), allow_lan)

    def remove(self):
        self.removed += 1
        return []

    def is_active(self):
        return self._active


@pytest.fixture
def stub(monkeypatch):
    backend = StubBackend()
    monkeypatch.setattr(firewall, "_backend", backend)
    return backend


def test_supported_delegates(stub):
    assert firewall.supported() is True
    stub._supported = False
    assert firewall.supported() is False


def test_install_delegates(stub):
    firewall.install("xray0", ["1.2.3.4"], True)
    assert stub.installed == ("xray0", ["1.2.3.4"], True)


def test_install_propagates_failure(stub):
    stub.install_error = FirewallError("boom")
    with pytest.raises(FirewallError, match="boom"):
        firewall.install("xray0", ["1.2.3.4"], True)


def test_remove_and_recover_stale_delegate(stub):
    assert firewall.remove() == []
    assert stub.removed == 1
    assert firewall.recover_stale() == []
    assert stub.removed == 2


def test_is_active_delegates(stub):
    assert firewall.is_active() is False
    stub._active = True
    assert firewall.is_active() is True


def test_status_strings(stub):
    stub._supported = False
    assert "missing" in firewall.status()
    stub._supported = True
    stub._active = False
    assert firewall.status() == "inactive"
    stub._active = True
    assert firewall.status() == "active"


def test_no_backend_means_unsupported(monkeypatch):
    monkeypatch.setattr(firewall, "_backend", None)
    assert firewall.supported() is False
    assert firewall.is_active() is False
    assert firewall.remove() == []
    assert firewall.recover_stale() == []
    assert "not supported" in firewall.status()
    with pytest.raises(FirewallError):
        firewall.install("xray0", ["1.2.3.4"], True)
