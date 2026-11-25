# MASQUE chain — local runtime validation

Evidence from `tools/masque_runtime_probe.py` (opt-in manual diagnostic,
run as `python -m tools.masque_runtime_probe --xray /path/to/xray`) and
`tests/test_masque_runtime.py` (portable unit tests, no binary/openssl
required). Run against the pinned baseline Xray 26.10.31
(`/Users/soroushdeimi/Desktop/myprojects/SUSHTUN/sushTun/xray`,
`a4a3dff`, darwin/arm64).

## Loopback-only topology (no LAN, no TUN, no OS routes, no DNS)

Everything is bound to `127.0.0.1` in an isolated temp dir:

- a fixed-body HTTP target (the exact expected response body, so a proxy
  bypass cannot pass);
- local MASQUE TLS servers (h2 and h3);
- a local VLESS/TCP exit;
- a host-side SOCKS5 fixture with an EXACT allowlist mapping the logical
  documentation addresses onto loopback:
  `203.0.113.10:<target_port> -> 127.0.0.1:<target_port>` and
  `192.168.20.20:<vless_port> -> 127.0.0.1:<vless_port>`.
  Every other destination gets SOCKS5 reply code 4 (host unreachable).

The MASQUE server and the VLESS exit use that SOCKS fixture as their
outbound, so the tunnel's userspace stack never dials its own `127`
address. `192.168.20.20` is RFC1918 because Xray refuses a plaintext
VLESS outbound to a non-private address, and it sits outside the tunnel's
own subnet (`10.0.0.1/24`) so the stack forwards it. Certificates/keys
live in the private temp dir and are never HTTP-served. The fetch
environment is built explicitly with only the proxy set, so an inherited
`NO_PROXY` cannot turn a tunnel test into a direct hit.

## Reproduced outcomes (2026-11-25, exit code 0)

| Case | Outcome | Evidence |
|------|---------|----------|
| fixture rejects unknown target | PASS | SOCKS5 reply code 4 (host unreachable) |
| H2 standalone data plane | PASS | `HTTP 200 size=37B exact-body=True` |
| H2 wrong credentials | REJECTED (expected) | `HTTP 0 size=0B` |
| H2 wrong cert pin | REJECTED (expected) | `HTTP 0 size=0B` |
| H3 standalone data plane | PASS | `HTTP 200 size=37B exact-body=True` |
| chain MASQUE(H2) -> VLESS/TCP exit | PASS | `HTTP 200 size=37B exact-body=True` |
| stopping entry fails closed | PASS | `HTTP 0 size=0B` |

`size=37B` is the exact expected body
(`MASQUE-LOOPBACK-PROBE-BODY-0123456789`); the probe asserts byte-exact
equality, not just a non-empty body. The client Xray configs are built by
the REAL app code: `outbounds.build` for the standalone MASQUE profile and
`chains.resolve`/`apply` for the H2 chain; only the entry's `__IFACE__`
interface placeholder is stripped for the loopback fixture.

## Chain support (narrow, this round)

- MASQUE is accepted as the ENTRY (first hop) of a chain, carrier H2 only.
  H3 chains, MASQUE as middle/exit, and MASQUE mux/flow remain rejected in
  `chains.validate` until separately verified.
- `coreopts._masque_is_h2` reads `masque_http_version` (authoritative),
  not `alpn`, which may be empty or contradictory on imported profiles.
  H3 never gets TCP fragment/socket options; MASQUE is never mux-eligible.
- `connection.Connection.connect` runs full MASQUE profile validation
  BEFORE any interface/route/state/DNS mutation.

## Limits / NOT VERIFIED

- **Operator / Iran field behaviour**: NOT VERIFIED. All evidence is
  loopback-only with fake credentials; nothing here claims a real
  operator, ISP or WARP network works.
- **WARP enrollment / mTLS path**: NOT VERIFIED. Only generic basic-auth
  MASQUE was exercised; no live WARP enrollment (P-256 device key,
  `masqueSettings.warp`) was tested, per contract.
- **H3 chain**: H3 standalone works locally, but H3 as a chain carrier is
  deliberately rejected until separately proven.
- **Cross-platform**: only darwin/arm64 with the pinned binary. H3 uses
  QUIC datagrams; real-network MTU/UDP behaviour is NOT VERIFIED.
- The native probe is an opt-in manual diagnostic (needs the Xray binary
  and `openssl`); the default unit suite (`tests/test_masque_runtime.py`)
  is portable and needs neither.
