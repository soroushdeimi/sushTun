"""A second launch shows the running window instead of starting another copy."""
from __future__ import annotations

import os
import socket
import sys
import tempfile
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QDeadlineTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui.ui import single_instance  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def name():
    # A unique name per test, so a real sushTun on this machine is never reached.
    return f"sushtun-test-{uuid.uuid4().hex[:12]}"


def _pump_until(cond, ms=2000):
    deadline = QDeadlineTimer(ms)
    while not cond() and not deadline.hasExpired():
        QCoreApplication.processEvents()
    return cond()


def test_nobody_running_means_start_normally(name):
    assert single_instance.notify_running(name=name) is False


def test_a_second_launch_asks_the_running_copy_to_show(qapp, name):
    server = single_instance.InstanceServer(name)
    shown = []
    server.show_requested.connect(lambda: shown.append(1))
    assert server.is_listening()
    assert single_instance.notify_running(name=name) is True
    assert _pump_until(lambda: shown == [1])


def test_a_login_launch_only_checks_and_does_not_pop_the_window(qapp, name):
    server = single_instance.InstanceServer(name)
    shown = []
    server.show_requested.connect(lambda: shown.append(1))
    assert single_instance.notify_running(show=False, name=name) is True
    _pump_until(lambda: bool(shown), ms=300)
    assert shown == []


@pytest.mark.skipif(sys.platform == "win32", reason="named pipes leave no file behind")
def test_a_socket_file_left_by_a_crash_does_not_block_the_next_start(qapp, name):
    path = os.path.join(tempfile.gettempdir(), name)
    stale = socket.socket(socket.AF_UNIX)
    stale.bind(path)
    stale.close()  # the file stays, like after a crash
    try:
        assert single_instance.notify_running(name=name) is False
        server = single_instance.InstanceServer(name)
        assert server.is_listening()
    finally:
        if os.path.exists(path):
            os.unlink(path)
