# Changelog

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
