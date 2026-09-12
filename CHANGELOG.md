# Changelog

## v0.1.11

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
- **Linux: DNS leaked outside the tunnel.** NetworkManager takes over the new `xray0`
  device about a second after it appears and wipes its DNS setting, so lookups went to
  the ISP unencrypted (and could be filtered). sushTun now tells NetworkManager to leave
  `xray0` alone, sets DNS on it, and checks it stuck; if it cannot, the log says so.
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
