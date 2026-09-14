<h1 align="center">sushTun</h1>

<p align="center">A fast, portable Xray TUN client with a clean desktop UI.</p>

<p align="center">
  <a href="https://github.com/soroushdeimi/sushTun/actions/workflows/ci.yml">
    <img alt="CI" src="https://github.com/soroushdeimi/sushTun/actions/workflows/ci.yml/badge.svg">
  </a>
  <a href="https://github.com/soroushdeimi/sushTun/releases/latest">
    <img alt="Release" src="https://img.shields.io/github/v/release/soroushdeimi/sushTun">
  </a>
  <a href="LICENSE">
    <img alt="License" src="https://img.shields.io/badge/license-MIT-blue.svg">
  </a>
</p>

---

sushTun routes all of your system traffic through an Xray tunnel and puts you in
full control of it from a single window: import a server, choose what bypasses
the tunnel, and connect. It ships as one self-contained binary — no install, no
dependencies.

## Features

- **Servers** — VLESS, VMess, Trojan, Shadowsocks, Hysteria2, and WireGuard, with
  certificate pinning and ECH. Import from links, base64 subscriptions, a
  WireGuard `.conf`, raw JSON, or a QR code; test real delay or TCP ping (one
  server or a whole selection), switch to the fastest, and copy a share
  link/QR straight from the table.
- **Subscriptions** — tracks your plan's data quota and expiry with a live usage
  bar; each one refreshes on its own schedule, with an optional name filter and
  custom User-Agent, or refresh them all at once.
- **Smart alerts** — a tray notification and in-app banner when data runs low or
  a plan is about to expire, throttled to once per day per threshold.
- **Split routing** — Simple toggles for Iran, Russia, China, ad/tracker
  blocking, and your own domains and IPs, or build named custom rule sets with
  v2rayN-compatible import/export and their own geo-data updater.
- **Custom DNS** — pick your resolvers (DoH, DoT, plain, or a one-click preset),
  a separate domestic resolver for domains your routing sends direct, resolving
  the rest through the tunnel, and advanced overrides when you need them.
- **Core tuning** — anti-filter TLS fragmentation, multiplexing, traffic
  sniffing, and a local proxy you can share with other devices on your network.
- **Low-usage mode** — a single toggle sends OS telemetry and update traffic
  direct so it never eats your quota, while everything else stays tunneled.
- **Share via hotspot** *(Windows, Linux)* — put the tunnel behind a Wi-Fi hotspot
  so phones and other devices are covered the moment they connect, with nothing to
  configure on the device itself. On Linux sushTun starts the hotspot through
  NetworkManager (named "sushTun"; the password is shown in the log), alongside the
  Wi-Fi you are connected to when the card supports it.
- **Startup and backup** — start sushTun at login (Windows, and the `.deb` on
  Linux) with optional auto-connect, back up and restore your servers and
  settings as a zip, and get a banner when a new release is out.
- **Persian interface** — a full right-to-left فارسی translation, switchable in
  Settings.
- **Live metrics** — real-time throughput and total data used this session,
  plus ping, TCP-delay, and diagnostics tools alongside a colorized live log.

## Download

Grab the latest build for your platform from the
**[Releases page](https://github.com/soroushdeimi/sushTun/releases/latest)**:
`sushTun-windows.exe`, `sushTun-linux`, or `sushTun-macos`. Each is a single
ready-to-run binary — no Python or dependencies required. The portable build
keeps its settings and profiles next to the file itself.

On Debian/Ubuntu you can install it instead of running the portable binary:
the `sushtun_<version>_amd64.deb` asset adds sushTun to the app menu with its
icon, and keeps settings and profiles in `/var/lib/sushtun`.

```bash
sudo apt install ./sushtun_*_amd64.deb   # then launch "sushTun" from the app menu
sudo apt remove sushtun                  # uninstall (purge also deletes your data)
```

sushTun requests elevated privileges on launch, since changing routes, DNS, and
the network device requires admin (Windows), root via `pkexec`/`sudo` (Linux),
or an `osascript` prompt (macOS).

## Platform support

| Platform | Status |
|----------|--------|
| Windows | Fully supported |
| Linux   | Uses Xray's native TUN inbound, the same model as Windows. Connect path is experimental and being hardened. |
| macOS   | Xray has no native TUN inbound here, so sushTun runs it with a SOCKS inbound and bridges that to a real TUN device via [tun2socks](https://github.com/xjasonlyu/tun2socks). Unverified on real hardware — experimental. |

## Building from source

```bash
python -m pip install -r requirements-dev.txt
python scripts/fetch_deps.py   # fetches xray-core, geo data, and platform TUN helpers
python -m xrayui
```

To produce a standalone binary:

```bash
pyinstaller tools/build.spec
```

## License

Released under the [MIT License](LICENSE).
