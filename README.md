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
- **Core tuning** — anti-filter TLS fragmentation, UDP noise before a Hysteria2
  handshake, multiplexing, traffic sniffing, TCP Fast Open / Multipath TCP / congestion
  control, post-quantum server verification for REALITY, and a local proxy you can
  share with other devices on your network.
- **Low-usage mode** — a single toggle sends OS telemetry and update traffic
  direct so it never eats your quota, while everything else stays tunneled.
- **Share via hotspot** *(Windows, Linux)* — put the tunnel behind a Wi-Fi hotspot
  so phones and other devices are covered the moment they connect, with nothing to
  configure on the device itself. On Linux sushTun starts the hotspot through
  NetworkManager alongside the Wi-Fi you are connected to when the card supports it,
  and Settings → Hotspot holds its name, password, WPA2/WPA3, band, a hidden network,
  and whether joined devices can see each other.
- **Multi-exit port** — one local SOCKS port where the **username picks the exit
  server**: `socks5://de:PASSWORD@127.0.0.1:10809` leaves through the server you named
  "de" while everything else keeps using the main tunnel. A chosen exit wins over the
  routing rules; UDP is refused on this port, because the username does not travel with
  UDP packets and the traffic would leave through the wrong server.
- **Port forwarding** — map a local port to one fixed address, through the tunnel or
  directly: reach a machine only your server can see, or force one destination through
  the tunnel whatever the routing says. Each forward can be switched off, or shared with
  other devices on your network.
- **Startup and backup** — start sushTun at login (Windows, and the `.deb` on
  Linux) with optional auto-connect, back up and restore your servers and
  settings as a zip, and get a banner when a new release is out.
- **Persian interface** — a full right-to-left فارسی translation, switchable in
  Settings.
- **Live metrics** — real-time throughput and total data used this session,
  plus ping, TCP-delay, and diagnostics tools alongside a colorized live log.

## How it works

Xray runs as one child process with a config sushTun writes at connect time, and the
operating system is pointed at it. Everything below is what actually happens on Linux
and Windows; macOS differs only in the first hop (see *Platform support*).

```text
              your apps, the whole system
                        |
      +-----------------+------------------+
      |                 |                  |
   routes            resolver         apps that dial
 0.0.0.0/1 +        172.19.0.1        a proxy themselves
 128.0.0.0/1            |                  |
   -> xray0             |                  |
      |                 |                  |
 +----v-----------------v------------------v--------------------------+
 |  Xray, one process, config.runtime.json                            |
 |                                                                    |
 |   tun-in          dns-in          socks-in    exits-in    fwd-PORT  |
 |   xray0        127.0.0.1:53      :10808      :10809     (optional) |
 |   172.19.0.2/30                            username =              |
 |      |               |               |     which exit     |        |
 |      +-------+-------+-------+-------+---------+----------+        |
 |                      |                                             |
 |               routing rules, in this order:                        |
 |                 1. stats API                                       |
 |                 2. DNS                                             |
 |                 3. multi-exit + port forwards   <- a deliberate    |
 |                 4. ads / Iran / private / yours    choice wins     |
 |                      |                                             |
 |      +---------------+---------+------------+-----------+          |
 |      |               |         |            |           |          |
 |   proxy          exit-SERVER  direct     dns-out      block        |
 |   (your server)  (optional)   |          (DoH)          X          |
 +------|---------------|--------|------------|-----------------------+
        |               |        |            |
        +---------------+--------+------------+
                        |
        all of them bound to the physical interface,
        so they never re-enter the tunnel they carry
                        |
        proxy, exit-SERVER  ->  your server  ->  the internet
        direct, dns-out     ->  the internet directly
```

**The order of the routing rules matters**, and sushTun builds it deliberately:

1. the stats API,
2. DNS (`dns-in`, and port 53 out of the tunnel),
3. multi-exit and port-forward rules, so a deliberate choice always wins,
4. your own rules: blocked ads, Iran/Russia/China direct, private addresses, custom sets.

**Two details make the whole thing work.** The tunnel takes over with two `/1` routes
instead of replacing the default route: they are more specific, so they win, while your
real default route stays untouched and other VPNs with more specific routes keep
working. And every outbound that must *not* go through the tunnel — `proxy`, `direct`
and `dns-out` — is bound to the physical interface, so the connection to your server
never loops back into the tunnel it is carrying.

**DNS** never leaves the tunnel: the system resolver points at `172.19.0.1` on `xray0`,
queries arrive at `dns-in`, and Xray answers them over DoH. Domains your routing sends
direct can use a separate domestic resolver.

**Coming back down is the careful part.** Before anything is changed, the previous DNS
and routes are saved; teardown restores them in reverse order (hotspot, then tunnel),
and a boot task puts them back if the app is killed or the machine loses power.

**The hotspot** *(Linux)* is a second virtual Wi-Fi interface (`sushap0`) on the same
radio, shared by NetworkManager, with forwarding enabled on `xray0` so replies coming
back out of the tunnel reach the phones.

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
