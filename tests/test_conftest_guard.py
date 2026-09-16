"""The suite must never leave a real network teardown queued for exit."""
from __future__ import annotations

from xrayui.core import connection


def test_suite_guard_stubs_the_connection_exit_hook():
    # conftest's autouse fixture swaps atexit.register for a no-op lambda, so
    # a Connection built by any test cannot queue the real _restore.
    assert connection.atexit.register.__name__ == "<lambda>"
