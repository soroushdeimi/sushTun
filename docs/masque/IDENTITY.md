# MASQUE / WARP identity

What this module implements, and what it does not.

## Implemented: importing an existing WARP identity

`xrayui/core/warp_identity.py` provides a small, stdlib-only API to
*import* a WARP identity the user already has:

- `WarpIdentity(private_key, public_key, addresses)` — frozen dataclass.
- `parse_identity(text)` — parses bounded JSON
  `{"privateKey","publicKey","address":[...]}` or `{"warp":{...}}`.
- `profile_fields(identity)` — maps to exactly the three `masque_*`
  profile fields (`masque_private_key`, `masque_public_key`,
  `masque_addresses`).
- `load_identity(path)` / `save_identity(path, identity)` — safe private
  file I/O (0600 on POSIX, no symlink following, atomic replace).

### What "accepts PEM/base64" means here

Keys are checked for **syntax only**: a base64 body, or a PEM block with
matching `BEGIN`/`END` labels and a base64 body. This module does **not**
parse the key, does not check the curve, and does **not** claim any
cryptographic validity from a prefix. A string that looks like a key is
stored as-is; whether Xray can actually use it is decided by Xray at
runtime, not by this module.

### File-safety guarantees (POSIX)

- `load_identity` opens the final path component with `O_NOFOLLOW`, so a
  symlink at the target is refused atomically (no TOCTOU on the last step).
- `save_identity` writes a temp file in the same directory and
  `os.replace()`s it into place; `rename(2)` replaces a symlink at the
  target rather than following it.
- A symlinked *parent* directory is only caught by a best-effort
  `is_symlink()` pre-check, which is **not** race-free. When the app runs
  elevated, writes are delegated to `core.userfs`, which drops to the
  invoking user so the kernel's own permission checks apply.

## Not implemented: registration / key generation

This module does **not** enroll a device with Cloudflare and does **not**
generate a WARP keypair. There is no registrar, no placeholder button, and
no fake endpoint.

### Why registration is not implemented

A real WARP identity comes from Cloudflare's enrollment flow (the
`wgcf register` / `warp-reg` path documented at
<https://xtls.github.io/document/level-2/warp.html>), which returns a
device keypair **plus** the assigned tunnel addresses and reserved bytes.
That is a live network protocol against Cloudflare, not something this
module can or should fake.

### P-256 key generation without new dependencies — research status

Xray's own WARP client (`transport/internet/masque/warp.go` at
v26.10.31) parses the private key with
`x509.ParsePKCS8PrivateKey` and requires an `*ecdsa.PrivateKey`; the
public key is a SPKI blob compared byte-for-byte against the endpoint
leaf's `RawSubjectPublicKeyInfo`. So the on-wire shape is a P-256
ECDSA key in PKCS8 (private) / SPKI (public) form.

Investigated options for producing such a key with **no new runtime
dependency**:

- **Python stdlib**: no EC/P-256 key-generation API. `ssl`, `hashlib` and
  `hmac` expose no `ecdsa` keygen; the third-party `ecdsa` and
  `cryptography` packages are not installed. NOT a viable path.
- **`xray tls cert --json`** (installed binary, v26.10.31): generates a
  TLS certificate and key. **Verified by running it**: the certificate is
  EC, but the emitted private key is `-----BEGIN RSA PRIVATE KEY-----`
  (PKCS1 RSA), which does **not** match the EC certificate and is not the
  PKCS8 P-256 form `warp.go` requires. So this is **NOT** a verified
  P-256 generation path. (The manager's note that `main/commands/all/tls/
  cert.go` calls `cert.Generate` / `ecdsa.GenerateKey(elliptic.P256())`
  was not confirmed against the installed binary's actual output; the
  observed output is RSA. Recorded as NOT VERIFIED for P-256.)

**Conclusion:** no dependency-free P-256 generation path is verified.
Registration therefore stays research-only. A future implementation would
need either a verified P-256 keygen source (e.g. a confirmed Xray
subcommand that emits PKCS8 P-256) or an explicit, user-approved new
dependency — and the full Cloudflare enrollment protocol, which has not
been reproduced here.
