"""The in-app updater: version comparison, what each build can install,
downloading with its checksum check, and swapping the executable."""
from __future__ import annotations

import hashlib

import pytest

from xrayui.core import updates


# -- is_newer -----------------------------------------------------------------
def test_is_newer_true_for_a_higher_version():
    assert updates.is_newer("v0.2.0", "0.1.13") is True


def test_is_newer_false_for_the_same_or_older_version():
    assert updates.is_newer("v0.1.13", "0.1.13") is False
    assert updates.is_newer("v0.1.0", "0.1.13") is False


def test_is_newer_false_for_a_prerelease_or_non_numeric_tag():
    assert updates.is_newer("v0.2.0-rc1", "0.1.13") is False
    assert updates.is_newer("nightly", "0.1.13") is False
    assert updates.is_newer("", "0.1.13") is False


def test_is_newer_handles_missing_v_prefix():
    assert updates.is_newer("0.2.0", "0.1.13") is True


def test_is_newer_compares_numerically_not_lexically():
    # "0.9.0" < "0.10.0" numerically, but ">" lexically as strings.
    assert updates.is_newer("v0.10.0", "0.9.0") is True


# -- latest_release -------------------------------------------------------
# Trimmed from a real GitHub /releases/latest response.
API_RESPONSE = {
    "tag_name": "v0.5.0",
    "html_url": "https://github.com/soroushdeimi/sushTun/releases/tag/v0.5.0",
    "body": "### Fixed\n- things",
    "assets": [
        {"name": "sushTun-windows.exe",
         "browser_download_url": "https://example.com/sushTun-windows.exe"},
        {"name": "sushTun-Setup-0.5.0.exe",
         "browser_download_url": "https://example.com/sushTun-Setup-0.5.0.exe"},
        {"name": "sushTun-linux", "browser_download_url": "https://example.com/sushTun-linux"},
        {"name": "sushTun-macos", "browser_download_url": "https://example.com/sushTun-macos"},
        {"name": "SHA256SUMS", "browser_download_url": "https://example.com/SHA256SUMS"},
    ],
}


def test_latest_release_carries_tag_notes_and_assets():
    release = updates.latest_release(fetch=lambda: API_RESPONSE)
    assert release.tag == "v0.5.0"
    assert release.version == "0.5.0"
    assert release.notes.startswith("### Fixed")
    assert release.assets["SHA256SUMS"] == "https://example.com/SHA256SUMS"


def test_latest_release_returns_none_on_fetch_failure():
    def fetch():
        raise TimeoutError("no network")
    assert updates.latest_release(fetch=fetch) is None


def test_latest_release_returns_none_on_malformed_response():
    assert updates.latest_release(fetch=lambda: "not a dict") is None
    assert updates.latest_release(fetch=lambda: {}) is None
    assert updates.latest_release(fetch=lambda: {"tag_name": "v1"}) is None


def test_latest_release_survives_a_release_with_no_assets():
    """A draft published without binaries must not break the check -- the
    dialog falls back to the release page."""
    release = updates.latest_release(
        fetch=lambda: {"tag_name": "v1.0.0", "html_url": "https://x"})
    assert release.assets == {} and release.notes == ""


def test_latest_release_skips_malformed_asset_entries():
    release = updates.latest_release(fetch=lambda: {
        "tag_name": "v1.0.0", "html_url": "https://x",
        "assets": ["nonsense", {"name": "good", "browser_download_url": "https://y"},
                   {"name": "no-url"}]})
    assert release.assets == {"good": "https://y"}


