"""macOS pf firewall backend: exact argv, rule text, ordering, rollback,
idempotency, and the round-trip safety checks.

The real pfctl cannot be run without root, so a stateful fake simulates the
anchor/main-ruleset/enable-token state machine and records every argv. The
generated ruleset text is additionally validated against the real pfctl binary
with `pfctl -nf` (no root needed) on macOS.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from xrayui import paths
from xrayui.core import _firewall_macos as mac
from xrayui.core._firewall_common import FirewallError

NS = SimpleNamespace

# A realistic /etc/pf.conf: Apple's anchors, nothing else.
PFCONF = (
    'scrub-anchor "com.apple/*"\n'
    'nat-anchor "com.apple/*"\n'
    'rdr-anchor "com.apple/*"\n'
    'dummynet-anchor "com.apple/*"\n'
    'anchor "com.apple/*"\n'
    'load anchor "com.apple" from "/etc/pf.anchors/com.apple"\n'
)


class FakePfctl:
    """Simulates pfctl's anchor / main-ruleset / enable-token state machine."""

    def __init__(self, main_ruleset=PFCONF, anchor_rules=""):
        self.main = main_ruleset
        self.anchor = anchor_rules
        self.enabled = False
        self.token = "123456"
        self.calls: list[list[str]] = []
        self.main_loaded = None   # content last loaded into the main ruleset
        self.anchor_loaded = None  # content last loaded into the anchor
        self.fail_nf = False
        self.fail_anchor_load = False
        self.fail_enable = False

    def run(self, args, **_k):
        self.calls.append(list(args))
        rest = list(args[1:])
        if rest and rest[0] == "-a":
            if "-sr" in rest:
                return NS(returncode=0, stdout=self.anchor, stderr="")
            if "-f" in rest:
                if self.fail_anchor_load:
                    return NS(returncode=1, stdout="", stderr="forced")
                content = Path(rest[rest.index("-f") + 1]).read_text()
                self.anchor = content
                self.anchor_loaded = content
                return NS(returncode=0, stdout="", stderr="")
            if "-F" in rest:
                self.anchor = ""
                return NS(returncode=0, stdout="", stderr="")
        if "-nf" in rest:
            if self.fail_nf:
                return NS(returncode=1, stdout="", stderr="syntax error")
            return NS(returncode=0, stdout="", stderr="")
        if "-sr" in rest:
            return NS(returncode=0, stdout=self.main, stderr="")
        if "-f" in rest:
            content = Path(rest[rest.index("-f") + 1]).read_text()
            self.main = content
            self.main_loaded = content
            return NS(returncode=0, stdout="", stderr="")
        if "-E" in rest:
            if self.fail_enable:
                return NS(returncode=1, stdout="", stderr="forced")
            self.enabled = True
            return NS(returncode=0, stdout=f"Enabled {self.token}", stderr="")
        if "-X" in rest:
            self.enabled = False
            return NS(returncode=0, stdout="", stderr="")
        if "-s" in rest and "info" in rest:
            state = "enabled" if self.enabled else "disabled"
            return NS(returncode=0, stdout=f"Status: {state}", stderr="")
        return NS(returncode=0, stdout="", stderr="")


@pytest.fixture
def fake(monkeypatch, tmp_path):
    pf = FakePfctl()
    monkeypatch.setattr(mac.proc, "run", pf.run)
    monkeypatch.setattr(mac, "_read_main_ruleset", lambda: PFCONF)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(mac, "supported", lambda: True)
    return pf


# -- rule text ---------------------------------------------------------------
def test_ruleset_allows_tunnel_servers_loopback_then_blocks():
    text = mac.build_ruleset("utun233", ["1.2.3.4", "2001:db8::1"], allow_lan=False)
    lines = text.splitlines()
    assert lines[0] == "pass out quick on utun233"
    assert "pass out quick inet from any to 1.2.3.4" in lines
    assert "pass out quick inet6 from any to 2001:db8::1" in lines
    assert "pass out quick on lo0" in lines
    assert lines[-1] == "block out quick"
    # The block must be last: every allow precedes it.
    assert lines.index("block out quick") == len(lines) - 1


def test_ruleset_includes_lan_and_dhcp_only_when_allowed():
    with_lan = mac.build_ruleset("utun233", ["1.2.3.4"], allow_lan=True)
    assert "pass out quick inet from any to 10.0.0.0/8" in with_lan
    assert "pass out quick inet from any to 192.168.0.0/16" in with_lan
    assert "pass out quick inet6 from any to fe80::/10" in with_lan
    assert "pass out quick inet proto udp from any port 68 to any port 67" in with_lan
    assert "pass out quick inet6 proto udp from any port 547 to any port 546" in with_lan

    without = mac.build_ruleset("utun233", ["1.2.3.4"], allow_lan=False)
    assert "10.0.0.0/8" not in without
    assert "fe80::/10" not in without
    assert "port 68" not in without


def test_ruleset_drops_unparseable_server_ips():
    text = mac.build_ruleset("utun233", ["not-an-ip", "1.2.3.4"], allow_lan=False)
    assert "not-an-ip" not in text
    assert "pass out quick inet from any to 1.2.3.4" in text


