# MASQUE chain — local runtime validation

Evidence from `tools/masque_runtime_probe.py` and `tests/test_masque_runtime.py`,
run against the pinned baseline Xray 26.10.31
(`/Users/soroushdeimi/Desktop/myprojects/SUSHTUN/sushTun/xray`,
`a4a3dff`, darwin/arm64). All runs are isolated in a temp dir: a local MASQUE
TLS server, a local VLESS/TCP exit, and an HTTP target. No TUN, no OS routes,
no DNS changes. Ephemeral certs are generated with the locally installed
`openssl` (test-only, not a runtime dependency).

## Reproduced outcomes (distinct config / handshake / data-plane)

| Case | Outcome | Evidence |
|------|---------|----------|
| H2 standalone data plane | PASS | `HTTP 200 size=499B`; client log `proxy/masque: MASQUE: tunnel established from [10.0.0.2]`; server log `processing from tcp:10.0.0.2:… to tcp:<local-ip>:<port>` |
| H2 wrong credentials | REJECTED (expected) | client log `connect-ip: server responded with 401`; server log `proxy/masque: invalid credentials` / `authentication failed for u1` |
| H3 standalone data plane | PASS | `HTTP 200 size=847B`; server `listening UDP for MASQUE over HTTP/3` |
| chain MASQUE(H2) -> VLESS/TCP exit | PASS | `HTTP 200 size=1071B`; client `proxy/vless/outbound: tunneling request … via <local-ip>:<port>` then `MASQUE: tunnel established from [10.0.0.3]`; exit log `proxy/vless/inbound: received request` |

TLS-only is not treated as data-plane success: the test asserts a non-empty
HTTP body, not just a completed handshake.

## Root cause of the previous "HTTP response timed out"

The tunnel establishes and the server assigns an address, but the data path
fails with `proxy/masque: failed to create TCP connection > proxy/tun:
connection timed out`, and the server never logs a forward. Two distinct
causes were found and fixed in the probe:

1. **Loopback target.** The MASQUE outbound runs a user-space network stack
   that cannot reach `127.0.0.1`. A target bound to loopback is never reached
   (server sees no forward). Binding the target to a real interface address
   (e.g. `10.42.0.107`) makes the data plane work.
2. **`NO_PROXY` in the environment.** `NO_PROXY=127.0.0.1,localhost` made
   `curl` bypass the SOCKS proxy entirely, silently turning a tunnel test into
   a direct hit (a dead proxy port still returned `HTTP 200`). The probe
   strips `NO_PROXY`/`no_proxy` from the fetch environment.

## Chain wiring notes (for the narrow chain extension)

- The VLESS/TCP exit is dialed from inside the tunnel, so it must be reachable
  at a non-loopback address (the tunnel stack cannot reach `127.0.0.1`).
- Xray's `freedom` outbound blackholes the local machine's own IP
  (`proxy/freedom: blocked target … blackholing connection`), so the chain's
  final hop to a local target must go through a plain socket proxy, not a
  second `freedom` outbound.
- A VLESS inbound requires `settings.decryption = "none"` (settings level, not
  per-client) or Xray refuses to start.

## coreopts / connection changes (this worker)

- `coreopts.mux_eligible`: MASQUE is never mux-eligible (the MASQUE outbound
  does not support Mux).
- `coreopts.fragment_eligible` / `sockopt_eligible`: MASQUE h2 (TCP+TLS) is
  eligible; MASQUE h3 (QUIC) is not. The single carrier is the profile `alpn`
  (default h2).
- `connection.Connection.connect`: MASQUE is exempt from the VLESS-style `id`
  requirement (it authenticates with basic auth or a WARP identity).

## NOT VERIFIED

- **Chain acceptance in `chains.validate`/`SUPPORTED_PROTOCOLS`.** MASQUE is
  not yet in `SUPPORTED_PROTOCOLS`, so a MASQUE chain hop is still rejected
  ("not verified for chains"). Enabling it requires Worker 1's model/builder
  (the `masque` outbound builder and profile fields) to land first; I did not
  edit those owned paths.
- **WARP identity path.** Only generic basic-auth MASQUE was exercised locally.
  The WARP mTLS path (P-256 device key, `masqueSettings.warp`) was not tested
  (no live WARP enrollment, per contract).
- **Cross-platform / operator.** Only darwin/arm64 with the pinned binary.
  H3 uses QUIC datagrams; real-network MTU/UDP behaviour is NOT VERIFIED.
  Iranian-operator field behaviour is NOT VERIFIED.
- **`connection.connect` full MASQUE connect path.** Only the id-exemption
  check was unit-tested (OS interactions mocked). A full MASQUE connect
  through `render`/`chains.build` is NOT VERIFIED until the MASQUE outbound
  builder exists.
