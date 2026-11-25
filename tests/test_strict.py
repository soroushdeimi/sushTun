"""Strict mode: keep the user's real IP away from AI accounts.

Covers the pure functions in core/strict.py: sanitising the protected-domain
list, building the protected rule, the no-direct strip, the domestic-DNS
filter, and the serverless-only incompatibility report.
"""
from __future__ import annotations

import copy
import logging

from xrayui.core import settings as app_settings
from xrayui.core import strict
from xrayui.core.profiles import Profile


def _strict(**over):
    c = copy.deepcopy(app_settings.DEFAULTS["strict"])
    c.update(over)
    return c


# -- defaults / off-by-default ------------------------------------------------

def test_default_is_off():
    c = app_settings.DEFAULTS["strict"]
    assert c["enabled"] is False
    assert c["no_direct"] is False
    assert c["ai_protect"] is True
    assert c["domains"] == []
    assert strict.is_active(c) is False
    assert strict.no_direct(c) is False
    assert strict.build_rule(c) is None


def test_is_active_requires_enabled_and_domains():
    assert strict.is_active(_strict(enabled=True)) is True  # ai_protect default
    assert strict.is_active(_strict(enabled=True, ai_protect=False, domains=[])) is False
    assert strict.is_active(_strict(enabled=True, ai_protect=False, domains=["x.ai"])) is True
    # enabled but a non-dict (corrupt) degrades to off, never raises
    assert strict.is_active(None) is False
    assert strict.is_active("enabled") is False


def test_no_direct_requires_enabled():
    assert strict.no_direct(_strict(no_direct=True)) is False  # not enabled
    assert strict.no_direct(_strict(enabled=True, no_direct=True)) is True


# -- sanitize_domains ---------------------------------------------------------

def test_sanitize_normalises_case_wildcard_and_dedupes():
    out = strict.sanitize_domains(
        ["OpenAI.com", "*.chatgpt.com", "openai.com", "  claude.ai  ", "claude.ai"]
    )
    assert out == ["openai.com", "chatgpt.com", "claude.ai"]


def test_sanitize_drops_empty_whitespace_and_nonstring():
    out = strict.sanitize_domains(["", "   ", None, 42, ["x.ai"], "x.ai"])
    assert out == ["x.ai"]


def test_sanitize_drops_invalid_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="xrayui.core.strict"):
        out = strict.sanitize_domains(
            ["exa mple.com", "unicode.دومين.com", "nodot", "a..b", "x.ai"]
        )
    assert out == ["x.ai"]
    assert any("invalid protected domain" in r.message for r in caplog.records)


def test_sanitize_drops_nonstring_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="xrayui.core.strict"):
        out = strict.sanitize_domains([123, None, "x.ai"])
    assert out == ["x.ai"]
    assert any("non-string" in r.message for r in caplog.records)


def test_sanitize_caps_at_max_domains(caplog):
    entries = [f"host{i}.example.com" for i in range(1500)]
    with caplog.at_level(logging.WARNING, logger="xrayui.core.strict"):
        out = strict.sanitize_domains(entries)
    assert len(out) == strict.MAX_DOMAINS
    assert any("exceeds" in r.message for r in caplog.records)


def test_sanitize_never_raises_on_anything():
    weird = ["", " ", "UPPER.COM", "*.a.b", "a..b", "x.ai", 7, None, ["z"], "ok.com"]
    out = strict.sanitize_domains(weird)
    assert isinstance(out, list)
    assert "upper.com" in out and "a.b" in out and "x.ai" in out and "ok.com" in out


# -- protected_domains --------------------------------------------------------

def test_protected_defaults_to_ai_list():
    out = strict.protected_domains(_strict(enabled=True))
    assert "openai.com" in out and "claude.ai" in out and "x.ai" in out
    assert len(out) == len(strict.DEFAULT_AI_DOMAINS)


def test_protected_appends_user_domains_and_dedupes():
    out = strict.protected_domains(_strict(enabled=True, domains=["myai.dev", "openai.com"]))
    assert "myai.dev" in out
    # openai.com appears once (the curated one wins, user dup dropped)
    assert out.count("openai.com") == 1