@pytest.mark.skipif(sys.platform != "darwin", reason="needs the real pfctl binary")
def test_generated_ruleset_passes_real_pfctl_syntax_check(tmp_path):
    text = mac.build_ruleset("utun233", ["1.2.3.4", "2001:db8::1"], allow_lan=True)
    f = tmp_path / "rules"
    f.write_text(text)
    import subprocess
    assert subprocess.run(["pfctl", "-nf", str(f)], capture_output=True).returncode == 0


# -- install happy path ------------------------------------------------------
def test_install_loads_anchor_reference_then_rules_then_enables(fake):
    mac.install("utun233", ["1.2.3.4"], allow_lan=True)

    # The main ruleset was reloaded with our anchor line added before Apple's
    # filter anchor (line-based: the substring also appears in scrub-anchor).
    lines = fake.main_loaded.splitlines()
    assert 'anchor "sushtun"' in lines
    assert lines.index('anchor "sushtun"') < lines.index('anchor "com.apple/*"')
    # The anchor rules were loaded, block last.
    assert fake.anchor_loaded is not None
    assert fake.anchor_loaded.splitlines()[-1] == "block out quick"
    # pf was enabled with a token.
    assert fake.enabled is True
    # The anchor-load argv is exactly right.
    assert ["pfctl", "-a", "sushtun", "-f"] in [c[:4] for c in fake.calls]


def test_install_saves_state_with_token_and_original(fake, tmp_path):
    mac.install("utun233", ["1.2.3.4"], allow_lan=False)
    state = mac.load_state()
    assert state["kind"] == "macos"
    assert state["token"] == "123456"
    assert state["original"] == PFCONF
    assert (tmp_path / "firewall.json").exists()


# -- install refusal / rollback ---------------------------------------------
def test_install_refuses_when_combined_ruleset_fails_validation(fake):
    fake.fail_nf = True
    with pytest.raises(FirewallError, match="validation"):
        mac.install("utun233", ["1.2.3.4"], allow_lan=True)
    # Nothing was loaded into the main ruleset or the anchor.
    assert fake.main_loaded is None
    assert fake.anchor_loaded is None
    assert mac.load_state() is None


def test_install_refuses_when_live_ruleset_has_foreign_anchor(fake):
    # Another app added a runtime anchor that /etc/pf.conf does not know about.
    fake.main = PFCONF + 'anchor "otherapp"\n'
    with pytest.raises(FirewallError, match="round-trip"):
        mac.install("utun233", ["1.2.3.4"], allow_lan=True)
    assert fake.main_loaded is None
    assert fake.anchor_loaded is None


def test_install_rolls_back_when_anchor_load_fails(fake):
    fake.fail_anchor_load = True
    with pytest.raises(FirewallError, match="anchor rules"):
        mac.install("utun233", ["1.2.3.4"], allow_lan=True)
    # The main ruleset was restored to the original (no sushtun anchor).
    assert 'anchor "sushtun"' not in fake.main
    # The anchor was flushed and the state cleared.
    assert fake.anchor == ""
    assert mac.load_state() is None


def test_install_rolls_back_when_enable_fails(fake):
    fake.fail_enable = True
    with pytest.raises(FirewallError, match="enable pf"):
        mac.install("utun233", ["1.2.3.4"], allow_lan=True)
    assert 'anchor "sushtun"' not in fake.main
    assert mac.load_state() is None


# -- remove ------------------------------------------------------------------
def test_remove_is_idempotent_with_no_state(fake):
    # No state file: remove must not reload the main ruleset or touch the anchor.
    before = list(fake.calls)
    assert mac.remove() == []
    # Only the existence check ran; no -f / -F / -X.
    new = fake.calls[len(before):]
    assert all("-f" not in c and "-F" not in c and "-X" not in c for c in new)


def test_remove_restores_original_and_releases_token(fake):
    mac.install("utun233", ["1.2.3.4"], allow_lan=True)
    assert fake.enabled is True
    warnings = mac.remove()
    assert warnings == []
    # Main ruleset restored to the exact original (no sushtun anchor).
    assert fake.main == PFCONF
    assert 'anchor "sushtun"' not in fake.main
    # Anchor flushed and token released.
    assert fake.anchor == ""
    assert fake.enabled is False
    assert mac.load_state() is None


def test_remove_after_partial_install_leaves_no_lockdown(fake):
    # Simulate a crash after the main ruleset was reloaded but before the
    # anchor rules were loaded: state has the original, anchor is empty.
    fake.main = mac._insert_anchor_line(PFCONF)
    mac.save_state({"kind": "macos", "original": PFCONF, "token": "", "ruleset": ""})
    warnings = mac.remove()
    assert warnings == []
    assert fake.main == PFCONF
    assert mac.load_state() is None


def test_remove_reports_a_stray_anchor_it_cannot_account_for(fake):
    # The anchor reference is present but there is no saved state: we must not
    # blindly rewrite the main ruleset, and we must say so.
    fake.main = mac._insert_anchor_line(PFCONF)
    warnings = mac.remove()
    assert any("no saved state" in w for w in warnings)
    # The main ruleset was left untouched.
    assert 'anchor "sushtun"' in fake.main


# -- is_active ---------------------------------------------------------------
def test_is_active_requires_anchor_and_rules(fake):
    assert mac.is_active() is False  # nothing installed
    mac.install("utun233", ["1.2.3.4"], allow_lan=False)
    assert mac.is_active() is True
    mac.remove()
    assert mac.is_active() is False
