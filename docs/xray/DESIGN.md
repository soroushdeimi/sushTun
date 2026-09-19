# sushTun as a complete front end for Xray-core: architecture and UX

Status: **proposal**. No feature code is written in this step. Every claim cites
a file; anything not checked against code or a real run is marked
**UNVERIFIED**.

Companion files, all in `docs/xray/`:

| file | what | kept by |
|---|---|---|
| `keys.json` | every JSON key the core accepts, with first/removed/rejected version | `scripts/xray_keys.py extract` |
| `classification.toml` | client / server / internal per key, with a reason for every exclusion | hand |
| `status.toml` | sushTun's support per client key, with files and link round-trip | hand |
| `COVERAGE.md` | the joined report with totals per section | `scripts/xray_keys.py report` |

`tests/test_xray_coverage.py` fails when a client-side key has no status, when
a `full`/`partial` status is claimed by wildcard, when `COVERAGE.md` is stale,
or when sushTun writes a key the bundled core does not know.

---

## 1. Where sushTun stands

Baseline: the bundled core, **Xray 26.3.27** (`/opt/sushtun/_internal/xray
version`), which is also the newest stable release (`gh release list -R
XTLS/Xray-core`: every later tag up to 26.9.9 is a pre-release).

Inventory (from `COVERAGE.md`, releases 26.3.27 → 26.9.9 plus `~/xray-core` at
`dcdfc57`):

- 1,678 keys across all versions; **1,149** accepted by 26.3.27.
- Of those: **564 client-side**, 514 server-only, 71 internal.
- Client-side keys sushTun can reach today: **240 (42%)**. Through a form or
  setting: **140 (24%)**. The rest are raw JSON only (42), aliases (58), or
  unsupported (324).
- 529 keys first appear after 26.3.27 and are **gated**: recorded, not
  implemented.

How the inventory is built (`scripts/xray_keys.py`): it reads the json struct
tags under `infra/conf` and follows each field into its struct. Fields decoded
at run time (`settings` by `protocol`, finalmask and balancer settings by
`type`, user lists) are listed in `SLOTS`. If a newer release adds a raw field
that `SLOTS` doesn't know, the script stops with an error instead of reading
it partially. That guard fired 5 times while going from 26.3.27 to `main`
(`Xdns.domain`, `CustomTransformArg.bytes`, inbound `users`, `proxySettings`,
`XDriveConfig.template`).

Two properties of the core shape everything below:

- **Unknown keys are ignored silently.** Go's `encoding/json` drops fields it
  doesn't know. A typo, or a key from another core version, does nothing and
  shows no error. `xray run -test` does **not** catch it. That's why the test
  compares what sushTun writes against `keys.json`.
- **Key names match case-insensitively.** 26.3.27 declares `MTU` for the TUN
  (`infra/conf/tun.go`), and sushTun's `mtu` works (`config.template.json`).

---

## 2. Findings

Found while building the inventory. None of these are fixed in this step.