def test_protected_without_ai_protect_is_user_only():
    out = strict.protected_domains(_strict(enabled=True, ai_protect=False, domains=["myai.dev"]))
    assert out == ["myai.dev"]


def test_protected_empty_when_nothing_configured():
    # protected_domains lists the names; the enabled gate is in is_active /
    # build_rule (the render call sites). With ai_protect off and no user
    # domains there is nothing to protect.
    assert strict.protected_domains(_strict(enabled=False, ai_protect=False)) == []
    # but the rule itself is None when off, regardless of the name list
    assert strict.build_rule(_strict(enabled=False)) is None


# -- build_rule ---------------------------------------------------------------

def test_build_rule_is_proxy_with_domain_prefix():
    rule = strict.build_rule(_strict(enabled=True, domains=["myai.dev"]))
    assert rule["outboundTag"] == "proxy"
    assert rule["type"] == "field"
    assert "domain:openai.com" in rule["domain"]
    assert "domain:myai.dev" in rule["domain"]
    # every entry is a domain: matcher (suffix matching)
    assert all(d.startswith("domain:") for d in rule["domain"])


def test_build_rule_none_when_off():
    assert strict.build_rule(_strict(enabled=False)) is None
    assert strict.build_rule(None) is None


# -- strip_direct -------------------------------------------------------------

def test_strip_direct_removes_only_direct():
    rules = [
        {"type": "field", "domain": ["geosite:private"], "outboundTag": "direct"},
        {"type": "field", "domain": ["domain:openai.com"], "outboundTag": "proxy"},
        {"type": "field", "domain": ["geosite:category-ads-all"], "outboundTag": "block"},
        {"type": "field", "inboundTag": ["dns-in"], "outboundTag": "dns-out"},
    ]
    out = strict.strip_direct(rules)
    tags = [r["outboundTag"] for r in out]
    assert "direct" not in tags
    assert tags == ["proxy", "block", "dns-out"]


def test_strip_direct_handles_none_and_empty():
    assert strict.strip_direct(None) == []
    assert strict.strip_direct([]) == []


# -- filter_direct_domains ----------------------------------------------------

def test_filter_removes_protected_matchers_keeps_geo():
    direct = ["geosite:category-ir", "domain:ir", "domain:openai.com",
              "full:chatgpt.com", "domain:example.com"]
    out = strict.filter_direct_domains(direct, ["openai.com", "chatgpt.com"])
    assert "domain:openai.com" not in out
    assert "full:chatgpt.com" not in out
    # geo categories and unrelated domains survive
    assert "geosite:category-ir" in out and "domain:ir" in out and "domain:example.com" in out


def test_filter_subdomain_overlap_is_removed():
    out = strict.filter_direct_domains(
        ["domain:api.openai.com", "domain:openai.com"], ["openai.com"]
    )
    assert out == []


def test_filter_noop_when_nothing_protected():
    direct = ["domain:openai.com", "domain:example.com"]
    assert strict.filter_direct_domains(direct, []) == direct
    assert strict.filter_direct_domains(direct, None) == direct


# -- problem (serverless-only incompatibility) --------------------------------

def test_problem_flags_serverless_only_profile():
    only = Profile(name="Serverless only", protocol="serverless", address="",
                   uid="serverless-only")
    msg = strict.problem(only)
    assert msg is not None
    assert "serverless" in msg.lower()


def test_problem_none_for_normal_profile():
    normal = Profile(name="p", protocol="vless", address="1.2.3.4", port=443, id="u")
    assert strict.problem(normal) is None


def test_problem_by_mode_string():
    assert strict.problem("serverless-only") is not None
    assert strict.problem("simple") is None
    assert strict.problem(None) is None


# -- status -------------------------------------------------------------------

def test_status_reflects_state():
    assert "off" in strict.status(_strict(enabled=False)).lower()
    assert "on" in strict.status(_strict(enabled=True)).lower()
    assert "no-direct" in strict.status(_strict(enabled=True, no_direct=True)).lower()
