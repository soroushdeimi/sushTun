"""Linux uplink selection from iproute2 JSON; no system commands run."""
import json
from types import SimpleNamespace

import pytest

from xrayui.core import _net_posix as posix


def _detect(monkeypatch, routes):
    def run(args, **kwargs):
        if args == ["ip", "-j", "route", "show", "default"]:
            data = routes
        elif args == ["ip", "-j", "link", "show"]:
            data = [{"ifname": name, "link_type": kind} for name, kind in
                    [("enp0s31f6", "ether"), ("wlp2s0.100", "ether"), ("tun0", "none")]]
        else:
            data = [{"addr_info": [{"family": "inet", "local": "192.0.2.20"}]}]
        return SimpleNamespace(stdout=json.dumps(data), stderr="", returncode=0)

    monkeypatch.setattr(posix.proc, "run", run)
    return posix._linux_detect()


def test_multipath_default_selects_a_live_physical_nexthop(monkeypatch):
    iface = _detect(monkeypatch, [{"dst": "default", "metric": 100, "protocol": "static",
                                 "nexthops": [
                                     {"gateway": "192.0.2.1", "dev": "enp0s31f6",
                                      "weight": 1, "flags": ["linkdown"]},
                                     {"gateway": "192.0.2.2", "dev": "wlp2s0.100",
                                      "weight": 1, "flags": ["onlink"]}]}])
    assert iface is not None
    assert (iface.alias, iface.gateway) == ("wlp2s0.100", "192.0.2.2")


@pytest.mark.parametrize("flags", [["linkdown"], ["dead"]])
def test_unusable_default_does_not_beat_a_live_route(monkeypatch, flags):
    iface = _detect(monkeypatch, [
        {"dst": "default", "gateway": "192.0.2.1", "dev": "enp0s31f6",
         "metric": 10, "flags": flags},
        {"dst": "default", "gateway": "192.0.2.2", "dev": "wlp2s0.100",
         "metric": 600, "protocol": "dhcp", "flags": ["onlink"]},
    ])
    assert iface.alias == "wlp2s0.100"


def test_a_plain_default_route_is_still_detected(monkeypatch):
    # Real NetworkManager output: a dhcp default on a wired link, plus the
    # route to the docker bridge's subnet that must never be picked.
    iface = _detect(monkeypatch, [
        {"dst": "172.17.0.0/16", "dev": "docker0", "protocol": "boot", "metric": 100},
        {"dst": "default", "gateway": "192.0.2.1", "dev": "enp0s31f6",
         "protocol": "dhcp", "metric": 600},
    ])
    assert (iface.alias, iface.gateway, iface.ipv4) == ("enp0s31f6", "192.0.2.1", "192.0.2.20")


def test_only_dead_defaults_left_is_no_interface_at_all(monkeypatch):
    # Nothing to route through: say so rather than pin the server route to a
    # gateway that is not there.
    assert _detect(monkeypatch, [
        {"dst": "default", "gateway": "192.0.2.1", "dev": "enp0s31f6",
         "metric": 10, "flags": ["linkdown"]},
    ]) is None


def test_our_own_tunnel_is_never_the_uplink(monkeypatch):
    iface = _detect(monkeypatch, [{"dst": "default", "metric": 1, "nexthops": [
        {"gateway": "172.19.0.2", "dev": "xray0", "weight": 1},
        {"gateway": "192.0.2.2", "dev": "wlp2s0.100", "weight": 1},
    ]}])
    assert iface.alias == "wlp2s0.100"
