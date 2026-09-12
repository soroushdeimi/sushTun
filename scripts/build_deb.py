#!/usr/bin/env python3
"""Package the one-dir build as a Debian/Ubuntu .deb.

Run after `SUSHTUN_ONEDIR=1 pyinstaller tools/build.spec`. The package installs
to /opt/sushtun with a `sushtun` command, an app-menu entry carrying the icon,
and a polkit policy so the password prompt names sushTun. It is a separate
artifact: the portable one-file build is untouched.

    sudo apt install ./dist/sushtun_<version>_<arch>.deb
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xrayui import __version__, paths  # noqa: E402  (needs ROOT on sys.path)

PKG = "sushtun"
PREFIX = f"/opt/{PKG}"
EXE = f"{PREFIX}/{PKG}"
POLICY_ID = "io.github.soroushdeimi.sushtun"

DESKTOP = f"""\
[Desktop Entry]
Type=Application
Name=sushTun
GenericName=VPN Client
Comment=Route all traffic through an Xray tunnel
Exec={PKG}
Icon={PKG}
Terminal=false
Categories=Network;
Keywords=vpn;xray;vless;proxy;tunnel;
StartupWMClass={PKG}
"""

# exec.path makes `pkexec /opt/sushtun/sushtun` use this action's wording and
# icon instead of the generic "run a program as the super user" prompt.
POLICY = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
 "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <vendor>sushTun</vendor>
  <vendor_url>https://github.com/soroushdeimi/sushTun</vendor_url>
  <icon_name>{PKG}</icon_name>
  <action id="{POLICY_ID}">
    <description>Run sushTun</description>
    <message>sushTun needs your password to change network routes and DNS</message>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">{EXE}</annotate>
  </action>
</policyconfig>
"""

POSTINST = f"""\
#!/bin/sh
set -e
if [ "$1" = configure ]; then
    # Profiles hold server credentials: root only.
    install -d -m 0700 {paths.INSTALLED_DATA_DIR}
fi
"""

POSTRM = f"""\
#!/bin/sh
set -e
if [ "$1" = purge ]; then
    rm -rf {paths.INSTALLED_DATA_DIR}
fi
"""


def _control(version: str, arch: str, size_kb: int) -> str:
    # The bundle links against the build machine's glibc, so that is the floor.
    glibc = platform.libc_ver()[1] or "2.35"
    return f"""\
Package: {PKG}
Version: {version}
Architecture: {arch}
Maintainer: soroush <soroushdeimi@gmail.com>
Section: net
Priority: optional
Installed-Size: {size_kb}
Depends: libc6 (>= {glibc}), libegl1, libgl1, libxkbcommon0, libfontconfig1, libdbus-1-3, iproute2, pkexec | policykit-1
Recommends: libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0
Homepage: https://github.com/soroushdeimi/sushTun
Description: Xray TUN client with a desktop UI
 Routes all system traffic through an Xray tunnel. Import vless:// links,
 subscriptions or QR codes, choose what bypasses the tunnel, and connect.
"""


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def stage(onedir: Path, root: Path, version: str, arch: str) -> Path:
    """Lay out the package tree under `root`. Returns `root`."""
    if root.exists():
        shutil.rmtree(root)
    opt = root / PREFIX.lstrip("/")
    shutil.copytree(onedir, opt, symlinks=True)
    (opt / paths.INSTALLED_MARKER).touch()

    bindir = root / "usr" / "bin"
    bindir.mkdir(parents=True)
    (bindir / PKG).symlink_to(EXE)

    share = root / "usr" / "share"
    _write(share / "applications" / f"{PKG}.desktop", DESKTOP)
    icon = share / "icons" / "hicolor" / "512x512" / "apps" / f"{PKG}.png"
    icon.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "assets" / "icon.png", icon)
    _write(share / "polkit-1" / "actions" / f"{POLICY_ID}.policy", POLICY)

    # Modes come from the build machine's umask (002 makes everything
    # group-writable); installed files must not be.
    for p in [root, *root.rglob("*")]:
        if p.is_symlink():
            continue
        if p.is_dir() or p.stat().st_mode & 0o111:
            p.chmod(0o755)
        else:
            p.chmod(0o644)

    size_kb = sum(p.stat().st_size for p in root.rglob("*")
                  if p.is_file() and not p.is_symlink()) // 1024
    debian = root / "DEBIAN"
    _write(debian / "control", _control(version, arch, size_kb))
    _write(debian / "postinst", POSTINST, 0o755)
    _write(debian / "postrm", POSTRM, 0o755)
    return root


def main() -> int:
    onedir = ROOT / "dist" / PKG
    if not (onedir / PKG).exists():
        print(f"{onedir / PKG} not found; first run:\n"
              "  SUSHTUN_ONEDIR=1 pyinstaller tools/build.spec", file=sys.stderr)
        return 1
    arch = subprocess.run(["dpkg", "--print-architecture"], capture_output=True,
                          text=True, check=True).stdout.strip()
    root = stage(onedir, ROOT / "build" / "deb", __version__, arch)
    out = ROOT / "dist" / f"{PKG}_{__version__}_{arch}.deb"
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(root), str(out)],
                   check=True)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
