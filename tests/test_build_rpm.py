"""The .rpm file list and spec come from the same staged tree as the .deb."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("build_rpm", ROOT / "scripts" / "build_rpm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_files_section_lists_dirs_files_and_symlinks(tmp_path):
    rpm = _load()
    (tmp_path / "opt/sushtun").mkdir(parents=True)
    (tmp_path / "opt/sushtun/sushtun").write_text("x")
    (tmp_path / "usr/bin").mkdir(parents=True)
    (tmp_path / "usr/bin/sushtun").symlink_to("/opt/sushtun/sushtun")
    lines = rpm.files_section(tmp_path).splitlines()
    assert "%dir /opt/sushtun" in lines
    assert "/opt/sushtun/sushtun" in lines
    assert "/usr/bin/sushtun" in lines and "%dir /usr/bin/sushtun" not in lines


def test_spec_carries_version_and_cleans_the_polkit_rule_only_on_removal(tmp_path):
    rpm = _load()
    (tmp_path / "opt").mkdir()
    text = rpm.spec_text(tmp_path, "1.2.3")
    assert "Version:        1.2.3" in text
    assert "@" not in text.replace("soroushdeimi@", "")
    assert '[ "$1" = 0 ]' in text
    assert "%dir /opt" in text
