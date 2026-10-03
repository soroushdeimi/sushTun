"""Adapter names must survive JSON rendering verbatim."""
import json

import pytest

from xrayui.core import render
from xrayui.core.profiles import Profile


@pytest.mark.parametrize("alias", ['Wi-Fi "خانه"', r'LAN\backup', 'اترنت\tخانه',
                                   'Wi-Fi __IFACE__'])
def test_interface_name_is_json_escaped_once(alias):
    profile = Profile(address="203.0.113.10", port=443, id="u", security="none")
    cfg = json.loads(render.build_text(profile, alias))
    for outbound in cfg["outbounds"]:
        sockopt = outbound.get("streamSettings", {}).get("sockopt", {})
        if "interface" in sockopt:
            assert sockopt["interface"] == alias