| # | finding | evidence | severity |
|---|---|---|---|
| F1 | **A `h2`/`http` transport profile cannot connect.** 26.3.27 removed the HTTP transport and refuses to start. sushTun still writes `httpSettings`. This breaks the project rule "a bad setting must never stop the app from connecting". | `xrayui/core/outbounds/_common.py:71`; importer accepts it (`importer.py` `_stream_fields`); a real `xray run -test` prints *"The feature HTTP transport … has been removed and migrated to XHTTP"* | high |
| F2 | **A reconnect tears down a working tunnel before knowing whether the new config starts.** `_reconnect_now` calls `disconnect()` then `connect()`. `connect` renders, pins the route, then starts Xray, and nothing tests the config first. | `xrayui/ui/main_window.py:1134-1145`, `xrayui/core/connection.py:137-149`; `xraycheck.check_config` exists (`xrayui/core/xraycheck.py:83`) but only the settings and DNS pages call it | high |
| F3 | **Hysteria2 port hopping will silently stop working after a core upgrade.** sushTun writes `finalmask.quicParams.udpHop`, which is removed in 26.9.9 (replaced by a `udphop` finalmask). Unknown keys are ignored, so there is no error. | `xrayui/core/outbounds/hysteria2.py:81`; `keys.json` `removed: 26.9.9` | medium (on upgrade) |
| F4 | **The TUN inbound's `"dns"` does nothing on 26.3.27** and starts to matter after an upgrade (TUN gains `dns` later). | `config.template.json:20`; test `KNOWN_UNKNOWN` | low now, review on upgrade |
| F5 | Hysteria2 links' `ech` is parsed but never written. | `importer.py:328`; `hysteria2.py` writes no `echConfigList` | low |
| F6 | xhttp `extra` with a JSON typo is dropped silently, not refused in the form. | `_common.py:13` `_parse_extra` | low |
| F7 | `routing.rules[].type = "field"` is ignored (legacy); harmless. | `config.template.json:109,114` | none |
| F8 | `render.build` is called with `profile` and the interface positionally, against the project rule "keyword, never by position". | `connection.py:137`, `:232` | style |
| F9 | The legacy top-level `reverse` (bridge/portal) is **rejected from 26.4.25**. Remote access must use VLESS `reverse`, which 26.3.27 has. | `keys.json` `reverse.rejected_in` | design input |
| F10 | `allowInsecure` is rejected by 26.3.27 after 2026-06-01 (a date check inside the core). sushTun already never writes it. ✓ | 26.3.27 `infra/conf/transport_internet.go:709-716`; `_common.py` comment | none |

**Why probing with `xray -test` misleads:** freedom `finalRules` "passed" such
a probe on 26.3.27, but it first appears in **26.5.3**. The probe printed "OK"
only because unknown keys are ignored. Checked against `keys.json` instead, these
do exist in 26.3.27 (noises, fragment for direct traffic, balancers + observatory,
DNS `expectIPs`/`unexpectedIPs`/`finalQuery`, webhook, happyEyeballs, MPTCP,
ECH, `mldsa65Verify`, `dialerProxy`, VLESS reverse, UDP noise mask, sudoku). xdns
exists in 26.3.27 with `domain` (renamed `domains` in 26.4.13). xicmp is only a
server-side (inbound) mask in the inventory.

---

## 3. One definition per setting

### 3.1 The model

A new Qt-free package, so the "no Qt in core/" rule holds:

```
xrayui/core/xspec/
  model.py      Setting, LinkField, Risk, Tier, Issue            (dataclasses)
  engine.py     validate(), apply(), to_link(), from_link(), status_keys()
  corever.py    bundled core version + comparisons
  catalog/      one module per section: tls.py, reality.py, sockopt.py,
                xhttp.py, grpc.py, dns.py, direct.py, routing.py,
                observatory.py, policy.py, inbound.py
xrayui/ui/spec_form.py   builds InsetGroup rows from Settings (Qt)
```

```python
@dataclass(frozen=True)
class Setting:
    id: str                    # "tls.min_version", stable, stored in files
    path: str                  # keys.json form: "outbounds[].streamSettings.tlsSettings.minVersion"
    scope: Literal["profile", "global", "group"]
    kind: Literal["bool", "int", "float", "str", "enum", "list", "port_range",
                  "duration", "size", "json"]
    default: object            # the core's own default where one exists
    choices: tuple = ()        # enum values
    pattern: str = ""          # str/list items
    minimum: float | None = None
    maximum: float | None = None
    since: str = "26.3.27"     # first core that accepts `path`
    until: str | None = None   # first core that rejects/removes it
    label: str = ""            # tr()-able
    help: str = ""             # ONE sentence: what it does and when to change it
    risk: Literal["safe", "advanced", "security", "experimental"] = "advanced"
    tier: Literal["basic", "advanced", "raw"] = "advanced"
    applies: Callable[[Profile], bool] | None = None   # e.g. only for TLS profiles
    link: LinkField | None = None    # share-link param + encode/decode
    write: Callable | None = None    # default: set `path` in the proxy outbound
```

