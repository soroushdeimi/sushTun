import sys
import time

import pytest

from xrayui.core import wireguard


def test_device_name_platform_specific(monkeypatch):
    monkeypatch.setattr(wireguard, "IS_MAC", True)
    assert wireguard.device_name() == wireguard.MAC_DEVICE
    monkeypatch.setattr(wireguard, "IS_MAC", False)
    assert wireguard.device_name() == wireguard.DEVICE


def test_start_builds_expected_command_windows(monkeypatch, tmp_path):
    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def poll(self):
            return None

    monkeypatch.setattr(wireguard, "IS_WIN", True)
    monkeypatch.setattr(wireguard.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(wireguard.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(wireguard.paths, "wireguard_go_bin", lambda: tmp_path / "wireguard-go.exe")

    t = wireguard.WireGuardTunnel()
    t.start()

    args = captured["args"]
    assert args[0].endswith("wireguard-go.exe")
    assert t.device in args
    assert captured["kwargs"]["env"]["WG_PROCESS_FOREGROUND"] == "1"
    assert t.is_running()


def test_start_builds_expected_command_posix(monkeypatch, tmp_path):
    captured = {}

    class FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def poll(self):
            return None

    monkeypatch.setattr(wireguard, "IS_WIN", False)
    monkeypatch.setattr(wireguard.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(wireguard.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(wireguard.paths, "wireguard_go_bin", lambda: tmp_path / "wireguard-go")

    t = wireguard.WireGuardTunnel()
    t.start()

    args = captured["args"]
    assert args[0].endswith("wireguard-go")
    assert "-f" in args
    assert t.device in args
    assert "WG_PROCESS_FOREGROUND" not in captured["kwargs"]["env"]


def test_is_running_survives_missing_popen_handle(monkeypatch):
    t = wireguard.WireGuardTunnel()
    assert t._proc is None
    monkeypatch.setattr(wireguard, "uapi_exists", lambda device: True)
    assert t.is_running() is True
    monkeypatch.setattr(wireguard, "uapi_exists", lambda device: False)
    assert t.is_running() is False


def test_stop_terminates_process_and_closes_log(tmp_path):
    calls = []

    class FakeProc:
        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout=None):
            calls.append("wait")

    t = wireguard.WireGuardTunnel()
    t._proc = FakeProc()
    log_path = tmp_path / "wg.log"
    t._log = open(log_path, "w", encoding="utf-8")
    t.stop()
    assert calls == ["terminate", "wait"]
    assert t._proc is None
    assert t._log is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipes")
def test_uapi_set_win_over_a_real_pipe_server(monkeypatch):
    """The Windows UAPI transport, against a real named-pipe server.

    Also pins the no-hang property: the server replies and then deliberately
    keeps the pipe open, so a read-to-EOF implementation would block here
    forever instead of returning the response.
    """
    import ctypes
    import threading
    from ctypes import wintypes

    name = r"WGTestPrefix\sushTunSet"
    full = wireguard._PIPE_ROOT + name
    monkeypatch.setattr(wireguard, "_uapi_pipe_path", lambda device: full)

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    ]
    k32.CreateNamedPipeW.restype = wintypes.HANDLE

    handle = k32.CreateNamedPipeW(full, 0x3, 0x0, 1, 4096, 4096, 0, None)
    assert handle != ctypes.c_void_p(-1).value, "could not create test pipe"

    received = {}
    release = threading.Event()

    def server():
        k32.ConnectNamedPipe(wintypes.HANDLE(handle), None)
        buf = ctypes.create_string_buffer(4096)
        read = wintypes.DWORD(0)
        k32.ReadFile(wintypes.HANDLE(handle), buf, 4096, ctypes.byref(read), None)
        received["payload"] = buf.raw[: read.value].decode()
        reply = b"errno=0\n\n"
        written = wintypes.DWORD(0)
        k32.WriteFile(wintypes.HANDLE(handle), reply, len(reply),
                      ctypes.byref(written), None)
        # Hold the pipe open; a read-to-EOF client would hang right here.
        release.wait(timeout=10)
        k32.CloseHandle(wintypes.HANDLE(handle))

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        response = wireguard._uapi_set_win("sushTun", "set=1\nprivate_key=ab\n\n")
    finally:
        elapsed = time.monotonic() - started
        release.set()
        thread.join(timeout=10)

    assert response == "errno=0\n\n"
    assert received["payload"] == "set=1\nprivate_key=ab\n\n"
    # Must return on the terminator, not wait out the server holding the pipe.
    assert elapsed < 5, f"read did not stop at the UAPI terminator ({elapsed:.1f}s)"


def test_uapi_set_posix_over_fake_socket(monkeypatch):
    sent = {}

    class FakeSocket:
        def __init__(self, *a, **k):
            pass

        def connect(self, path):
            sent["path"] = path

        def sendall(self, data):
            sent["data"] = data

        def recv(self, n):
            if sent.get("received"):
                return b""
            sent["received"] = True
            return b"errno=0\n\n"

        def close(self):
            sent["closed"] = True

    # AF_UNIX doesn't exist on every platform this test suite runs on
    # (e.g. some Windows Python builds); _uapi_set_posix only ever runs on
    # POSIX in production, so the constant just needs to exist for the test.
    monkeypatch.setattr(wireguard.socket, "AF_UNIX", 1, raising=False)
    monkeypatch.setattr(wireguard.socket, "socket", lambda *a, **k: FakeSocket())
    response = wireguard._uapi_set_posix("sushTun", "set=1\nprivate_key=aa\n\n")
    assert sent["path"] == "/var/run/wireguard/sushTun.sock"
    assert sent["data"] == b"set=1\nprivate_key=aa\n\n"
    assert response == "errno=0\n\n"
    assert sent["closed"] is True


def test_uapi_pipe_path_shape():
    path = wireguard._uapi_pipe_path("sushTun")
    assert path == r"\\.\pipe\ProtectedPrefix\Administrators\WireGuard\sushTun"
    assert wireguard._PIPE_ROOT + wireguard._uapi_pipe_name("sushTun") == path


def test_pipe_exists_is_false_and_silent_when_absent():
    # Must answer False, not raise, for a pipe that was never created.
    assert wireguard._pipe_exists("sushTun_definitely_not_a_live_pipe") is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipes")
def test_pipe_exists_detects_a_live_named_pipe():
    """Regression: a live pipe must be detected without connecting to it.

    stat()-based probing fails both ways here -- Path.exists() raises
    WinError 231 when the pipe is live, and os.path.exists() returns False.
    Either would leave wait_for_uapi() unable to ever see wireguard-go come
    up, so the WireGuard lane could never connect on Windows.
    """
    import ctypes
    from ctypes import wintypes

    name = r"WGTestPrefix\sushTunProbe"
    full = wireguard._PIPE_ROOT + name

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    ]
    k32.CreateNamedPipeW.restype = wintypes.HANDLE

    assert wireguard._pipe_exists(name) is False
    handle = k32.CreateNamedPipeW(full, 0x3, 0x0, 4, 4096, 4096, 0, None)
    assert handle != ctypes.c_void_p(-1).value, "could not create test pipe"
    try:
        assert wireguard._pipe_exists(name) is True
    finally:
        k32.CloseHandle(handle)
    assert wireguard._pipe_exists(name) is False
