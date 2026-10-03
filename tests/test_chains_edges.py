from xrayui.core import chains, profiles


def test_chains_duplicates_and_deleted():
    p1 = profiles.Profile(uid="p1", protocol="vless", network="tcp", address="x", port=1, id="x")
    p2 = profiles.Profile(uid="p2", protocol="vless", network="tcp", address="y", port=2, id="y")
    c = chains.Chain(uid="c1", hops=["p1", "p1", "missing", "c1"])

    issues = chains.validate(c, [p1, p2])
    assert any("used twice" in i for i in issues)
    assert any("no longer exists" in i for i in issues)



def test_corrupt_chain_store_reads_as_empty(tmp_path, monkeypatch):
    # The window reads the store from its 2 s status timer; raising here
    # would turn one bad file into an exception on every tick.
    monkeypatch.setattr(chains.paths, "base_dir", lambda: tmp_path)
    store = chains.ChainStore()
    store.file.write_text("{not a list", encoding="utf-8")
    assert store.list() == []
    assert store.get("c1") is None