What reads it:

| consumer | uses |
|---|---|
| forms (`ui/spec_form.py`) | kind, choices, bounds, label, help, tier, risk, since/until (disable + reason) |
| validation (`engine.validate`) | kind, choices, pattern, bounds, since/until, risk (fail closed) |
| config generation (`engine.apply`) | path/write, applies, default (an unset value writes nothing) |
| links (`engine.to_link/from_link`) | link |
| inventory (`tests/test_xray_coverage.py`) | path must exist in `keys.json` at `since`; keys owned by a Setting count as `full` automatically, so status.toml can't drift from the code |

### 3.2 Storage (no reshaping of existing data)

- **Per profile:** a new `Profile.options: dict[str, object]` (default empty).
  `Profile.from_dict` already drops unknown keys (`profiles.py:77-79`), so old
  profile files load unchanged and nothing needs migrating. Downgrading loses
  only the new options.
- **Global:** `settings["xray_options"] = []` as a list of `{"id", "value"}`.
  It's a list and not a dict because `settings._merge` treats a dict default as a
  schema and would drop every entry (`settings.py:145`). It's added to
  `DEFAULTS`.
- **Groups and chains:** a new `groups.json` store next to `profiles/`, shaped
  like `ProfileStore`.

### 3.3 How existing outbounds keep working

`render.build_text` gains one step at the end of the outbound phase: after
`outbounds.apply_profile(cfg, profile)` and `coreopts.apply_all(...)`
(`render.py`), it calls `xspec.apply(cfg, profile=..., globals=...,
core=...)`. The existing `outbounds/*.py`, `_common.py` and `coreopts.py` stay
unchanged. A Setting never overwrites a key the old code already writes unless
its id is on an explicit `MIGRATED` list. So new settings adopt the model first,
and moving old Profile fields (sni, fp, alpn…) into Settings is a separate,
optional step, one field per commit, each with a round-trip test.

Example catalog entries:

```python
Setting(id="dns.block_poisoned", path="dns.servers[].unexpectedIPs", scope="global",
        kind="list", default=(), tier="basic", risk="safe",
        label="Reject poisoned DNS answers",
        help="Throws away DNS answers that point at known block pages; leave on in Iran.",
        write=dns_unexpected_ips)          # fills every non-domestic server
Setting(id="tls.min_version", path="outbounds[].streamSettings.tlsSettings.minVersion",
        scope="profile", kind="enum", choices=("1.2", "1.3"), default=None,
        risk="security", label="Minimum TLS version",
        help="Refuses older TLS; set 1.3 only if the server supports it.",
        applies=lambda p: p.security == "tls")
Setting(id="sockopt.tcp_fast_open", path="outbounds[].streamSettings.sockopt.tcpFastOpen",
        scope="global", kind="bool", default=False, risk="advanced",
        label="TCP Fast Open", help="Saves one round trip per connection; turn off if connections fail.")
```

---

## 4. Information architecture

The default user doesn't know what Xray is. They paste a link or a subscription
and press Connect. Everything below starts from that user.

| tier | visible | contains |
|---|---|---|
| **Basic** | always | what a link can't decide and most users want: routing presets, block ads, direct Iran, DNS preset, poisoned-answer protection, fragment on/off, hotspot, local proxy port |
| **Advanced** | a collapsed **Advanced** section at the end of the page it belongs to | every other client-side key with a form (per-transport, TLS, REALITY, sockopt, per-level timeouts, observatory tuning) |
| **Raw JSON** | a per-section **Edit as JSON…** button inside Advanced | the escape hatch for anything without a form: per-profile `streamSettings`, per-profile outbound `settings`, `dns` (exists: `dns.raw_override`), routing (exists: rule-set import) |

Placement per section (Advanced lists are what the catalog fills, not new pages):

