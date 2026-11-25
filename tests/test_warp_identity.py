"""WARP identity: bounded JSON parsing, profile fields, safe private file I/O.

All identities use syntactic dummy key data (valid base64/PEM shape, not
real P-256 keys); no real credentials, no network, no real user profiles.
"""
from __future__ import annotations

import base64
import json
import os
import stat

import pytest

from xrayui.core.warp_identity import (
    WarpIdentity,
    load_identity,
    parse_identity,
    profile_fields,
    save_identity,
)

V4 = "172.16.0.2/32"
V6 = "2606:4700:110:8949:fed8:2642:a640:c8e1/128"


def _dummy_keys() -> tuple[str, str]:
    # Dummy P-256 key material as valid base64; syntax only, never used live.
    priv = base64.b64encode(b"\x01" * 48).decode()
    pub = base64.b64encode(b"\x02" * 48).decode()
    return priv, pub


def _identity(priv: str | None = None, pub: str | None = None,
              addresses: tuple[str, ...] = (V4, V6)) -> WarpIdentity:
    if priv is None and pub is None:
        priv, pub = _dummy_keys()
    return WarpIdentity(private_key=priv, public_key=pub, addresses=addresses)


def _json_text(identity: WarpIdentity) -> str:
    return json.dumps({
        "privateKey": identity.private_key,
        "publicKey": identity.public_key,
        "address": list(identity.addresses),
    })


# --- parse_identity ---------------------------------------------------------

def test_parse_flat_json_round_trips():
    ident = _identity()
    parsed = parse_identity(_json_text(ident))
    assert parsed == ident
    assert parsed.addresses == (V4, V6)


def test_parse_accepts_nested_warp_object():
    ident = _identity()
    text = json.dumps({"warp": {
        "privateKey": ident.private_key,
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    }})
    assert parse_identity(text) == ident


def test_parse_accepts_pem_style_keys():
    priv = "-----BEGIN PRIVATE KEY-----\n" + "A" * 64 + "\n-----END PRIVATE KEY-----"
    pub = "-----BEGIN PUBLIC KEY-----\n" + "B" * 64 + "\n-----END PUBLIC KEY-----"
    ident = _identity(priv=priv, pub=pub)
    assert parse_identity(_json_text(ident)) == ident


def test_parse_rejects_malformed_json():
    with pytest.raises(ValueError):
        parse_identity('{"privateKey": ')


def test_parse_rejects_non_object_root():
    with pytest.raises(ValueError):
        parse_identity("[1, 2, 3]")


def test_parse_rejects_missing_fields():
    text = json.dumps({"privateKey": "AAAA", "publicKey": "BBBB"})
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_incomplete_nested_warp():
    text = json.dumps({"warp": {"privateKey": "AAAA"}})
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_wrong_types():
    ident = _identity()
    bad = {
        "privateKey": [ident.private_key],
        "publicKey": 42,
        "address": "172.16.0.2/32",
    }
    with pytest.raises(ValueError):
        parse_identity(json.dumps(bad))


