from xrayui.core import autostart


def test_desktop_file_text_escapes_exec_path_per_desktop_entry_spec(monkeypatch):
    monkeypatch.setattr(autostart, "_EXE", "/opt/path with spaces/%dir/sushtun\"")
    text = autostart._desktop_file_text()
    assert 'Exec="/opt/path with spaces/%%dir/sushtun\\"" --autostart\n' in text
