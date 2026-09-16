"""Suite-wide guards."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_network_teardown_at_exit(monkeypatch):
    # Connection() registers an atexit hook that undoes a connection this
    # process made. A test that fakes a successful connect leaves that flag
    # set, and at interpreter exit -- long after its monkeypatches are gone --
    # the hook ran the real teardown on the developer's machine: `ip route del`
    # for the fake server and `resolvectl revert xray0` on a live tunnel.
    from xrayui.core import connection

    monkeypatch.setattr(connection.atexit, "register", lambda *a, **k: None)
