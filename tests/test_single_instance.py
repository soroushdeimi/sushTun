"""A second launch shows the running window instead of starting another copy."""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QDeadlineTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import paths  # noqa: E402
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


# -- which build is answering ------------------------------------------------
# The handover was blind: any build on the socket got the window, so opening a
# freshly installed version while an older one still ran raised the OLD window
# and the new launch vanished. Settings then showed the old version number with
# nothing to explain it.

@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    return tmp_path / "state"


# -- the advertisement -------------------------------------------------------
def test_the_listener_advertises_its_version_and_withdraws_it(state):
    single_instance.advertise()
    other = single_instance.running_instance()
    assert other is not None
    assert other.version == single_instance.__version__ and other.pid == os.getpid()
    assert other.is_this_build
    single_instance.withdraw()
    assert single_instance.running_instance() is None


def test_nothing_advertised_reads_as_unknown(state):
    # What an older build leaves behind: no file at all.
    assert single_instance.running_instance() is None


def test_a_leftover_from_a_dead_process_is_not_believed(state, monkeypatch):
    single_instance.advertise()
    monkeypatch.setattr(single_instance, "_alive", lambda _pid: False)
    assert single_instance.running_instance() is None


def test_a_corrupt_advertisement_is_not_believed(state):
    single_instance.identity_path().parent.mkdir(parents=True, exist_ok=True)
    single_instance.identity_path().write_text("{not json", encoding="utf-8")
    assert single_instance.running_instance() is None
    single_instance.identity_path().write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
    assert single_instance.running_instance() is None  # no pid to check


def test_a_root_owned_listener_counts_as_alive(monkeypatch):
    # The running copy is root and we are not: kill(pid, 0) is refused, and a
    # refusal proves the process is there.
    def refuse(_pid, _sig):
        raise PermissionError

    monkeypatch.setattr(single_instance.os, "kill", refuse)
    assert single_instance._alive(1234) is True


# -- what a second launch does -----------------------------------------------
@pytest.fixture
def warned(monkeypatch):
    seen = []
    monkeypatch.setattr(single_instance, "_warn_other_build", lambda other: seen.append(other))
    return seen


def test_no_copy_running_means_carry_on(monkeypatch, warned):
    monkeypatch.setattr(single_instance, "notify_running", lambda **_kw: False)
    assert single_instance.hand_over() is False
    assert warned == []


def test_the_same_build_hands_over_without_a_word(monkeypatch, state, warned):
    monkeypatch.setattr(single_instance, "notify_running", lambda **_kw: True)
    single_instance.advertise()
    assert single_instance.hand_over() is True
    assert warned == []


def test_a_different_version_is_called_out(monkeypatch, state, warned):
    monkeypatch.setattr(single_instance, "notify_running", lambda **_kw: True)
    single_instance.identity_path().parent.mkdir(parents=True, exist_ok=True)
    single_instance.identity_path().write_text(json.dumps(
        {"version": "0.7.1", "exe": "/old/sushtun", "pid": os.getpid()}), encoding="utf-8")
    assert single_instance.hand_over() is True
    assert [o.version for o in warned] == ["0.7.1"]


def test_a_build_too_old_to_advertise_is_called_out_too(monkeypatch, state, warned):
    monkeypatch.setattr(single_instance, "notify_running", lambda **_kw: True)
    assert single_instance.hand_over() is True
    assert warned == [None]


def test_a_login_launch_never_opens_a_dialog(monkeypatch, state, warned):
    # --autostart raises no window; a dialog would appear out of nowhere.
    monkeypatch.setattr(single_instance, "notify_running", lambda **_kw: True)
    assert single_instance.hand_over(show=False) is True
    assert warned == []
