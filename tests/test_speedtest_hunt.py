import threading

from xrayui.core import profiles, speedtest


def test_ports_are_unique():
    profs = [profiles.Profile(uid=str(i)) for i in range(50)]
    captured_ports = []
    def run_batch(profiles, ports, **kwargs):
        captured_ports.extend(ports)
        return True

    speedtest._test_group(
        profs, lambda *a: None, threading.Event(),
        url="http://x", timeout=1, iface_alias="", run_batch=run_batch
    )

    assert len(set(captured_ports)) == 50
