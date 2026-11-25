"""Strict mode validated against the real Xray binary.

The rendered config must be one Xray will actually start. In particular the
protected-domain list is sanitised so that weird user input (empty, spaces,
uppercase, wildcard, unicode, duplicates, >1000 entries) is dropped/normalised
with a WARNING and never produces a config Xray refuses.
"""
from __future__ import annotations

import copy
import json

import pytest

from xrayui import paths
from xrayui.core import render, routing, strict, xraycheck
from xrayui.core import settings as app_settings
from xrayui.core.importer import parse_vless

SAMPLE = "vless://u@127.0.0.1:443?type=tcp&security=none#x"


def _skip_if_no_binary():
    if not paths.xray_exe().exists():
        pytest.skip("bundled xray binary not present")


def _strict(**over):
    c = copy.deepcopy(app_settings.DEFAULTS["strict"])
    c.update(over)
    return c


def _render(strict_cfg, routing_over=None):
    r = copy.deepcopy(app_settings.DEFAULTS["routing"])
    if routing_over:
        r.update(routing_over)
    return render.build_text(
        parse_vless(SAMPLE), "lo", include_tun=False,
        routing_rules=routing.build_rules(r), strict_cfg=strict_cfg)


def test_strict_on_renders_a_config_xray_accepts(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    text = _render(_strict(enabled=True, domains=["myai.dev"]))
    assert xraycheck.check_config(text) is None


def test_no_direct_renders_a_config_xray_accepts(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    text = _render(_strict(enabled=True, no_direct=True))
    assert xraycheck.check_config(text) is None


def test_weird_input_is_sanitised_and_still_validates(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    weird = [
        "", "   ", "UPPER.COM", "*.chatgpt.com", "openai.com", "openai.com",
        "exa mple.com", "unicode.دومين.com", "nodot", 42, None, ["x.ai"],
        "myai.dev",
    ]
    text = _render(_strict(enabled=True, domains=weird))
    assert xraycheck.check_config(text) is None
    # The normalised names made it in; the bad ones did not.
    rules = json.loads(text)["routing"]["rules"]
    strict_rule = next(r for r in rules if r.get("outboundTag") == "proxy")
    doms = strict_rule["domain"]
    assert "domain:upper.com" in doms
    assert "domain:chatgpt.com" in doms  # wildcard normalised
    assert "domain:myai.dev" in doms
    assert "domain:openai.com" in doms
    assert doms.count("domain:openai.com") == 1  # deduped
    assert not any("exa mple" in d for d in doms)
    assert not any("دومين" in d for d in doms)
    assert not any("nodot" in d for d in doms)


def test_huge_list_is_capped_and_still_validates(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    big = [f"host{i}.example.com" for i in range(1500)]
    text = _render(_strict(enabled=True, domains=big))
    assert xraycheck.check_config(text) is None
    rules = json.loads(text)["routing"]["rules"]
    strict_rule = next(r for r in rules if r.get("outboundTag") == "proxy")
    # user domains capped at MAX_DOMAINS, plus the curated AI list
    assert len(strict_rule["domain"]) <= strict.MAX_DOMAINS + len(strict.DEFAULT_AI_DOMAINS)
    assert len(strict_rule["domain"]) > strict.MAX_DOMAINS  # the cap actually bound


def test_strict_off_renders_a_config_xray_accepts(tmp_path, monkeypatch):
    _skip_if_no_binary()
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    text = _render(_strict(enabled=False))
    assert xraycheck.check_config(text) is None
