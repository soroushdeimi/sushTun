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
  Elevated writes go through `core.userfs.write_private_as_user`, which
  creates a 0600 temp file *before* any bytes are written and atomically
  replaces the destination as the invoking user.

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
  invoking user so the kernel's own permission checks apply. The elevated
  private writer creates its temp file at 0600 before writing any bytes,
  so the secret is never exposed at a wider mode, and it atomically
  replaces the destination as that user.

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

### P-256 key generation without new dependencies — verified status

Xray's own WARP client (`transport/internet/masque/warp.go` at
v26.10.31) parses the private key with
`x509.ParsePKCS8PrivateKey` and requires an `*ecdsa.PrivateKey`; the
public key is a SPKI blob compared byte-for-byte against the endpoint
leaf's `RawSubjectPublicKeyInfo`. So the on-wire shape is a P-256
ECDSA key in PKCS8 (private) / SPKI (public) form.

**`xray tls cert --json` (installed binary, v26.10.31) is a verified
P-256 key-generation path.** Reproduced by running it and decoding the
output with the installed `openssl`:

- The emitted private key PEM is labeled `-----BEGIN RSA PRIVATE KEY-----`,
  but that label is **wrong**: the decoded DER is a PKCS8
  `PrivateKeyInfo` whose algorithm is `id-ecPublicKey` + `prime256v1`
  (P-256). The label does not describe the contents.
- The certificate's `subjectPublicKeyInfo` (extracted from the DER with
  `openssl asn1parse`) is `id-ecPublicKey` + `prime256v1`, and its
  public key point is byte-for-byte identical to the public point inside
  the private key.
- A dummy WARP config built from such a keypair (PKCS8 private key,
  base64 SPKI public key, two host-prefix addresses) passes
  `xray run -test` with `Configuration OK.`

**Endpoint public key:** the `publicKey` field is the *server* (endpoint)
leaf certificate's SPKI, not the device's own public key. A locally
generated keypair is therefore only a placeholder until the real
endpoint's SPKI is known.

**Conclusion:** key generation exists via the installed Xray binary
(`xray tls cert --json`, PKCS8 P-256 despite the RSA PEM label). Actual
enrollment against Cloudflare is still **NOT implemented and NOT
verified** — no registrar, no placeholder button, no fake endpoint.
