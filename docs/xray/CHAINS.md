# Ordered chains: core compatibility

The core stores named, ordered profile references in `chains.json` under the
application data directory. This phase does not expose chain selection or an
editor in the UI. `ChainStore` provides list/get/save/delete; `validate` returns
translated problems, and `resolve` captures an immutable profile snapshot.
`Connection.connect` accepts a `Chain`, a `ResolvedChain`, or the existing
single `Profile`. Rendering accepts a `ResolvedChain` in place of a profile.

A chain contains two to eight distinct profiles. Rendering reuses the existing
protocol builders. The last hop keeps `proxy`; preceding hops are `chain-1`,
`chain-2`, and so on. Tag collisions fail validation at render time. Only the
entry hop binds the physical interface. Independent multi-exits remain
independent even when their profile also appears in a chain.

The entry owns the host route, DNS hosts pin, and persisted recovery address.
Its pinned hostname uses `ForceIPv4` so Xray reads its own hosts map; subsequent
hops retain `AsIs` and pass hostnames to the preceding proxy. The entry pin also
applies with raw DNS overrides. Single-profile rendering remains unchanged.
`State.chain_uid` identifies the connected chain; `State.profile_uid` identifies
its exit. Backups preserve chain references, including missing-profile errors.

## Compatibility gate

Verified with bundled Xray 26.3.27, commit `d2758a0`, on Linux using only local
listeners. Windows and macOS lifecycle coverage mocks network operations.

| Combination | Status |
| --- | --- |
| VLESS without flow, VMess, Trojan, Shadowsocks over TCP | Three-hop HTTP runtime proof |
| VLESS over gRPC and HTTPUpgrade | Three-hop HTTP runtime proof |
| TCP, gRPC, HTTPUpgrade hostname endpoints | Entry pin and remote next-hop resolution runtime proof |
| Shadowsocks UDP | Three-hop request and reply runtime proof |
| Other supported protocol/transport pairs | Shared dial path verified from source; no exhaustive runtime matrix |
| TLS/REALITY settings | Preserved by existing builders; no remote TLS/REALITY runtime proof |
| WebSocket | Rejected: a loopback three-hop VLESS probe intermittently lost the response when the HTTP target closed immediately |
| XHTTP, including separate download settings | Rejected until both dial paths are verified |
| Vision/other flows, enabled mux/XUDP | Rejected pending dedicated runtime proof |
| Hysteria2, WireGuard, other transports/protocols | Rejected pending verification |

The runtime tests cover both two and three hops, each server's expected next
connection in its access log, failure with the middle server stopped, and
immediate-close responses on supported transports. They skip only when the
bundled executable is absent and always stop their own processes. No test
installs routes, opens a TUN, or changes system DNS.

## Matching source evidence

All references below are from tag `v26.3.27`:

- `transport/internet/dialer.go:111-139`: redirection dispatches the target
  through the selected outbound using pipes, with separate TCP/UDP readers.
- `transport/internet/dialer.go:252-282`: domain resolution depends on socket
  domain strategy; `dialerProxy` redirects before a system dial, and a missing
  handler returns an error instead of falling back directly.
- `transport/internet/tcp/dialer.go:22` and
  `transport/internet/httpupgrade/dialer.go:49`: these transports pass stream
  socket settings into `DialSystem`.
- `transport/internet/grpc/dial.go:86-127,181-190`: gRPC retains the stream
  socket settings and uses a passthrough resolver before `DialSystem`.
- `transport/internet/splithttp/dialer.go:403-438`: XHTTP constructs a separate
  download stream whose socket settings need independent treatment.
- `proxy/vless/outbound/outbound.go:251-295`: Vision inspects underlying
  connection types and has special flow handling.
- `app/proxyman/outbound/handler.go:210-242`: mux and XUDP use separate dispatch
  clients; the supported plain TCP/UDP path calls the protocol directly.

WebSocket support can be revisited with a reproducer and a matching-core fix;
a successful keep-alive request alone does not resolve the close-response loss.
