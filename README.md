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

- **Servers** — import from `vless://` links, base64 subscriptions, raw JSON, or
  a QR code; edit, duplicate, and switch between profiles.
- **Subscriptions** — tracks your plan's data quota and expiry with a live usage
  bar, refreshed automatically in the background.
- **Smart alerts** — a tray notification and in-app banner when data runs low or
  a plan is about to expire, throttled to once per day per threshold.
- **Split routing** — choose what skips the tunnel: Iran, Russia, and China
  (via geosite/geoip), ad and tracker blocking, the local network, or your own
  domains, IPs, and app presets.
- **Low-usage mode** — a single toggle sends OS telemetry and update traffic
  direct so it never eats your quota, while everything else stays tunneled.
- **Share via hotspot** *(Windows)* — put the tunnel behind the Windows mobile
  hotspot so phones and other devices are covered the moment they connect, with
  nothing to configure on the device itself.
- **Live metrics** — real-time throughput and total data used this session,
  plus ping, TCP-delay, and diagnostics tools alongside a colorized live log.

## Download

Grab the latest build for your platform from the
**[Releases page](https://github.com/soroushdeimi/sushTun/releases/latest)**.
Each release ships ready-to-run binaries for Windows, macOS, and Linux — no
Python or dependencies required.

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