| section (page) | Basic | Advanced | Raw |
|---|---|---|---|
| Server editor | from link: address, port, id, transport, security | transport knobs (xhttp xmux/download, grpc multiMode/authority, ws heartbeat), TLS min/max, ALPN, pinned cert, REALITY mldsa65Verify, **Connect through…** | streamSettings JSON |
| Routing | presets + Iran/ads/private toggles (exist) | source IP rules (hotspot clients), webhook (experimental), domainStrategy (exists) | rule-set JSON (exists) |
| DNS | preset (exists), **reject poisoned answers** | per-server expect/unexpect IPs, finalQuery, clientIp, timeouts, cache, useSystemHosts | `dns` JSON (exists) |
| Network | fragment on/off (exists) | fragment/noises for **direct** traffic, TFO, MPTCP, BBR, keep-alive, happy eyeballs, mux (exists) | — |
| Groups | Auto (best) per subscription | strategy, probe URL/interval, tolerance, fallback | — |
| Local proxy | port, LAN share (exist) | HTTP proxy port, sniffing overrides | — |

Rules every setting follows:

1. **Safe default.** An unset value writes nothing, so the core's own default
   applies. The installed behaviour is unchanged until the user acts (the same
   rule `coreopts.py` follows).
2. **Inline validation.** The form checks kind, choices, pattern and bounds as
   you type, and Save stays disabled with the reason under the field.
   `engine.apply` validates again and **drops** a bad value when the config is
   built (as `dns.py` does), so a typo in `settings.json` never reaches Xray.
3. **One sentence** in `help`: what it does, and when to change it.
4. **Not supported by the bundled core** (`since` > bundled): shown disabled
   with *"Needs Xray 26.5.3 or newer (bundled: 26.3.27)"*, never hidden.
5. **Security-sensitive fails closed.** An invalid value with `risk="security"`
   (pinned cert, verify-by-name, min TLS, cipher suites, disableSystemRoot) is
   **not** dropped silently. Connect refuses with *"Server ‘X’: pinned
   certificate is not a valid SHA-256 hash. Fix it in Advanced → TLS."*
   Dropping it would quietly connect with weaker security than the user asked
   for. `masterKeyLog` (writes TLS keys to disk) is kept off the forms entirely
   (open decision D8).
6. **Test before touching.** Every connect, reconnect and server switch runs
   `Connection.preflight(profile)`: render, then `xraycheck.check_config`, with
   no network changes. The running connection is torn down only if preflight
   passes. Otherwise it stays up and the error names the setting. This fixes F2.
   Preflight also runs `xray_keys.unknown_paths` in debug builds, so ignored
   keys show up in the log.
7. **Experimental** (`risk="experimental"`): off by default, labelled with an
   *Experimental* tag, listed last in Advanced.

---

## 5. Wireframes

### 5.1 Policy group (balancer + observatory)

Servers page: a group is one row, above its members.

```
┌ Servers ──────────────────────────────────────────────────────────────┐
│  ⚡ Auto · MyProvider              using  de-3  ·  142 ms   [Connect] │
│     12 servers · fastest · checked 20 s ago                    [···]  │
│  ──────────────────────────────────────────────────────────────────── │
│  de-1   vless · reality                                  188 ms       │
│  de-3   vless · reality                                  142 ms  ●    │
│  nl-2   trojan · tls                                     timeout      │
└───────────────────────────────────────────────────────────────────────┘
```

A subscription gets its group from the switch **"Add an Auto (best server)
entry"** in the subscription editor. It's on by default for new subscriptions
and off for existing ones. **New group…** (Servers ▸ ···) opens:

```
┌ New group ────────────────────────────────────────────────────┐
│ Name        [ Auto · MyProvider               ]               │
│ Servers     (•) Every server in  [ MyProvider ▾ ]             │
│             ( ) These servers    [ pick… ]  (0 chosen)        │
│             ( ) Names matching   [ de-*          ]            │
│ Choose      [ Fastest right now ▾ ]                           │
│               Fastest right now      (leastPing)              │
│               Fastest and steady     (leastLoad)              │
│               Take turns             (roundRobin)             │
│               Any                    (random)                 │
│ ▸ Advanced                                                    │
│     Check with   [ https://www.google.com/generate_204 ]      │
│     Every        [ 1 min ▾ ]                                  │
│     If all fail  [ Stay on the last good server ▾ ]           │
│                                   [ Cancel ]  [ Save ]        │
└───────────────────────────────────────────────────────────────┘
```

