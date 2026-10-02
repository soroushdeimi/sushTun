import re
from pathlib import Path

import pytest

CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _text() -> str:
    return CI.read_text(encoding="utf-8")


def test_text_has_macos_job_and_dispatch():
    text = _text()
    assert re.search(r"^\s*workflow_dispatch:", text, re.M)
    assert re.search(r"^  test-macos:", text, re.M)
    assert "macos-latest" in text
    assert "pytest -q -rs" in text
    assert "Pasteboard seen from root" in text
    assert "continue-on-error: true" in text
    assert "PASTEBOARD: root_sees_token=" in text


def test_text_ubuntu_job_keeps_ruff_and_pytest():
    head = _text().split("  test-macos:")[0]
    assert "ruff check ." in head
    assert "python -m pytest -q" in head
    assert "ubuntu-latest" in head


@pytest.fixture
def wf():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(_text())


def _on(wf):
    # PyYAML parses the bare key `on` as boolean True.
    return wf.get("on", wf.get(True))


def test_yaml_triggers(wf):
    assert "workflow_dispatch" in _on(wf)


def test_yaml_ubuntu_job_unchanged(wf):
    job = wf["jobs"]["test"]
    assert job["runs-on"] == "ubuntu-latest"
    runs = [s.get("run", "") for s in job["steps"]]
    assert "ruff check ." in runs
    assert "python -m pytest -q" in runs


def test_yaml_macos_job(wf):
    job = wf["jobs"]["test-macos"]
    assert job["runs-on"] == "macos-latest"
    runs = [s.get("run", "") for s in job["steps"]]
    assert any("requirements-dev.txt" in r for r in runs)
    assert any("scripts/fetch_deps.py" in r for r in runs)
    pytest_steps = [s for s in job["steps"] if "pytest" in s.get("run", "")]
    assert pytest_steps
    assert "-rs" in pytest_steps[0]["run"]
    assert pytest_steps[0]["env"]["QT_QPA_PLATFORM"] == "offscreen"


def test_yaml_pasteboard_step(wf):
    steps = wf["jobs"]["test-macos"]["steps"]
    step = next(s for s in steps if s.get("name") == "Pasteboard seen from root")
    assert step["continue-on-error"] is True
    assert steps.index(step) > max(
        i for i, s in enumerate(steps) if "pytest" in s.get("run", ""))
    assert "set -u" in step["run"]
    assert "set -e" not in step["run"]
    assert "session_user" in step["run"] and "_as_user" in step["run"]


def test_yaml_pasteboard_uses_absolute_interpreter_under_sudo(wf):
    steps = wf["jobs"]["test-macos"]["steps"]
    run = next(s for s in steps if s.get("name") == "Pasteboard seen from root")["run"]
    assert 'PY="$(command -v python)"' in run
    assert '"$PY" -c' in run