def test_default_fetch_sends_the_app_user_agent(monkeypatch):
    captured = {}

    class FakeResp:
        def read(self):
            return b'{"tag_name": "v1.0.0", "html_url": "https://x"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=10):
        captured["header"] = req.get_header("User-agent")
        captured["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr(updates.urllib.request, "urlopen", fake_urlopen)
    release = updates.latest_release()
    assert release.tag == "v1.0.0"
    assert captured["header"].startswith("sushTun/")
    assert captured["url"] == updates._API_URL


# -- which asset this build installs ---------------------------------------

def _release() -> updates.Release:
    return updates.latest_release(fetch=lambda: API_RESPONSE)


def _build(monkeypatch, platform, *, installed=False, frozen=True):
    monkeypatch.setattr(updates.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(updates.sys, "platform", platform)
    monkeypatch.setattr(updates, "IS_WIN", platform == "win32")
    monkeypatch.setattr(updates, "IS_MAC", platform == "darwin")
    monkeypatch.setattr(updates.paths, "installed", lambda: installed)


def test_portable_builds_install_their_own_binary(monkeypatch):
    for platform, expected in (("win32", "sushTun-windows.exe"),
                               ("linux", "sushTun-linux"),
                               ("darwin", "sushTun-macos")):
        _build(monkeypatch, platform)
        assert updates.asset_for_this_build(_release()) == expected


def test_an_installed_windows_build_installs_the_setup_exe(monkeypatch):
    """Overwriting files under Program Files behind the installer's back
    leaves Add/Remove Programs describing a version that is not there."""
    _build(monkeypatch, "win32", installed=True)
    assert updates.asset_for_this_build(_release()) == "sushTun-Setup-0.5.0.exe"
    assert updates.installed_windows() and not updates.installed_deb()


def test_the_deb_is_left_to_dpkg(monkeypatch):
    _build(monkeypatch, "linux", installed=True)
    assert updates.asset_for_this_build(_release()) is None
    assert updates.installed_deb()


def test_a_source_checkout_never_installs_a_binary(monkeypatch):
    _build(monkeypatch, "win32", frozen=False)
    assert updates.asset_for_this_build(_release()) is None


def test_an_asset_the_release_does_not_have_is_not_offered(monkeypatch):
    """A release that failed to publish the installer must not send an
    installed build chasing a URL that is not there."""
    _build(monkeypatch, "win32", installed=True)
    thin = updates.Release(tag="v0.9.0", url="https://x",
                           assets={"sushTun-windows.exe": "https://y"})
    assert updates.asset_for_this_build(thin) is None


# -- checksums --------------------------------------------------------------

def test_parse_checksums_reads_sha256sum_output():
    text = ("a" * 64 + "  sushTun-linux\n"
            + "B" * 64 + " *sushTun-windows.exe\n")
    parsed = updates.parse_checksums(text)
    assert parsed["sushTun-linux"] == "a" * 64
    # sha256sum's `*` binary marker is not part of the name, and the digest is
    # compared lower-case whichever way the tool wrote it.
    assert parsed["sushTun-windows.exe"] == "b" * 64


def test_parse_checksums_ignores_anything_that_is_not_a_digest_line():
    parsed = updates.parse_checksums(
        "# a comment\n\nnot-a-digest  file\n" + "b" * 64 + "  real\n")
    assert parsed == {"real": "b" * 64}


def test_sha256_file_matches_hashlib(tmp_path):
    blob = tmp_path / "blob"
    blob.write_bytes(b"sushTun" * 1000)
    assert updates.sha256_file(blob) == hashlib.sha256(b"sushTun" * 1000).hexdigest()


# -- downloading ------------------------------------------------------------

def _stub_download(monkeypatch, tmp_path, payload: bytes, sums: str | None = None):
    """Stub the two network calls and point staging at a temp directory."""
    digest = hashlib.sha256(payload).hexdigest()
    text = sums if sums is not None else f"{digest}  sushTun-linux\n"
    monkeypatch.setattr(updates, "_read_url", lambda url, timeout=30: text.encode())

    def stream(url, dest, on_progress, cancelled, timeout=60.0):
        if cancelled is not None and cancelled():
            raise updates.UpdateError("cancelled")
        dest.write_bytes(payload)
        if on_progress is not None:
            on_progress(len(payload), len(payload))

    monkeypatch.setattr(updates, "_stream_url", stream)
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(updates, "_staging_dir", lambda: staging)
    return staging


def test_download_verifies_the_checksum_and_reports_progress(monkeypatch, tmp_path):
    _build(monkeypatch, "linux")
    payload = b"x" * (updates._MIN_SIZE + 10)
    _stub_download(monkeypatch, tmp_path, payload)
    seen = []
    path = updates.download(_release(), on_progress=lambda d, t: seen.append((d, t)))
    assert path.read_bytes() == payload
    assert seen == [(len(payload), len(payload))]


def test_download_refuses_a_file_that_does_not_match_the_checksum(monkeypatch, tmp_path):
    _build(monkeypatch, "linux")
    payload = b"x" * (updates._MIN_SIZE + 10)
    staging = _stub_download(monkeypatch, tmp_path, payload, sums="c" * 64 + "  sushTun-linux\n")
    with pytest.raises(updates.UpdateError, match="checksum"):
        updates.download(_release())
    assert not staging.exists()  # nothing half-downloaded is left behind


def test_download_refuses_a_truncated_file(monkeypatch, tmp_path):
    """An error page served with a 200 is the usual shape of this."""
    _build(monkeypatch, "linux")
    _stub_download(monkeypatch, tmp_path, b"<html>404</html>")
    with pytest.raises(updates.UpdateError, match="truncated"):
        updates.download(_release())


def test_download_refuses_when_the_release_publishes_no_checksums(monkeypatch, tmp_path):
    _build(monkeypatch, "linux")
    _stub_download(monkeypatch, tmp_path, b"x" * (updates._MIN_SIZE + 10))
    bare = updates.Release(tag="v0.5.0", url="https://x",
                           assets={"sushTun-linux": "https://y"})
    with pytest.raises(updates.UpdateError, match="SHA256SUMS"):
        updates.download(bare)


def test_download_refuses_when_the_checksums_omit_this_asset(monkeypatch, tmp_path):
    _build(monkeypatch, "linux")
    _stub_download(monkeypatch, tmp_path, b"x" * (updates._MIN_SIZE + 10),
                   sums="d" * 64 + "  something-else\n")
    with pytest.raises(updates.UpdateError, match="does not list"):
        updates.download(_release())


def test_download_refuses_on_a_build_that_cannot_update_itself(monkeypatch, tmp_path):
    _build(monkeypatch, "linux", installed=True)
    with pytest.raises(updates.UpdateError, match="cannot update itself"):
        updates.download(_release())


# -- swapping the executable ------------------------------------------------

def _fake_exe(monkeypatch, tmp_path, name="sushTun"):
    exe = tmp_path / name
    exe.write_bytes(b"old version")
    monkeypatch.setattr(updates.sys, "executable", str(exe))
    return exe


def test_replacing_the_executable_keeps_the_old_one_aside_on_windows(monkeypatch, tmp_path):
    """Windows will not free the name of a running .exe until the process
    exits, so the old one is renamed and swept up on the next launch."""
    monkeypatch.setattr(updates, "IS_WIN", True)
    exe = _fake_exe(monkeypatch, tmp_path, "sushTun.exe")
    new = tmp_path / "download.exe"
    new.write_bytes(b"new version")

    updates._replace_executable(new)

    assert exe.read_bytes() == b"new version"
    assert (tmp_path / ("sushTun.exe" + updates.OLD_SUFFIX)).read_bytes() == b"old version"


def test_replacing_the_executable_cleans_up_after_itself_on_posix(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "IS_WIN", False)
    exe = _fake_exe(monkeypatch, tmp_path)
    new = tmp_path / "download"
    new.write_bytes(b"new version")

    updates._replace_executable(new)

    assert exe.read_bytes() == b"new version"
    assert not (tmp_path / ("sushTun" + updates.OLD_SUFFIX)).exists()


def test_a_failed_swap_puts_the_working_copy_back(monkeypatch, tmp_path):
    """Better an un-updated sushTun than no sushTun at all."""
    monkeypatch.setattr(updates, "IS_WIN", True)
    exe = _fake_exe(monkeypatch, tmp_path, "sushTun.exe")
    new = tmp_path / "download.exe"
    new.write_bytes(b"new version")
    real_replace = updates.os.replace
    calls = []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) == 2:  # the second move is the new file into place
            raise OSError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(updates.os, "replace", flaky)
    with pytest.raises(updates.UpdateError, match="could not put the new version"):
        updates._replace_executable(new)
    assert exe.read_bytes() == b"old version"


def test_clean_previous_is_a_no_op_in_a_source_run(monkeypatch):
    monkeypatch.setattr(updates.sys, "frozen", False, raising=False)
    updates.clean_previous()  # must not raise, must not touch anything


def test_clean_previous_removes_last_updates_leftovers(monkeypatch, tmp_path):
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    exe = _fake_exe(monkeypatch, tmp_path, "sushTun.exe")
    aside = exe.with_name(exe.name + updates.OLD_SUFFIX)
    aside.write_bytes(b"older")
    staging = tmp_path / "update.tmp"
    staging.mkdir()
    monkeypatch.setattr(updates.paths, "base_dir", lambda: tmp_path)

    updates.clean_previous()

    assert not aside.exists() and not staging.exists()
