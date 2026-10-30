"""scripts/fetch_deps.py pins the Xray release that the tests and the
shipped builds are verified against, instead of following `latest`."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_deps.py"


@pytest.fixture
def deps():
    spec = importlib.util.spec_from_file_location("fetch_deps_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_xray_is_pinned_not_latest(deps, monkeypatch):
    monkeypatch.delenv("SUSHTUN_XRAY_VERSION", raising=False)
    url = deps.xray_url("Xray-linux-64.zip")
    assert "/latest/" not in url
    assert url == (f"https://github.com/XTLS/Xray-core/releases/download/"
                   f"{deps.XRAY_VERSION}/Xray-linux-64.zip")
    assert deps.XRAY_VERSION.startswith("v")


def test_version_can_be_overridden_to_try_a_newer_core(deps, monkeypatch):
    monkeypatch.setenv("SUSHTUN_XRAY_VERSION", "v99.1.2")
    assert deps.xray_url("a.zip").endswith("/download/v99.1.2/a.zip")


@pytest.mark.parametrize("bad", ["latest", "26.3.27", "v1.2", "v1.2.3/../x", "v1.2.3 ", ""])
def test_a_malformed_override_is_refused(deps, monkeypatch, bad):
    monkeypatch.setenv("SUSHTUN_XRAY_VERSION", bad)
    if bad == "":
        assert deps.xray_url("a.zip").endswith(f"/{deps.XRAY_VERSION}/a.zip")  # empty = unset
    else:
        with pytest.raises(SystemExit):
            deps.xray_url("a.zip")