Defaults: fastest (`leastPing`), probe `generate_204`, interval 1 minute,
fallback = the last server that worked. **At most 50 members**: each member is
one outbound plus probe traffic.

What it generates: one outbound per member (`tag` = `g-<uid>`), each bound to the
physical interface like `proxy` is today; `routing.balancers[]` with `selector:
["g-"]`, `strategy`, `fallbackTag`; `observatory` (or `burstObservatory` for
leastLoad) with `subjectSelector: ["g-"]`; the default route rule points at
`balancerTag` instead of `proxy`. Host routes: every member's server IP gets
pinned, not just one (`_net_posix.add_host_route`). This is the main connection
change.

Live row: read `ObservatoryService.GetOutboundStatus`, which exists in 26.3.27
(`app/observatory/command/command.proto:18-19`). Whether `xray api` exposes it
from the command line the way `metrics.query_stats` uses `statsquery` is
**UNVERIFIED**; otherwise use a small gRPC client.

Errors:

| state | shown |
|---|---|
| no members | Save disabled: *"Pick at least one server."* |
| a member fails preflight | that member is left out with ⚠ *"skipped: <reason>"*; the group still connects |
| every member fails preflight | Connect refuses: *"No server in this group can start."* |
| all probes fail while connected | row turns amber: *"No server answers — staying on de-3."* (fallback) |
| a subscription refresh empties the group | row greys out: *"MyProvider has no servers."* |
| more than 50 members | *"Only the first 50 servers are used."* |

A group change applies on the next connect, like every other config change
(restarting Xray destroys the TUN).

### 5.2 Proxy chaining (dialerProxy)

In the server editor, Advanced ▸ **Connect through**:

```
┌ Server: us-exit ──────────────────────────────────────────────┐
│ ▾ Advanced                                                    │
│   Connect through   [ Nothing (direct) ▾ ]                    │
│                       Nothing (direct)                        │
│                       Another server…  → [ de-3 ▾ ]           │
│                       A proxy on this network → socks5://…    │
│   Your traffic:  You → de-3 → us-exit → Internet              │
└───────────────────────────────────────────────────────────────┘
```

Server list row: `us-exit   via de-3   vless · reality`.

Defaults: *Nothing*. One hop only (open decision D4).

What it generates: the entry server becomes an extra outbound `chain-<uid>`,
bound to the physical interface. The exit (`proxy`) gets
`streamSettings.sockopt.dialerProxy = "chain-<uid>"` and **loses** its
`sockopt.interface`, because it dials through the entry and not the NIC
(**UNVERIFIED** whether the core minds both being set). The host route is pinned
to the **entry** server's IP (today `connect` pins `profile.address`,
`connection.py:148`). Fragment already skips a chained outbound
(`coreopts.py:79-82`). A local-proxy entry needs a `socks`/`http` outbound,
which is unsupported today (`status.toml`).

Errors:

| state | shown |
|---|---|
| entry is the server itself, or a loop | the choice is disabled in the menu |
| entry server deleted | the row shows ⚠ *"de-3 was removed"*; Connect refuses with the same text |
| entry fails preflight | Connect refuses: *"The entry server de-3 can't start: <reason>."* |
| entry is UDP-only (Hysteria2, WireGuard) and the exit needs TCP | **UNVERIFIED** whether dialerProxy carries TCP over them; until tested, those entries are disabled with *"Can't carry this server's traffic yet."* |
| local proxy unreachable | Connect fails with the probe error; the tunnel is not touched (preflight) |

---

## 6. Implementation order

Each phase ships on its own with tests, and no phase changes UI a previous
phase finished.

