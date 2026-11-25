"""WARP identity for MASQUE: parse, profile mapping, safe private file I/O.

An identity is the device keypair plus the tunnel addresses Cloudflare
assigned to it. Keys are accepted as PEM or base64 *syntax* only: this
module never claims cryptographic validity from a prefix, and it never
enrolls. The private key is secret material: it must not appear in
reprs, exceptions or logs.

File-safety guarantees (POSIX):
- load_identity opens the final component with O_NOFOLLOW, so a symlink
  at the target is refused atomically (no TOCTOU on the last path step).
- save_identity writes a temp file in the same directory and os.replace()s
  it into place; rename(2) replaces a symlink at the target rather than
  following it, so the final step never writes through a link.
- A symlinked *parent* directory is only caught by a best-effort pre-check
  (is_symlink), which is NOT race-free. When the app runs elevated, writes
  are delegated to core.userfs, which drops to the invoking user so the
  kernel's own permission checks apply.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import tempfile
from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path

# Bounded input: a real identity JSON is a few hundred bytes; anything
# larger is not an identity and must not be parsed.
MAX_INPUT_BYTES = 1024 * 1024

# At most one IPv4 and one IPv6 host prefix (a /32 or /128 each).
MAX_ADDRESSES = 2

# PEM block with matching BEGIN/END labels and a base64 body.
_PEM_RE = re.compile(
    r"^-----BEGIN ([A-Z0-9 ]+)-----\n(.*?)\n-----END \1-----$", re.S)


class WarpIdentityError(ValueError):
    """Malformed or incomplete identity data. Never carries key material."""


@dataclass(frozen=True)
class WarpIdentity:
    private_key: str
    public_key: str
    addresses: tuple[str, ...]

    def __repr__(self) -> str:  # never leak key material
        return f"WarpIdentity(addresses={self.addresses!r})"


def _check_key(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise WarpIdentityError(f"{field} must be a non-empty string")
    v = value.strip()
    if v.startswith("-----BEGIN "):
        m = _PEM_RE.match(v)
        if not m:
            raise WarpIdentityError(f"{field} is not a well-formed PEM block")
        body = re.sub(r"\s+", "", m.group(2))
        try:
            base64.b64decode(body, validate=True)
        except binascii.Error:
            raise WarpIdentityError(f"{field} PEM body is not base64") from None
        return value
    try:
        base64.b64decode(v, validate=True)
    except binascii.Error:
        raise WarpIdentityError(f"{field} is not valid base64") from None
    return value


def _check_addresses(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise WarpIdentityError("address must be a non-empty list")
    if len(value) > MAX_ADDRESSES:
        raise WarpIdentityError("address has too many entries")
    seen: set[str] = set()
    have_v4 = have_v6 = False
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise WarpIdentityError("address entries must be strings")
        if "/" not in entry:
            raise WarpIdentityError("address needs a /32 or /128 prefix")
        try:
            net = IPv4Network(entry) if ":" not in entry else IPv6Network(entry)
        except ValueError:
            raise WarpIdentityError("address is not a valid host prefix") from None
        if net.prefixlen not in (32, 128):
            raise WarpIdentityError("address must be a /32 or /128 host prefix")
        if isinstance(net, IPv4Network):
            if have_v4:
                raise WarpIdentityError("at most one IPv4 address")
            have_v4 = True
        else:
            if have_v6:
                raise WarpIdentityError("at most one IPv6 address")
            have_v6 = True
        if entry in seen:
            raise WarpIdentityError("duplicate address")
        seen.add(entry)
        out.append(entry)
    return tuple(out)


def _object_fields(obj: dict, field: str) -> tuple[str, str, object]:
    for key in ("privateKey", "publicKey", "address"):
        if key not in obj:
            raise WarpIdentityError(f"{field} is missing {key!r}")
    return _check_key(obj["privateKey"], "privateKey"), \
        _check_key(obj["publicKey"], "publicKey"), obj["address"]


def parse_identity(text: str) -> WarpIdentity:
    """Parse bounded identity JSON into a WarpIdentity.

    Accepts {"privateKey","publicKey","address":[...]} or {"warp":{...}}.
    Raises WarpIdentityError (a ValueError) without echoing key material.
    """
    if not isinstance(text, str):
        raise WarpIdentityError("identity must be a string")
    if len(text.encode("utf-8", "replace")) > MAX_INPUT_BYTES:
        raise WarpIdentityError("identity input is too large")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as e:
        raise WarpIdentityError("identity is not valid JSON") from e
    if not isinstance(data, dict):
        raise WarpIdentityError("identity must be a JSON object")
    if "warp" in data:
        if not isinstance(data["warp"], dict):
            raise WarpIdentityError("warp must be a JSON object")
        obj = data["warp"]
    else:
        obj = data
    priv, pub, addrs = _object_fields(obj, "identity")
    return WarpIdentity(priv, pub, _check_addresses(addrs))


def profile_fields(identity: WarpIdentity) -> dict[str, str]:
    """Map an identity onto exactly the three masque_* profile fields."""
    return {
        "masque_private_key": identity.private_key,
        "masque_public_key": identity.public_key,
        "masque_addresses": ", ".join(identity.addresses),
    }


def _identity_bytes(identity: WarpIdentity) -> bytes:
    return json.dumps({
        "privateKey": identity.private_key,
        "publicKey": identity.public_key,
        "address": list(identity.addresses),
    }, indent=2).encode("utf-8")


def _refuse_symlink(path: Path) -> None:
    # Best-effort: a symlink at the target or any parent is refused. This is
    # not race-free for parents; the final component is additionally guarded
    # by O_NOFOLLOW / rename(2) below.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise OSError(f"refusing to follow a symlink at {part}")


def _write_private(path: Path, data: bytes) -> None:
    _refuse_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".identity.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)  # rename(2): replaces a symlink, never follows it
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def save_identity(path: Path, identity: WarpIdentity) -> None:
    """Atomically write an identity as a 0600 private file, no symlinks.

    When running elevated, delegate to core.userfs so the write happens as
    the invoking user (kernel-enforced), not as root.
    """
    path = Path(path)
    data = _identity_bytes(identity)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        from . import userfs
        ids = userfs.invoking_user_ids()
        if ids is not None:
            userfs.write_as_user(path, data, *ids, mode=0o600)
            return
    _write_private(path, data)


def load_identity(path: Path) -> WarpIdentity:
    """Read and parse an identity file, refusing symlinks at every level."""
    path = Path(path)
    _refuse_symlink(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)  # O_NOFOLLOW: atomic refusal of a symlink target
    try:
        data = b""
        while len(data) <= MAX_INPUT_BYTES:
            chunk = os.read(fd, MAX_INPUT_BYTES + 1 - len(data))
            if not chunk:
                break
            data += chunk
    finally:
        os.close(fd)
    if len(data) > MAX_INPUT_BYTES:
        raise WarpIdentityError("identity file is too large")
    return parse_identity(data.decode("utf-8"))
