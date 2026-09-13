from xrayui.core import profiles as profiles_mod
from xrayui.core.profiles import Profile, ProfileStore


def _store(tmp_path, monkeypatch) -> ProfileStore:
    monkeypatch.setattr(profiles_mod.paths, "base_dir", lambda: tmp_path)
    return ProfileStore()


def test_list_skips_the_subscriptions_file(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    kept = store.save(Profile(name="a", address="x", port=1, id="y"))
    (store.dir / profiles_mod.SUBSCRIPTIONS_FILENAME).write_text(
        '[{"url": "https://sub.example/x"}]', encoding="utf-8"
    )

    got = store.list()

    assert [p.uid for p in got] == [kept.uid]


def test_list_skips_a_json_file_that_is_not_an_object(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    kept = store.save(Profile(name="a", address="x", port=1, id="y"))
    (store.dir / "not-a-profile.json").write_text("[1, 2, 3]", encoding="utf-8")

    got = store.list()

    assert [p.uid for p in got] == [kept.uid]
