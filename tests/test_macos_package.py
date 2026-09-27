"""The macOS package: a signed .app inside a .dmg, with its data outside it.

A bare Unix executable is not something macOS can open -- a download loses its
+x bit, so Finder shows it as a document and a double-click does nothing. The
release therefore ships an .app in a .dmg. Nothing here can build or launch a
macOS bundle on Linux, so these are text checks on the spec and the workflow
plus real unit tests for the two code paths a bundle changes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import updates

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


# -- what the build produces -------------------------------------------------
def test_the_spec_bundles_an_app_for_macos():
    assert "BUNDLE(" in SPEC
    assert 'name="sushTun.app"' in SPEC
    # From the one-dir tree: the one-file build re-extracts ~170 MB per launch.
    assert SPEC.index("if ONEDIR:") < SPEC.index("BUNDLE(")


def test_the_app_carries_a_real_version_not_a_placeholder():
    assert '"CFBundleShortVersionString": VERSION' in SPEC
    assert '__version__' in SPEC  # read out of the package, not hard-coded


def test_the_release_workflow_builds_signs_and_packages_the_dmg():
    job = WORKFLOW[WORKFLOW.index("  macos-app:"):WORKFLOW.index("  deb:")]
    assert "runs-on: macos-latest" in job
    assert 'SUSHTUN_ONEDIR: "1"' in job          # the .app wraps the one-dir tree
    assert "iconutil -c icns" in job             # a real icon, not the default
    assert "codesign --force --deep --sign -" in job
    assert "hdiutil create" in job
    assert "ln -s /Applications dmg/Applications" in job  # the drag-here window
    assert "sushTun-macos.dmg" in job


def test_the_app_is_marked_installed_so_it_never_writes_inside_itself():
    assert 'touch "dist/sushTun.app/Contents/MacOS/.installed"' in WORKFLOW
    # Before signing: the signature seals everything under Contents.
    assert WORKFLOW.index(".installed") < WORKFLOW.index("codesign --force")


def test_publishing_waits_for_the_dmg():
    assert "needs: [build, windows-installer, macos-app, deb]" in WORKFLOW


def test_the_raw_macos_binary_is_still_published():
    # updates.PORTABLE_ASSETS looks for this exact name; dropping it would
    # strand everyone already running the portable macOS build.
    assert "artifact: sushTun-macos" in WORKFLOW
    assert updates.PORTABLE_ASSETS["darwin"] == "sushTun-macos"


# -- where an installed .app keeps its data ----------------------------------
@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(paths, "IS_WIN", False)
    monkeypatch.setattr(paths, "IS_MAC", True)


def test_an_elevated_app_uses_the_machine_wide_application_support(mac, monkeypatch):
    monkeypatch.setattr(paths.os, "geteuid", lambda: 0)
    assert paths._installed_data_dir() == Path("/Library/Application Support/sushTun")


def test_an_unelevated_app_falls_back_to_the_users_own_library(mac, monkeypatch):
    monkeypatch.setattr(paths.os, "geteuid", lambda: 501)
    assert paths._installed_data_dir() == \
        Path.home() / "Library" / "Application Support" / "sushTun"


def test_linux_is_untouched_by_the_macos_branch(monkeypatch):
    monkeypatch.setattr(paths, "IS_WIN", False)
    monkeypatch.setattr(paths, "IS_MAC", False)
    monkeypatch.setattr(paths.os, "geteuid", lambda: 0)
    assert paths._installed_data_dir() == paths.INSTALLED_DATA_DIR


# -- how an installed .app updates -------------------------------------------
def test_an_installed_app_is_sent_to_the_release_page(monkeypatch):
    # Overwriting the executable inside the bundle breaks the signature sealed
    # over it, and Gatekeeper then refuses to launch the app at all.
    monkeypatch.setattr(updates, "IS_WIN", False)
    monkeypatch.setattr(updates, "IS_MAC", True)
    monkeypatch.setattr(updates.paths, "installed", lambda: True)
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    release = updates.Release(tag="v9.9.9", url="https://x",
                              assets={"sushTun-macos": "https://x/bin"})
    assert updates.installed_macos_app() is True
    assert updates.asset_for_this_build(release) is None


def test_the_portable_macos_build_still_updates_itself(monkeypatch):
    monkeypatch.setattr(updates, "IS_WIN", False)
    monkeypatch.setattr(updates, "IS_MAC", True)
    monkeypatch.setattr(updates.paths, "installed", lambda: False)
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updates.sys, "platform", "darwin")
    release = updates.Release(tag="v9.9.9", url="https://x",
                              assets={"sushTun-macos": "https://x/bin"})
    assert updates.installed_macos_app() is False
    assert updates.asset_for_this_build(release) == "sushTun-macos"