| phase | content | depends on | tests |
|---|---|---|---|
| **P0 fixes** | preflight before touching the connection (F2); h2/http: refuse at import and in the editor, with a message (F1, decision D1); Hysteria2 ECH (F5); keyword args to `render.build` (F8); drop the dead TUN `dns` line or keep it deliberately (F4, D9) | — | preflight keeps the old tunnel on a bad config; importing an h2 link is refused; `KNOWN_UNKNOWN` shrinks |
| **P1 spec engine** | `xspec` model/engine/corever, storage (`Profile.options`, `settings.xray_options`), `spec_form.py`, three pilot settings (TFO, happy eyeballs, TLS min version) | P0 | every Setting.path exists in keys.json at `since`; unset writes nothing; a bad value is dropped at render and refused in the form; security-sensitive fails closed; a disabled-by-version setting renders disabled |
| **P2 DNS protection** | reject poisoned answers (Basic, on with Iran direct), per-server expect/unexpect IPs and finalQuery (Advanced) | P1 | rendered dns block; the Iran preset; no DNS leak test regressions |
| **P3 direct traffic** | fragment and noises for the `direct` outbound, redirect; UDP noise mask for WireGuard/Hysteria2 | P1 | eligibility (TLS only for fragment), `xray -test` on the rendered config |
| **P4 transports and TLS** | structured xhttp (xmux, downloadSettings) replacing raw `extra` for those keys; grpc multiMode + link `mode=multi`; ws heartbeat; TLS advanced; REALITY mldsa65Verify (link param name **UNVERIFIED**) | P1 | link round-trip for each new link field; `extra` still passes through unknown xhttp keys |
| **P5 policy groups** | group store, Servers row, dialog, balancer/observatory rendering, multi-host-route pinning, live status | P0, P1 | render golden files; route pinning for N servers; failover state machine with fake observatory |
| **P6 chaining** | Connect through (server), host route to entry, then local SOCKS/HTTP proxy entry | P1, P5 (group as exit: later) | loop detection; route pinned to entry; interface dropped on exit |
| **P7 raw JSON per section** | Edit as JSON… with parse + `unknown_paths` (refuse unknown keys) + `xray -test` | P1 | a misspelt key is refused with its path |
| **P8 core upgrade (gated)** | choose the next core; re-run `extract`; review `removed` keys sushTun writes (F3 udpHop, F4 tun dns) before switching; then open gated keys (finalRules 26.5.3, finalmask xmc/realm/udphop, XDRIVE) | decision D6 | `test_sushtun_writes_no_key_the_bundled_core_ignores` against the new baseline |

---

## 7. Open decisions

- **D1.** h2/http profiles: refuse them with a clear message, or convert them to xhttp (the core's own error suggests "XHTTP stream-one")? Converting changes what the server sees, so it only works if the server also runs xhttp. My recommendation is refuse plus explain.
- **D2.** Should `Profile.options` stay a free dict validated by the catalog, or should each new setting become a typed Profile field? The dict keeps profile files stable. Typed fields are easier to read.
- **D3.** For the group live status, is a small gRPC client (ObservatoryService) acceptable, or should we poll with our own speed test instead? The second is simpler but duplicates the probe traffic.
- **D4.** Chaining depth: one hop only? Can a group be an entry or an exit?
- **D5.** New settings in share links: the Xray link format has no field for most of them. Do we add sushTun-only query params (other clients will ignore them), or share such servers as JSON instead?
- **D6.** Core policy: stay on stable 26.3.27 until the next stable release, or offer a pre-release channel? This decides when the gated keys open, and when F3 and F4 must be handled.
- **D7.** Experimental settings: one global "Show experimental settings" switch, or always visible with the tag?
- **D8.** Security-sensitive list: should `masterKeyLog` and `disableSystemRoot` be offered at all? My recommendation is no for `masterKeyLog`.
- **D9.** The TUN `dns` line: delete it now (it's dead on 26.3.27), or keep it on purpose for a newer core? If we keep it, check what it does there first.
- **D10.** Fragment is global today (`settings.core.fragment`). Should it also be settable per profile once the spec engine exists?
