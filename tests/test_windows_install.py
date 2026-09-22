"""The Windows installer: where an installed build keeps its data, and that
the Inno Setup script and the release workflow still agree with the code.

The path tests drive paths.py directly rather than the real platform, so they
check the Windows branch from any machine.
"""
from __future__ import annotations

import sys
from pathlib import Path

from xrayui import paths
from xrayui.core import updates

ROOT = Path(__file__).resolve().parent.parent
ISS = ROOT / "tools" / "installer.iss"
RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"


def _frozen_at(monkeypatch, exe: Path, *, installed: bool) -> None:
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.touch()
    if installed:
        (exe.parent / paths.INSTALLED_MARKER).touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))


# -- where an installed Windows build writes -------------------------------

def test_an_installed_windows_build_keeps_data_out_of_program_files(monkeypatch, tmp_path):
    """Program Files is not writable, and must not be made writable: an app
    that runs elevated writing into its own install directory is how a
    non-admin gets to choose what the admin's next launch executes."""
    monkeypatch.setattr(paths, "IS_WIN", True)
    exe = tmp_path / "Program Files" / "sushTun" / "sushtun.exe"
    _frozen_at(monkeypatch, exe, installed=True)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))

    assert paths.base_dir() == tmp_path / "ProgramData" / "sushTun"


def test_the_portable_windows_build_still_writes_next_to_itself(monkeypatch, tmp_path):
    """The whole point of the portable build: settings travel with the exe."""
    monkeypatch.setattr(paths, "IS_WIN", True)
    exe = tmp_path / "Downloads" / "sushTun.exe"
    _frozen_at(monkeypatch, exe, installed=False)

    assert paths.base_dir() == exe.parent


def test_a_windows_install_without_programdata_still_has_somewhere_to_write(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(paths, "IS_WIN", True)
    exe = tmp_path / "Program Files" / "sushTun" / "sushtun.exe"
    _frozen_at(monkeypatch, exe, installed=True)
    monkeypatch.delenv("PROGRAMDATA", raising=False)
    monkeypatch.delenv("ALLUSERSPROFILE", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))

    assert paths.base_dir() == tmp_path / "home" / "sushTun"


# -- the installer script and the code agree -------------------------------

def test_the_installer_drops_the_marker_paths_looks_for():
    """Without it an installed build would write into Program Files."""
    assert paths.INSTALLED_MARKER in ISS.read_text(encoding="utf-8")


def test_the_installer_packages_the_one_dir_build_and_asks_for_admin():
    text = ISS.read_text(encoding="utf-8")
    assert r"..\dist\sushtun\*" in text  # SUSHTUN_ONEDIR=1, not the one-file exe
    assert "PrivilegesRequired=admin" in text


def test_the_one_dir_build_asks_for_elevation_too():
    """The installed build changes routes and DNS exactly like the portable
    one; without uac_admin it would start unelevated and fail to connect."""
    spec = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
    onedir = spec[spec.index("if ONEDIR:"):spec.index("else:")]
    assert "uac_admin=IS_WIN" in onedir


def test_the_installer_writes_where_the_workflow_collects_from():
    """Paths in an .iss resolve against the script's own directory, so a bare
    `dist` would leave the installer in tools/dist/ and the release would
    publish nothing."""
    assert r"OutputDir=..\dist" in ISS.read_text(encoding="utf-8")
    assert "path: dist/sushTun-Setup-*.exe" in RELEASE_YML.read_text(encoding="utf-8")


def test_the_installer_removes_the_data_directory_when_uninstalling():
    """Profiles hold server credentials, so leaving them behind is the wrong
    default for someone who just asked for sushTun to be gone."""
    text = ISS.read_text(encoding="utf-8")
    assert "{commonappdata}\\{#AppName}" in text


def test_the_installer_can_replace_a_running_copy():
    """The in-app updater runs this over a live sushTun."""
    text = ISS.read_text(encoding="utf-8")
    assert "CloseApplications=yes" in text
    # The restart manager only restarts apps registered with
    # RegisterApplicationRestart; sushTun is brought back by [Run] instead.
    assert "RestartApplications=no" in text


# -- the release publishes what the updater looks for ----------------------

def test_the_release_workflow_builds_the_installer_the_updater_asks_for():
    text = RELEASE_YML.read_text(encoding="utf-8")
    assert "installer.iss" in text
    # updates.SETUP_ASSET names the file; the workflow's OutputBaseFilename
    # and artifact glob have to produce it.
    assert updates.SETUP_ASSET.format(version="*") in text


def test_the_release_publishes_the_checksums_the_updater_requires():
    """download() refuses to install anything it cannot match against this."""
    text = RELEASE_YML.read_text(encoding="utf-8")
    assert f"sha256sum * > {updates.CHECKSUMS}" in text


def test_every_self_updating_platform_has_an_artifact_in_the_workflow():
    text = RELEASE_YML.read_text(encoding="utf-8")
    for name in (*updates.PORTABLE_ASSETS.values(), updates.PORTABLE_LINUX):
        assert name in text, f"release.yml publishes no {name}"


def _run_entries() -> list[str]:
    text = ISS.read_text(encoding="utf-8")
    section = text.split("\n[Run]\n", 1)[1].split("\n[", 1)[0]  # the header, not a comment
    return [line for line in section.splitlines() if line.startswith("Filename:")]


def test_the_finish_page_launch_can_raise_the_uac_prompt():
    # postinstall runs it as the non-admin user; the manifest requires admin,
    # and only ShellExecute (shellexec) can prompt instead of failing with 740.
    finish = next(e for e in _run_entries() if "postinstall" in e)
    assert "shellexec" in finish and "skipifsilent" in finish


def test_an_update_brings_sushtun_back_through_the_installer():
    relaunch = next(e for e in _run_entries() if "RelaunchAfterUpdate" in e)
    assert "runascurrentuser" in relaunch and "postinstall" not in relaunch
    assert "{param:RELAUNCH|0}" in ISS.read_text(encoding="utf-8")


def test_the_updater_asks_the_installer_to_relaunch(monkeypatch, tmp_path):
    started: list[list[str]] = []
    monkeypatch.setattr(updates.subprocess, "Popen",
                        lambda args, **_k: started.append(list(args)))
    updates._run_installer(tmp_path / "sushTun-setup.exe")
    assert started and started[0][1:] == ["/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS",
                                          "/RELAUNCH=1"]
