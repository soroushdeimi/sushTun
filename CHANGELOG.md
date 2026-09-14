# Changelog

## Unreleased

### Fixed: 0.1.13 crashed on start whenever a subscription existed
The server list loaded every `*.json` file in the profiles folder as a server,
including `subscriptions.json` — the per-subscription settings file subscriptions
themselves are stored in. Parsing that as a server profile crashed the app on
startup for anyone with even one subscription configured. The server list now
skips it explicitly.

### Fixed: subscriptions
- **The active server, and its test history, could be lost on every refresh.**
  Refreshing a subscription deleted every one of its old servers and saved the
  newly parsed ones under fresh IDs, so the active pointer (and anything Test
  had recorded) reset each time, even when nothing about the server actually
  changed. A refresh now matches old and new servers by protocol/address/port/ID
  and reuses the old ID when a server reappears, so both survive a normal refresh.
- **A refresh that failed to parse anything deleted the whole server list**
  instead of leaving it alone. An empty or unparseable response no longer
  touches the servers already saved.

### Fixed: importing
- **Importing a raw Xray JSON config lost the WebSocket path/host and the gRPC
  service name**, since the importer never read `wsSettings`/`httpSettings`/
  `grpcSettings`. Both round-trip correctly now.
- **A corrupted `settings.json` (valid JSON, but not an object) stopped the app
  from starting at all.** It's now treated the same as a missing or unreadable
  file: sushTun falls back to defaults instead of failing to launch.

### New: every major Xray protocol and transport
VMess, Trojan, Shadowsocks, and Hysteria2 join VLESS and WireGuard, each with
its own settings (ciphers, obfuscation, port-hopping, and more). Streams also
gained the xhttp and httpupgrade transports, TLS certificate pinning (SHA-256),
and ECH.

### New: a real server table
Sortable columns for delay, transport, subscription, and type, with a name/
address filter. Real-delay and TCP-ping tests run one server or a whole
selection at once, "Use fastest" switches to the quickest responder, share
links and QR codes can be copied straight from the table, and Ctrl+V imports
whatever's on the clipboard.

