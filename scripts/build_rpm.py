#!/usr/bin/env python3
"""Package the one-dir build as a Fedora/RHEL .rpm.

Run on Fedora after `SUSHTUN_ONEDIR=1 pyinstaller tools/build.spec`, so the
bundle links against the glibc and CA layout it will run on. It lays out the
same tree as the .deb (see build_deb.stage) and wraps it with rpmbuild.

    sudo dnf install ./dist/sushtun-<version>-1.<arch>.rpm
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_deb  # noqa: E402

from xrayui import __version__, paths  # noqa: E402
from xrayui.core import autostart  # noqa: E402

PKG = build_deb.PKG
# Tells the in-app updater this copy belongs to rpm, not dpkg.
RPM_MARKER = ".rpm-package"

SPEC = f"""\
Name:           {PKG}
Version:        @VERSION@
Release:        1
Summary:        Xray TUN client with a desktop UI
License:        MIT
URL:            https://github.com/soroushdeimi/sushTun
AutoReqProv:    no
Requires:       iproute, polkit, libxkbcommon, fontconfig, dbus-libs, mesa-libEGL, mesa-libGL, xcb-util-cursor

%description
Routes all system traffic through an Xray tunnel. Import vless:// links,
subscriptions or QR codes, choose what bypasses the tunnel, and connect.

%install
cp -a @STAGE@/. %{{buildroot}}/

%post
install -d -m 0700 {paths.INSTALLED_DATA_DIR}

%postun
# Same cleanup as the .deb: the autostart polkit rule must not outlive the
# app, but an upgrade ($1 = 1) keeps it.
if [ "$1" = 0 ]; then
    rm -f {autostart.POLKIT_RULE}
fi

%files
@FILES@
"""


def files_section(root: Path) -> str:
    """The install dir as one recursive entry (bundled files have spaces and
    other characters a per-file %files line would trip on), plus the loose
    files elsewhere. System directories like /usr/bin belong to other packages."""
    own = build_deb.PREFIX
    loose = [p for p in sorted(root.rglob("*"))
             if not (p.is_dir() and not p.is_symlink())
             and not ("/" + p.relative_to(root).as_posix()).startswith(own + "/")]
    lines = [own] + ["/" + p.relative_to(root).as_posix() for p in loose]
    return "\n".join(f'"{line}"'.replace("%", "%%") for line in lines)


def spec_text(root: Path, version: str) -> str:
    return (SPEC.replace("@VERSION@", version).replace("@STAGE@", str(root))
            .replace("@FILES@", files_section(root)))


def main() -> int:
    onedir = ROOT / "dist" / PKG
    if not (onedir / PKG).exists():
        print(f"{onedir / PKG} not found; first run:\n"
              "  SUSHTUN_ONEDIR=1 pyinstaller tools/build.spec", file=sys.stderr)
        return 1
    version = __version__
    root = build_deb.stage(onedir, ROOT / "build" / "rpm-root", version, platform.machine())
    shutil.rmtree(root / "DEBIAN")
    (root / build_deb.PREFIX.lstrip("/") / RPM_MARKER).touch()
    top = ROOT / "build" / "rpmbuild"
    shutil.rmtree(top, ignore_errors=True)
    (top / "SPECS").mkdir(parents=True)
    spec = top / "SPECS" / f"{PKG}.spec"
    spec.write_text(spec_text(root, version), encoding="utf-8")
    subprocess.run(["rpmbuild", "-bb", "--define", f"_topdir {top}",
                    "--define", "debug_package %{nil}", "--define", "__strip /bin/true",
                    "--define", "_build_id_links none", str(spec)], check=True)
    out = ROOT / "dist"
    for rpm in (top / "RPMS").rglob("*.rpm"):
        shutil.copy2(rpm, out / rpm.name)
        print(out / rpm.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
