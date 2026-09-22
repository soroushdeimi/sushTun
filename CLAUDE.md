# sushTun

A portable Xray **TUN** client with a PySide6 desktop UI. It routes all system traffic
through one Xray tunnel and keeps the UI simple. Windows is fully supported. Linux uses
Xray's native TUN inbound (experimental). macOS bridges a SOCKS inbound to a TUN device
with tun2socks (unverified).

The names are mixed for historical reasons: the Python package is `xrayui`, the product
is **sushTun**, and the portable release binaries are `XrayPortable-*`. Use "sushTun" in
anything the user sees.

## Commands

```bash
python -m pip install -r requirements-dev.txt
python scripts/fetch_deps.py          # xray-core, geoip/geosite.dat, wintun/tun2socks
python -m xrayui                      # run (relaunches itself elevated: pkexec/sudo/UAC/osascript)
ruff check .                          # lint (CI runs this)
QT_QPA_PLATFORM=offscreen python -m pytest -q   # tests (CI runs this)
pyinstaller tools/build.spec          # one-file portable build
SUSHTUN_ONEDIR=1 pyinstaller tools/build.spec && python scripts/build_deb.py   # .deb
```

CI (`.github/workflows/ci.yml`) runs ruff and pytest with Qt offscreen. The UI tests
must actually run: a skipped UI suite fails CI on purpose.

## Layout

```
xrayui/
  __main__.py        entry: elevation relaunch, headless --restore-stale mode
  paths.py           base_dir() is writable data, resource_dir() is bundled read-only
                     assets. An installed .deb keeps data in /var/lib/sushtun.
  elevate.py         per-OS admin relaunch
  core/              no Qt imports here, so it stays testable
    profiles.py      Profile dataclass + ProfileStore (profiles/<uid>.json, active.txt)
    importer.py      vless://, wireguard://, WG .conf, base64 subs, Xray JSON, QR
    subscription.py  fetch sub URL, Subscription-Userinfo quota, SubscriptionStore
    render.py        config.template.json + Profile + settings → config.runtime.json
    routing.py       settings["routing"] → Xray routing rules (direct/block/proxy)
    dns.py           settings["dns"] → Xray dns block, validation, presets
    settings.py      settings.json deep-merged over DEFAULTS
    connection.py    connect/disconnect lifecycle, route/DNS repair, stale recovery
    network.py       platform façade over _net_posix.py / Windows backends
    xray.py, tun2socks.py, proc.py   child processes (XRAY_LOCATION_ASSET is set)
    hotspot.py       share the tunnel over a Wi-Fi hotspot (Windows ICS, Linux NM)
    metrics.py       ping, TCP delay, throughput, Xray stats API, diagnostics
    alerts.py        quota/expiry alerts with per-day throttle
    bootrestore.py   task that restores DNS after a crash or power-off
  ui/                PySide6: main_window, dialogs, routing_dialog, dns_dialog,
                     subscription_panel, tools_panel, widgets, titlebar, theme
config.template.json the base Xray config. Inbounds: tun-in, dns-in (127.0.0.1:53),
                     socks-in (127.0.0.1:10808). Outbounds: proxy, dns-out, direct, block.
tests/               pytest, one file per core module plus test_ui.py
```

### How a connection is built
`Connection.connect()` works in this order:
1. Detect the physical interface.
2. Refuse to start if another VPN owns the default route.
3. Resolve the server and back up DNS.
4. `render.build()`: only the `proxy` outbound is rewritten from the Profile. Routing
   rules, stats API, log level, DNS and MTU are overlaid. `__IFACE__` is replaced last,
   so direct and DNS traffic stays bound to the physical interface.
5. Pin a host route to the server, then start Xray. Xray creates `xray0` itself.
6. Address the TUN, save state and install boot-restore *before* pointing the OS
   resolver at 127.0.0.1.
7. Add default routes, then optionally start the hotspot.

Restarting Xray destroys the TUN, so config changes apply on the next connect.

## Rules that must hold

- **No DNS leaks, and no stranded network.** Any path that changes DNS or routes must
  have a guaranteed undo (`_restore`, `recover_if_stale`, bootrestore). Save state
  before changing the network. Tear down in reverse order: hotspot, then tunnel.
- **A bad setting must never stop the app from connecting.** Xray exits on a config it
  cannot parse. Validate in the dialog (refuse to save) and drop bad entries when
  building the config, as `dns.py` does. Never let settings.json typos reach Xray.
- `settings._merge` drops keys that are not in `DEFAULTS` and treats dict defaults as a
  schema. Store user maps as lists (see `dns.hosts`). Add every new key to `DEFAULTS`.
  If an existing shape changes, write an explicit migration.
- `dns.py` refuses `localhost` (a resolver loop) and `fakedns` on purpose. Keep it that way.
- Pass arguments to `render.build`/`build_text` by keyword, never by position.
- Code in `core/` must not import Qt. The UI runs blocking work through
  `MainWindow._run_async` (QThreadPool workers). Never block the UI thread.
- Stay on the **Xray core only**. No sing-box, mihomo or other cores.
- Test on Linux as well as Windows: routes and DNS go through NetworkManager and
  resolvectl, and system tools run with the system's libraries, not the bundle's
  (`proc.child_env`).

## Code style

- Python ≥3.11, `from __future__ import annotations`, ruff (E, F, I, UP, B, W),
  line length 100.
- Comments explain *why*: the failure a line prevents, not what the line does. Match
  the density of the file you are editing.
- Every new `core/` behaviour gets a pytest in `tests/`. The UI tests execute dialogs
  and the main window offscreen.

## Git and releases

- Commit as the repository user's own git identity. Never add AI attribution (no
  Co-Authored-By trailers, no "generated with" lines) in commits, PRs, tags or comments.
- Conventional commits: `feat(scope): …`, `fix(linux): …`, `refactor: …`, `test(ui): …`,
  `build: …`, `docs: …`, `chore: bump version to X.Y.Z`.
- A release bumps the version in `pyproject.toml` **and** `xrayui/__init__.py`, adds a
  `## vX.Y.Z` section to `CHANGELOG.md` (user-facing, explains what broke and why), and
  pushes a `v*` tag. The tag triggers the Release workflow. Ask before tagging or pushing.

## Reference

v2rayN's source is at `../v2rayN` (C#, Avalonia). It is the reference for features
being ported: `ServiceLib/Handler/Fmt/*` (link formats), `ServiceLib/Services/SpeedtestService.cs`,
`ServiceLib/Sample/custom_routing_*`, `ServiceLib/Models/Entities/*`. The roadmap is in
`prompt.md`. The rule for porting: **v2rayN's features, sushTun's simplicity.** Defaults
up front, advanced settings behind a collapsed section.
