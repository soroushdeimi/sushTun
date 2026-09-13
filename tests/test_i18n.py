"""i18n.tr(): language switching, fallback, and formatting never raise."""
from __future__ import annotations

from xrayui import i18n


def teardown_function(_fn):
    i18n.set_language("en")


def test_set_language_only_accepts_en_or_fa():
    i18n.set_language("fa")
    assert i18n.current() == "fa"
    i18n.set_language("xx")
    assert i18n.current() == "en"
    i18n.set_language("fa")
    i18n.set_language("")
    assert i18n.current() == "en"


def test_tr_returns_english_by_default():
    assert i18n.tr("Connect") == "Connect"


def test_tr_returns_the_persian_translation_when_present(monkeypatch):
    monkeypatch.setitem(i18n.TRANSLATIONS_FA, "Connect", "اتصال")
    i18n.set_language("fa")
    assert i18n.tr("Connect") == "اتصال"


def test_tr_falls_back_to_english_for_a_missing_key(monkeypatch):
    monkeypatch.delitem(i18n.TRANSLATIONS_FA, "Some unmapped string", raising=False)
    i18n.set_language("fa")
    assert i18n.tr("Some unmapped string") == "Some unmapped string"


def test_tr_formats_params_in_english():
    assert i18n.tr("Updated {n}h ago", n=3) == "Updated 3h ago"


def test_tr_formats_params_in_the_persian_translation(monkeypatch):
    monkeypatch.setitem(i18n.TRANSLATIONS_FA, "Updated {n}h ago", "به‌روزرسانی {n} ساعت پیش")
    i18n.set_language("fa")
    assert i18n.tr("Updated {n}h ago", n=3) == "به‌روزرسانی 3 ساعت پیش"


def test_tr_never_raises_on_a_translation_with_a_bad_placeholder(monkeypatch):
    monkeypatch.setitem(i18n.TRANSLATIONS_FA, "Updated {n}h ago", "نگاشت اشتباه {oops}")
    i18n.set_language("fa")
    # The Persian entry references a placeholder the caller never passed --
    # falls back to the English source formatted correctly, never raises.
    assert i18n.tr("Updated {n}h ago", n=3) == "Updated 3h ago"


def test_tr_never_raises_when_params_are_missing_entirely(monkeypatch):
    monkeypatch.setitem(i18n.TRANSLATIONS_FA, "Updated {n}h ago", "به‌روزرسانی {n} ساعت پیش")
    i18n.set_language("fa")
    # Called with no params at all even though the template has a
    # placeholder -- no .format() call happens, so nothing to raise on.
    assert i18n.tr("Updated {n}h ago") == "به‌روزرسانی {n} ساعت پیش"