### New: custom routing rule sets
A "Rule sets" tab alongside the existing Simple bypass toggles: build named
rule sets from domain/IP/port/network/protocol/process conditions, import and
export them in a v2rayN-compatible format (file, clipboard, or a URL —
including a one-click import of Chocolate4U's Iran rule set), and pick the
active set from the main window or the tray's "Routing" submenu. A "Reconnect
now" button appears whenever a change needs one. The bundled geo data
(geosite/geoip) that rules like `geosite:category-ads-all` depend on now has
its own updater, with a source picker and an optional auto-update interval.

### New: DNS control
Route domains your routing sends direct through a separate domestic DNS
resolver, resolve everything else through the tunnel instead of your normal
connection, and reach for parallel queries, serve-stale, or a raw DNS block
override when you need them.

### New: core tuning
Anti-filter splits the TLS handshake into pieces small enough that filtering
can't read it. Multiplexing and traffic sniffing are now configurable, the
local SOCKS proxy's port can be changed and shared with other devices on your
network (with a password), and outbounds can be given a default TLS
fingerprint.

### New: subscriptions, your way
Each subscription now has its own auto-update interval, a name filter (regex)
to keep only the servers you want, and a custom User-Agent — plus an "Update
all" button that refreshes every enabled subscription in one go.

### New: tray, startup, and backup
- A "Servers" submenu on the tray icon switches your active server without
  opening the window.
- sushTun can start automatically at login (Windows, and the `.deb` package
  on Linux) and optionally connect right away, with a delay while the network
  comes up.
- Settings, servers, and subscriptions can be backed up to a zip and restored
  from one.
- sushTun checks for new releases in the background and shows a banner with a
  one-click "copy download link" — it never opens a browser itself, since it
  runs elevated.

### New: a Persian (فارسی) interface
A full right-to-left translation, switchable in Settings. Technical values —
addresses, keys, JSON, anything you'd type exactly — always stay left-to-right
and untranslated, wherever they appear.

### Changed: "Allow insecure" is gone
The bundled Xray build now refuses to start with `allowInsecure` set at all,
so the toggle could only ever produce a server that fails to connect. Pin the
server's certificate (SHA-256) instead, in the profile editor's Advanced
section — the field that "Allow insecure" configs already carried over.

### Changed: portable download names
Downloads are now named `sushTun-windows.exe` / `sushTun-linux` / `sushTun-macos`
instead of `XrayPortable-*`. The portable build keeps settings and profiles next to
the file, so put the new file in the same folder as the old one. The Windows
boot-restore task re-registers itself with the new file on the next Connect.

## v0.1.13

### New: a macOS-style window on Windows and Linux
- The window now has macOS traffic lights: red closes, yellow minimizes, green zooms.
  Hovering over them shows their ×, − and zoom marks, and they turn grey when the window
  is not focused. Drag the title bar to move the window, double-click it to zoom, and
  drag any edge to resize. macOS keeps its own native title bar.
- The red button now closes only the window, as on macOS: the tunnel keeps running and
  the tray icon brings the window back. The first time, a tray message says so. Quit from
  the tray menu or press Ctrl+Q. Where there is no tray icon, closing still quits.
- New shortcuts: Ctrl+W closes the window, Ctrl+M minimizes it, Ctrl+Q quits.
- The theme follows macOS dark mode: its colours and system fonts, segmented tabs, and a
  highlighted state for the Low usage and hotspot toggles, which showed no on/off state
  before.

### Fixed: DNS lookups other than plain addresses hung for seconds
Xray answered only address (A/AAAA) queries itself and passed every other kind
(HTTPS/SVCB, SRV, TXT, PTR) on to the tunnel's own address, where nothing answers.
Each one hung until the resolver gave up, filling the log with
`proxy/dns: failed to dial outbound connection ... i/o timeout` and making browsers
and SRV-based apps (XMPP, some VoIP clients) slow to start a connection. Those
queries are now refused at once, so apps fall back immediately.

### New: share the tunnel over a Wi-Fi hotspot on Linux
"Share via hotspot" was shown on Linux but did nothing: it said "applies on next
connect", and then nothing happened. It is now implemented through NetworkManager.
Checked against a real Intel Wi-Fi card's capabilities; a phone joining end to end
has not been tested yet.

- On connect, sushTun starts a hotspot named **sushTun**. The password is made once,
  kept, and shown in the log, so a phone that joined once rejoins by itself.
- If the Wi-Fi card is already connected as a client (your internet), the hotspot runs
  on a second, virtual interface on the same channel, so the internet stays up. Cards
  that cannot do both at once are refused with a clear message instead.
- Hotspot clients get IPv4 only: the tunnel carries IPv4, and IPv6 would go around it.
- Disconnecting takes the hotspot down before the tunnel, so clients never fall back to
  the unprotected connection.
- If you enable the `ufw` firewall, allow forwarding (`DEFAULT_FORWARD_POLICY="ACCEPT"`
  in `/etc/default/ufw`) or hotspot clients will get no internet.
- The button is disabled on macOS, where sharing is not available yet.

## v0.1.12

### Fixed (Linux: running alongside OpenVPN or other VPNs)
- **sushTun could tunnel itself through another VPN.** It picked "the default route
  with the lowest metric" as the internet connection, and NetworkManager's OpenVPN
  routes (metric 50) beat Wi-Fi's (600). sushTun then reached its server *through* the
  office VPN: slower, dropping whenever that VPN reconnected, and the automatic
  gateway-change repair never matched the adapter again. It now picks the real network
  card and uses a tunnel only when nothing else has a route.
- **DNS silently fell back to other VPNs' servers minutes after connecting.** The tunnel's
  DNS setting was wiped without a trace (NetworkManager suspected, since it adopts `xray0`
  as an external device). sushTun now asks NetworkManager to leave `xray0` alone, and
  checks every 15 seconds that the tunnel's DNS is still in place, restoring it and saying
  so in the log if another program cleared it.
- **The "another VPN" check no longer refuses OpenVPN.** It now blocks only VPNs whose
  routing rules override sushTun's (v2rayN/sing-box). A VPN that just adds a default
  route loses to sushTun's routes and can run alongside it.

### Using an office VPN together with sushTun
sushTun answers all DNS by default (`~.`), so an office VPN's internal names resolve only
if its NetworkManager profile names its domain, for example:

```bash
nmcli connection modify "<office VPN>" ipv4.dns-search "~office.example"
```

Then reconnect that VPN. Names under `office.example` go to the office DNS; everything
else goes through sushTun.

## v0.1.11

### Fixed (macOS — found by code review; still needs testing on a real Mac)
- **The tunnel bridge was likely cut off from Xray.** `tun2socks` was pinned to the
  Wi-Fi/Ethernet card (`-interface en0`), but its only peer is Xray on `127.0.0.1`,
  which a card-pinned connection cannot reach (the same trap proven on Linux).
- **The password step broke on a space in the app's path**, and cancelling the
  prompt left nothing on screen. It now falls back to a limited window, as on Linux.
- (Already fixed in v0.1.10, now covered by a test) network services with spaces in
  their name, like "USB 10/100/1000 LAN", lost their DNS on disconnect.

### Known macOS gaps (not fixed yet)
- No restore after a crash or power-off: the 127.0.0.1 DNS setting survives reboot,
  so there is no internet until sushTun is opened again. Windows has a boot task for this.
- The download is an unsigned, bare binary: Gatekeeper blocks it (right-click → Open,
  or `xattr -d com.apple.quarantine XrayPortable-macos`), and it only runs on Apple
  Silicon (built on `macos-latest`), not Intel Macs.

### New: install on Debian/Ubuntu (`.deb`)
A separate download from the portable binary: `sushtun_0.1.11_amd64.deb`.

- Appears in the app menu as **sushTun** with its icon (also in the dock and Alt-Tab).
- The password prompt reads "sushTun needs your password to change network routes and DNS".
- Starts in about 0.2 s; the portable file unpacks ~170 MB on every launch (2 s warm, 11 s cold).
- Settings and profiles live in `/var/lib/sushtun` (root only), not next to the program.

```bash
sudo apt install ./sushtun_0.1.11_amd64.deb
sudo apt remove sushtun      # or `purge` to delete your settings and profiles too
```

**Moving from the portable build:** disconnect and close the portable app first
(both use the `xray0` device and the same ports), then copy your servers over:

```bash
sudo cp -r /path/to/portable/profiles /path/to/portable/settings.json /var/lib/sushtun/
```

### Fixed
- **Linux: DNS leaked outside the tunnel.** The packaged app started system tools with
  its own bundled libraries on the library path; `resolvectl` loaded the bundled
  `libcrypto`, crashed, and DNS was never moved into the tunnel, so lookups went to the
  ISP unencrypted (and could be filtered). System tools now run with the system's own
  libraries. sushTun also reads the DNS setting back and warns if it did not take.
  Check with `resolvectl status xray0`: it should list DNS server `172.19.0.1`.

## v0.1.10

### Fixed (Linux)
- **The window never opened.** The root relaunch through `pkexec` lost the display,
  so the elevated app died silently. A cancelled password prompt now opens a limited
  window that explains why connecting will fail, instead of nothing.
- **Websites stopped loading once connected** (systemd-resolved): DNS pointed at an
  address resolved cannot reach, so every lookup timed out.
- **DNS was gone after disconnecting**: disconnect erased the servers NetworkManager
  had set, and on systems without systemd-resolved it corrupted `/etc/resolv.conf`.
- **Connecting killed other VPN clients' `xray`** (v2rayN, Nekoray): only sushTun's own
  xray is stopped now.
- Connecting now refuses, with a clear message, while another VPN's tunnel (such as
  v2rayN's `singbox_tun`) is carrying traffic: two full tunnels cannot share the route.
- If Xray fails to start, its own error is shown at once instead of a 30-second
  "TUN did not appear".