def test_parse_rejects_empty_key_strings():
    ident = _identity()
    text = json.dumps({
        "privateKey": "",
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_key_with_junk_characters():
    ident = _identity()
    text = json.dumps({
        "privateKey": "AAAA\x00BBBB",
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_invalid_base64_padding():
    ident = _identity()
    text = json.dumps({
        "privateKey": "AAAA=",  # bad padding
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_pem_with_mismatched_labels():
    ident = _identity()
    bad = "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PUBLIC KEY-----"
    text = json.dumps({
        "privateKey": bad,
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_pem_with_non_base64_body():
    ident = _identity()
    bad = "-----BEGIN PRIVATE KEY-----\n!!!not-base64!!!\n-----END PRIVATE KEY-----"
    text = json.dumps({
        "privateKey": bad,
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_oversized_input():
    ident = _identity()
    text = json.dumps({
        "privateKey": ident.private_key,
        "publicKey": ident.public_key,
        "address": [V4],
        "pad": "x" * (2 * 1024 * 1024),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_non_host_prefix():
    ident = _identity()
    text = json.dumps({
        "privateKey": ident.private_key,
        "publicKey": ident.public_key,
        "address": ["172.16.0.0/24"],
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_bare_address_without_prefix():
    ident = _identity()
    text = json.dumps({
        "privateKey": ident.private_key,
        "publicKey": ident.public_key,
        "address": ["172.16.0.2"],
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_duplicate_addresses():
    ident = _identity()
    text = json.dumps({
        "privateKey": ident.private_key,
        "publicKey": ident.public_key,
        "address": [V4, V4],
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_excess_addresses():
    ident = _identity()
    addrs = [f"10.0.{i // 256}.{i % 256}/32" for i in range(9)]
    text = json.dumps({
        "privateKey": ident.private_key,
        "publicKey": ident.public_key,
        "address": addrs,
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_empty_address_list():
    ident = _identity()
    text = json.dumps({
        "privateKey": ident.private_key,
        "publicKey": ident.public_key,
        "address": [],
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_whitespace_only_key():
    ident = _identity()
    text = json.dumps({
        "privateKey": "   \n\t  ",
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_pem_with_empty_body():
    ident = _identity()
    bad = "-----BEGIN PRIVATE KEY-----\n\n-----END PRIVATE KEY-----"
    text = json.dumps({
        "privateKey": bad,
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_pem_with_whitespace_only_body():
    ident = _identity()
    bad = "-----BEGIN PRIVATE KEY-----\n   \n  \n-----END PRIVATE KEY-----"
    text = json.dumps({
        "privateKey": bad,
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_pem_with_padding_only_body():
    # "====" is base64 padding that decodes to zero bytes.
    ident = _identity()
    bad = "-----BEGIN PRIVATE KEY-----\n====\n-----END PRIVATE KEY-----"
    text = json.dumps({
        "privateKey": bad,
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_pem_with_wrong_label_for_role():
    ident = _identity()
    text = json.dumps({
        "privateKey": "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----",
        "publicKey": "-----BEGIN PRIVATE KEY-----\nBBBB\n-----END PRIVATE KEY-----",
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_accepts_ec_private_key_pem_label():
    ident = _identity()
    priv = "-----BEGIN EC PRIVATE KEY-----\n" + "A" * 64 + "\n-----END EC PRIVATE KEY-----"
    text = json.dumps({
        "privateKey": priv,
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    assert parse_identity(text) == _identity(priv=priv, pub=ident.public_key)


def test_parse_rejects_oversized_key_input():
    ident = _identity()
    text = json.dumps({
        "privateKey": "A" * (2 * 1024 * 1024),
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError):
        parse_identity(text)


def test_parse_rejects_non_ascii_key_without_leaking_it():
    ident = _identity()
    secret = "AAAAéBBBB"
    text = json.dumps({
        "privateKey": secret,
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    })
    with pytest.raises(ValueError) as exc:
        parse_identity(text)
    assert secret not in str(exc.value)


def test_parse_error_does_not_reflect_secret():
    secret = "SUPERSECRETKEY"
    text = json.dumps({
        "privateKey": secret,
        "publicKey": "BBBB",
        "address": "not-a-list",
    })
    with pytest.raises(ValueError) as exc:
        parse_identity(text)
    assert secret not in str(exc.value)


# --- profile_fields ---------------------------------------------------------

def test_profile_fields_maps_exactly_the_three_masque_fields():
    ident = _identity()
    fields = profile_fields(ident)
    assert fields == {
        "masque_private_key": ident.private_key,
        "masque_public_key": ident.public_key,
        "masque_addresses": ", ".join(ident.addresses),
    }


# --- repr / secret hygiene --------------------------------------------------

def test_repr_never_shows_key_material():
    ident = _identity()
    r = repr(ident)
    assert ident.private_key not in r
    assert ident.public_key not in r
    assert "WarpIdentity" in r


# --- load / save ------------------------------------------------------------

def test_save_then_load_round_trips(tmp_path):
    ident = _identity()
    target = tmp_path / "identity.json"
    save_identity(target, ident)
    assert load_identity(target) == ident


def test_saved_file_round_trips_and_is_mode_0600_on_posix(tmp_path):
    ident = _identity()
    target = tmp_path / "identity.json"
    save_identity(target, ident)
    assert load_identity(target) == ident
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o600


def test_saved_content_is_bounded_json(tmp_path):
    ident = _identity()
    target = tmp_path / "identity.json"
    save_identity(target, ident)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {
        "privateKey": ident.private_key,
        "publicKey": ident.public_key,
        "address": list(ident.addresses),
    }


def test_load_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_identity(tmp_path / "nope.json")


def test_load_rejects_symlink_target(tmp_path):
    real = tmp_path / "real.json"
    ident = _identity()
    save_identity(real, ident)
    link = tmp_path / "link.json"
    os.symlink(real, link)
    with pytest.raises(OSError):
        load_identity(link)


def test_load_rejects_symlink_parent(tmp_path):
    real_dir = tmp_path / "realdir"
    real_dir.mkdir()
    ident = _identity()
    save_identity(real_dir / "identity.json", ident)
    link_dir = tmp_path / "linkdir"
    os.symlink(real_dir, link_dir)
    with pytest.raises(OSError):
        load_identity(link_dir / "identity.json")


def test_save_rejects_symlink_target(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    os.symlink(real, link)
    with pytest.raises(OSError):
        save_identity(link, _identity())
    # The symlink target must be untouched.
    assert real.read_text(encoding="utf-8") == "{}"


def test_save_rejects_symlink_parent(tmp_path):
    real_dir = tmp_path / "realdir"
    real_dir.mkdir()
    (real_dir / "victim.json").write_text("{}", encoding="utf-8")
    link_dir = tmp_path / "linkdir"
    os.symlink(real_dir, link_dir)
    with pytest.raises(OSError):
        save_identity(link_dir / "victim.json", _identity())
    assert (real_dir / "victim.json").read_text(encoding="utf-8") == "{}"


def test_save_partial_write_leaves_no_file_or_temp(tmp_path, monkeypatch):
    target = tmp_path / "identity.json"

    def flaky(fd):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", flaky)
    with pytest.raises(OSError):
        save_identity(target, _identity())
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_save_overwrites_existing_regular_file(tmp_path):
    target = tmp_path / "identity.json"
    target.write_text("old", encoding="utf-8")
    ident = _identity()
    save_identity(target, ident)
    assert load_identity(target) == ident


def test_save_elevated_delegates_to_private_writer(tmp_path, monkeypatch):
    from xrayui.core import userfs

    calls = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(userfs, "invoking_user_ids", lambda: (1234, 5678))
    monkeypatch.setattr(userfs, "write_private_as_user",
                        lambda path, data, uid, gid: calls.append(
                            (path, data, uid, gid)))
    ident = _identity()
    target = tmp_path / "identity.json"
    save_identity(target, ident)
    assert len(calls) == 1
    path, data, uid, gid = calls[0]
    assert path == target
    assert (uid, gid) == (1234, 5678)
    assert json.loads(data.decode("utf-8"))["privateKey"] == ident.private_key
