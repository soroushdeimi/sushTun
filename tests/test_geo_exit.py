"""Exit-country detection: trace parsing, never-raising fetch, flag assets."""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from xrayui.core import geo_exit

FLAGS = Path(__file__).resolve().parent.parent / "assets" / "flags"
TRACE = "fl=1\nh=www.cloudflare.com\nip=152.233.20.199\nloc=DE\ncolo=FRA\nwarp=off\n"


class _Opener:
    def __init__(self, body=None, error=None):
        self.body, self.error = body, error

    def open(self, url, timeout=None):
        if self.error:
            raise self.error
        resp = io.BytesIO(self.body.encode())
        resp.__enter__ = lambda: resp
        return resp


def test_parse_trace_reads_country_and_ip():
    info = geo_exit.parse_trace(TRACE)
    assert info == geo_exit.ExitInfo("de", "152.233.20.199")


@pytest.mark.parametrize("body", [
    "ip=1.2.3.4\ncolo=FRA\n",
    "ip=1.2.3.4\nloc=XX\n",
    "ip=1.2.3.4\nloc=T1\n",
    "ip=1.2.3.4\nloc=\n",
    "ip=1.2.3.4\nloc=DEU\n",
    "<html>not a trace</html>",
    "",
])
def test_parse_trace_rejects_bodies_without_a_usable_country(body):
    assert geo_exit.parse_trace(body) is None


def test_detect_through_an_opener():
    assert geo_exit.detect(_Opener(TRACE), 3) == geo_exit.ExitInfo("de", "152.233.20.199")


def test_detect_never_raises():
    assert geo_exit.detect(_Opener(error=OSError("down")), 1) is None
    assert geo_exit.detect(_Opener("garbage"), 1) is None
    assert geo_exit.detect("http://127.0.0.1:1", 0.5) is None


# -- assets -----------------------------------------------------------------
def test_every_flag_file_is_a_two_letter_code_with_english_and_persian_names():
    svgs = sorted(FLAGS.glob("*.svg"))
    assert svgs
    names = json.loads((FLAGS / "names.json").read_text(encoding="utf-8"))
    for svg in svgs:
        assert re.fullmatch(r"[a-z]{2}", svg.stem), svg.name
        assert names[svg.stem]["en"] and names[svg.stem]["fa"], svg.stem
    assert set(names) == {s.stem for s in svgs}


def test_the_flag_icons_license_ships_with_the_flags():
    assert "MIT" in (FLAGS / "LICENSE-flag-icons").read_text(encoding="utf-8")


def test_name_lookup_falls_back_to_english_then_the_code():
    assert geo_exit.country_name("de", "en") == "Germany"
    assert geo_exit.country_name("DE", "fa") == "آلمان"
    assert geo_exit.country_name("de", "xx") == "Germany"
    assert geo_exit.country_name("zz") == ""
    assert geo_exit.flag_path("de").name == "de.svg"
    assert geo_exit.flag_path("xx") is None
    assert geo_exit.flag_path(None) is None
