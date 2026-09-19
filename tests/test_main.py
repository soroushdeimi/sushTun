"""Entry point: the --autostart flag reaches ui.app.run()."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from xrayui import __main__ as main_mod  # noqa: E402
from xrayui import elevate, paths  # noqa: E402
from xrayui.ui import app as app_mod  # noqa: E402
from xrayui.ui import single_instance  # noqa: E402


def _stub_common(monkeypatch, argv):
    monkeypatch.setattr(main_mod.sys, "argv", argv)
    monkeypatch.setattr(elevate, "apply_session_env", lambda a: a)
    monkeypatch.setattr(elevate, "is_admin", lambda: True)
    monkeypatch.setattr(elevate, "relaunch_as_admin", lambda: False)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: None)
    # Never knock on a real sushTun running on the test machine.
    monkeypatch.setattr(single_instance, "notify_running", lambda **kw: False)
    captured = {}
    monkeypatch.setattr(app_mod, "run", lambda argv, **kw: captured.update(argv=argv, **kw)
                        or 0)
    return captured


def test_main_passes_the_autostart_flag_through(monkeypatch):
    captured = _stub_common(monkeypatch, ["sushtun", "--autostart"])
    assert main_mod.main() == 0
    assert captured["autostart"] is True


def test_main_without_the_flag_does_not_set_autostart(monkeypatch):
    captured = _stub_common(monkeypatch, ["sushtun"])
    assert main_mod.main() == 0
    assert captured["autostart"] is False


def test_a_second_launch_hands_over_before_asking_for_the_password(monkeypatch):
    captured = _stub_common(monkeypatch, ["sushtun"])
    knocks, elevations = [], []
    monkeypatch.setattr(elevate, "is_admin", lambda: False)
    monkeypatch.setattr(elevate, "relaunch_as_admin", lambda: elevations.append(1) or True)
    monkeypatch.setattr(single_instance, "notify_running",
                        lambda **kw: knocks.append(kw) or True)
    assert main_mod.main() == 0
    assert knocks == [{"show": True}]
    assert elevations == [] and captured == {}


def test_a_login_launch_leaves_the_running_copy_hidden(monkeypatch):
    _stub_common(monkeypatch, ["sushtun", "--autostart"])
    knocks = []
    monkeypatch.setattr(single_instance, "notify_running",
                        lambda **kw: knocks.append(kw) or True)
    assert main_mod.main() == 0
    assert knocks == [{"show": False}]
