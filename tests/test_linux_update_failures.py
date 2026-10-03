"""Update failure injection: no network, package manager or real executables."""
import errno
import hashlib
import io
import os
from pathlib import Path

import pytest

from xrayui.core import updates


@pytest.fixture
def release(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "IS_WIN", False)
    monkeypatch.setattr(updates, "IS_MAC", False)
    monkeypatch.setattr(updates.sys, "platform", "linux")
    monkeypatch.setattr(updates.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updates.paths, "installed", lambda: False)
    monkeypatch.setattr(updates.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(updates, "_expected_digest", lambda *a: hashlib.sha256(b"payload").hexdigest())
    monkeypatch.setattr(updates, "_MIN_SIZE", 1)
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("unmocked network"))
    return updates.Release("v1.0.0", "https://example.org", assets={
        "sushTun-linux": "https://example.org/binary"})


@pytest.mark.parametrize("error", [errno.EROFS, errno.ENOSPC, errno.EACCES])
def test_staging_failure_is_an_update_error(monkeypatch, release, error):
    def fail():
        raise OSError(error, "cannot create staging")
    monkeypatch.setattr(updates, "_staging_dir", fail)
    with pytest.raises(updates.UpdateError, match="cannot create staging"):
        updates.download(release)


def test_disk_full_during_download_cleans_partial_file(monkeypatch, release, tmp_path):
    def fail(url, dest, *args):
        dest.write_bytes(b"part")
        raise OSError(errno.ENOSPC, "disk full")
    monkeypatch.setattr(updates, "_stream_url", fail)
    with pytest.raises(updates.UpdateError, match="disk full"):
        updates.download(release)
    assert not (tmp_path / "update.tmp").exists()


def test_short_http_body_is_rejected(monkeypatch, release, tmp_path):
    class Response(io.BytesIO):
        headers = {"Content-Length": "100"}
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda *a, **k: Response(b"part"))
    with pytest.raises(updates.UpdateError, match="incomplete"):
        updates.download(release)
    assert not (tmp_path / "update.tmp").exists()


def test_mode_failure_preserves_working_binary(monkeypatch, tmp_path):
    current, new = tmp_path / "sushtun", tmp_path / "download"
    current.write_bytes(b"working")
    current.chmod(0o755)
    new.write_bytes(b"replacement")
    monkeypatch.setattr(updates.sys, "executable", str(current))
    monkeypatch.setattr(updates, "IS_WIN", False)
    chmod = Path.chmod
    def fail(path, mode, *a, **k):
        if path == new:
            raise PermissionError("chmod denied")
        return chmod(path, mode, *a, **k)
    monkeypatch.setattr(Path, "chmod", fail)
    with pytest.raises(updates.UpdateError):
        updates._replace_executable(new)
    assert current.read_bytes() == b"working"
    assert current.stat().st_mode & 0o111


@pytest.mark.parametrize("error", [errno.EROFS, errno.ETXTBSY, errno.ENOSPC])
def test_failed_replacement_restores_current_binary(monkeypatch, tmp_path, error):
    current, new = tmp_path / "sushtun", tmp_path / "download"
    current.write_bytes(b"working")
    new.write_bytes(b"replacement")
    monkeypatch.setattr(updates.sys, "executable", str(current))
    monkeypatch.setattr(updates, "IS_WIN", False)
    replace = updates.os.replace
    def fail(src, dst):
        if src == new:
            raise OSError(error, "replacement failed")
        return replace(src, dst)
    monkeypatch.setattr(updates.os, "replace", fail)
    with pytest.raises(updates.UpdateError):
        updates._replace_executable(new)
    assert current.read_bytes() == b"working"

def test_wrong_arch_linux_cannot_update(monkeypatch, release):
    import platform
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(updates.sys, "platform", "linux")
    assert updates.asset_for_this_build(release) is None


def test_checksum_mismatch_cleans_file(monkeypatch, release, tmp_path):
    monkeypatch.setattr(updates, "_expected_digest", lambda *a: "abc")
    def stream(*args):
        args[1].write_bytes(b"content")
    monkeypatch.setattr(updates, "_stream_url", stream)
    with pytest.raises(updates.UpdateError, match="checksum"):
        updates.download(release)
    assert not (tmp_path / "update.tmp").exists()



def test_attribute_errors_are_ignored_when_the_result_already_matches(monkeypatch, tmp_path):
    # A portable copy on FAT/exFAT: chmod and chown are refused, but the
    # download already carries the right owner, so the update must go on.
    current, new = tmp_path / "sushTun", tmp_path / "sushTun.new"
    current.write_bytes(b"old")
    new.write_bytes(b"new")
    current.chmod(0o755)
    new.chmod(0o755)

    def refuse(*args, **kwargs):
        raise PermissionError(errno.EPERM, "not supported")

    monkeypatch.setattr(updates.Path, "chmod", refuse)
    monkeypatch.setattr(updates.os, "chown", refuse)
    updates._copy_attributes(current, new)


def test_attribute_errors_still_fail_when_the_owner_would_differ(monkeypatch, tmp_path):
    current, new = tmp_path / "sushTun", tmp_path / "sushTun.new"
    current.write_bytes(b"old")
    new.write_bytes(b"new")
    real_stat = updates.Path.stat

    def stat(self, *args, **kwargs):
        st = real_stat(self, *args, **kwargs)
        if self == new:
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                                   st.st_uid + 1, st.st_gid, st.st_size,
                                   st.st_atime, st.st_mtime, st.st_ctime))
        return st

    def refuse(*args, **kwargs):
        raise PermissionError(errno.EPERM, "not permitted")

    monkeypatch.setattr(updates.Path, "stat", stat)
    monkeypatch.setattr(updates.os, "chown", refuse)
    monkeypatch.setattr(updates, "IS_WIN", False)
    with pytest.raises(OSError):
        updates._copy_attributes(current, new)
