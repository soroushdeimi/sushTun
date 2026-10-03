"""Never persist the tunnel's own dead resolver as an original DNS server."""
from types import SimpleNamespace

import pytest

from xrayui.core import _net_posix as posix
from xrayui.core.network import DnsState


def test_windows_loopback_backup_becomes_dhcp(win_net, monkeypatch):
    monkeypatch.setattr(win_net.proc, "ps_lines", lambda *a, **k: ["STATIC", "127.0.0.1"])
    assert win_net.backup_dns("Wi-Fi") == DnsState("DHCP", [])


@pytest.mark.parametrize("servers,expected", [("127.0.0.1", []),
                                               ("127.0.0.1\n1.1.1.1", ["1.1.1.1"])])
def test_macos_backup_strips_loopback(monkeypatch, servers, expected):
    monkeypatch.setattr(posix, "IS_MAC", True)
    monkeypatch.setattr(posix, "mac_service_name", lambda alias: "Wi-Fi")
    calls = []
    monkeypatch.setattr(posix.proc, "run", lambda args: calls.append(args) or
                        SimpleNamespace(stdout=servers, returncode=0))
    dns = posix.backup_dns("en0")
    assert dns == DnsState("MACOS", ["Wi-Fi", *expected])
    assert posix.restore_dns("en0", dns)
    assert ["networksetup", "-setdnsservers", "Wi-Fi", *(expected or ["empty"])] in calls


def test_linux_file_backup_strips_own_loopback(monkeypatch, tmp_path):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("search example.org\nnameserver 127.0.0.1\nnameserver 9.9.9.9\n")
    monkeypatch.setattr(posix, "IS_MAC", False)
    monkeypatch.setattr(posix, "_resolved_active", lambda: False)
    monkeypatch.setattr(posix, "_RESOLV", str(resolv))
    assert posix.backup_dns("eth0").servers == ["search example.org", "nameserver 9.9.9.9"]


def test_macos_stranded_dns_released_to_automatic(monkeypatch):
    monkeypatch.setattr(posix, "IS_MAC", True)
    calls = []
    def run(args):
        calls.append(args)
        out = ""
        if args == ["networksetup", "-listnetworkserviceorder"]:
            out = "(1) Wi-Fi\n(Hardware Port: Wi-Fi, Device: en0)\n"
        if "-getdnsservers" in args:
            out = "127.0.0.1\n"
        return SimpleNamespace(stdout=out, returncode=0)
    monkeypatch.setattr(posix.proc, "run", run)
    assert posix.release_stranded_dns() == ["en0"]
    assert ["networksetup", "-setdnsservers", "Wi-Fi", "empty"] in calls


def test_macos_missing_service_is_absent(monkeypatch):
    monkeypatch.setattr(posix, "IS_MAC", True)
    monkeypatch.setattr(posix.proc, "run", lambda *a, **k:
                        SimpleNamespace(stdout="", returncode=0))
    assert posix.dns_target_exists("en0", DnsState("MACOS", ["Old Wi-Fi"])) is False


def test_linux_file_restore_honours_retries(monkeypatch):
    monkeypatch.setattr(posix, "_resolved_active", lambda: False)
    monkeypatch.setattr(posix.time, "sleep", lambda *a: None)
    attempts = []
    def denied(*a, **k):
        attempts.append(1)
        raise PermissionError("immutable")
    monkeypatch.setattr("builtins.open", denied)
    assert posix.restore_dns("eth0", DnsState("FILE", ["nameserver 1.1.1.1"]), retries=8) is False
    assert len(attempts) == 8


def test_linux_file_release_uses_network_managers_dhcp_resolvers(monkeypatch, tmp_path):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 127.0.0.1\n")
    dhcp = tmp_path / "dhcp.conf"
    dhcp.write_text("nameserver 192.0.2.1\n")
    monkeypatch.setattr(posix, "IS_MAC", False)
    monkeypatch.setattr(posix, "_resolved_active", lambda: False)
    monkeypatch.setattr(posix, "_RESOLV", str(resolv))
    monkeypatch.setattr(posix, "_DHCP_RESOLV", (str(dhcp),), raising=False)
    assert posix.release_stranded_dns() == ["/etc/resolv.conf"]
    assert resolv.read_text() == dhcp.read_text()


@pytest.mark.parametrize("output,code,expected", [("present", 0, True),
                                                  ("absent", 0, False), ("", 1, None)])
def test_windows_inventory_distinguishes_missing_from_unavailable(
        win_net, monkeypatch, output, code, expected):
    monkeypatch.setattr(win_net.proc, "powershell", lambda *a, **k:
                        SimpleNamespace(stdout=output, returncode=code))
    assert win_net.dns_target_exists("Wi-Fi", DnsState()) is expected


@pytest.mark.parametrize("output,code,expected", [('[{"ifname":"eth0"}]', 0, True),
                                                  ("[]", 0, False), ("", 1, None)])
def test_linux_inventory_distinguishes_missing_from_unavailable(
        monkeypatch, output, code, expected):
    monkeypatch.setattr(posix, "IS_MAC", False)
    monkeypatch.setattr(posix.proc, "run", lambda *a, **k:
                        SimpleNamespace(stdout=output, returncode=code))
    assert posix.dns_target_exists("eth0", DnsState()) is expected


def test_macos_service_inventory_preserves_spaces_and_unicode(monkeypatch):
    monkeypatch.setattr(posix, "IS_MAC", True)
    output = "(1) Wi-Fi خانه\n(Hardware Port: Wi-Fi, Device: en0)\n"
    monkeypatch.setattr(posix.proc, "run", lambda *a, **k:
                        SimpleNamespace(stdout=output, returncode=0))
    assert posix.dns_target_exists("en0", DnsState("MACOS", ["Wi-Fi خانه"])) is True
    assert posix.dns_target_exists("en0", DnsState("MACOS", ["Removed service"])) is False
