"""Local MASQUE data-plane probe (diagnostics only, no runtime dependency).

Loopback-only topology in an isolated temp dir:
  - fixed-body HTTP target bound to 127.0.0.1
  - local MASQUE TLS server bound to 127.0.0.1 (h2 and h3)
  - local VLESS/TCP exit bound to 127.0.0.1
  - a host-side SOCKS5 fixture bound to 127.0.0.1 with an EXACT allowlist
    mapping the logical documentation addresses onto loopback:
      203.0.113.10:<target_port> -> 127.0.0.1:<target_port>
      10.0.0.20:<vless_port>     -> 127.0.0.1:<vless_port>
    Every other destination is rejected. The MASQUE server/exit use that
    SOCKS fixture as their outbound, so the userspace stack never dials its
    own 127 address. No TUN, no OS routes, no DNS changes, no LAN listener,
    and no packet is ever sent to a non-loopback address.

The client Xray configs are built by the REAL app code: outbounds.build for
the standalone MASQUE profile and chains.resolve/apply for the H2 chain.
Only the entry's interface placeholder is stripped (documented below), so
this proves the app's own builder/chain path, not a parallel implementation.

Run:  python -m tools.masque_runtime_probe [--xray /path/to/xray]
Exit code 0 only when every required check passes.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from xrayui import paths
from xrayui.core import chains, outbounds
from xrayui.core.profiles import Profile

DOC_TARGET_IP = "203.0.113.10"
# Xray 26.10.31 refuses a plaintext VLESS outbound to a non-private address
# ("vless without TLS ... unless the server address is a private IP"), so the
# logical VLESS address must be RFC1918. It must also sit OUTSIDE the tunnel's
# own subnet (10.0.0.1/24) or the MASQUE userspace stack treats it as local
# and never forwards it. The SOCKS fixture maps it to loopback.
DOC_VLESS_IP = "192.168.20.20"
VLESS_ID = "11111111-1111-1111-1111-111111111111"
EXPECTED_BODY = "MASQUE-LOOPBACK-PROBE-BODY-0123456789"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            time.sleep(0.2)
        finally:
            s.close()
    return False


def _cert_sha256(cert_pem: Path) -> str:
    """pinnedPeerCertSha256: SHA-256 of the DER-encoded certificate."""
    der = subprocess.run(
        ["openssl", "x509", "-in", str(cert_pem), "-outform", "der"],
        capture_output=True, check=True).stdout
    return subprocess.run(
        ["openssl", "dgst", "-sha256", "-binary"],
        input=der, capture_output=True, check=True).stdout.hex()


def _gen_cert(xray: Path, work: Path) -> tuple[Path, Path]:
    """Ephemeral test certificate from the Xray binary itself (test-only)."""
    out = subprocess.run(
        [str(xray), "tls", "cert", "--domain=masque.local", "--expire=24h"],
        capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    cert = work / "cert.pem"
    key = work / "key.pem"
    cert.write_text("\n".join(data["certificate"]) + "\n", encoding="utf-8")
    key.write_text("\n".join(data["key"]) + "\n", encoding="utf-8")
    os.chmod(key, 0o600)
    return cert, key


def _start_xray(xray: Path, cfg: Path, log: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [str(xray), "run", "-c", str(cfg)],
        stdout=log.open("wb"), stderr=subprocess.STDOUT,
        env={**os.environ, "XRAY_LOCATION_ASSET": str(xray.parent)})


def _http_target(port: int, body: bytes) -> subprocess.Popen:
    """Fixed-body HTTP server bound to 127.0.0.1; the body is the exact
    expected response, so a proxy bypass cannot pass."""
    code = (
        "import http.server,socketserver,sys\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        b=sys.argv[1].encode()\n"
        "        self.send_response(200)\n"
        "        self.send_header('Content-Length',str(len(b)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(b)\n"
        "    def log_message(self,*a):\n"
        "        pass\n"
        "socketserver.TCPServer.allow_reuse_address=True\n"
        "socketserver.TCPServer(('127.0.0.1',int(sys.argv[2])),H).serve_forever()\n"
    )
    return subprocess.Popen([sys.executable, "-c", code, body.decode("ascii"), str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _socks5_allowlist(port: int, mapping: dict[tuple[str, int], tuple[str, int]]) -> subprocess.Popen:
    """Host-side SOCKS5 fixture bound to 127.0.0.1.

    Only the exact (address, port) pairs in `mapping` are forwarded; every
    other destination gets a SOCKS5 "host unreachable" reply.
    """
    mapping_json = json.dumps([[a, p, ta, tp] for (a, p), (ta, tp) in mapping.items()])
    code = (
        "import socket,threading,json,sys\n"
        "M={tuple(x[:2]):tuple(x[2:]) for x in json.loads(sys.argv[1])}\n"
        "def rd(c,n):\n"
        "    b=b''\n"
        "    while len(b)<n:\n"
        "        d=c.recv(n-len(b))\n"
        "        if not d:raise OSError\n"
        "        b+=d\n"
        "    return b\n"
        "def pipe(a,b):\n"
        "    try:\n"
        "        while True:\n"
        "            d=a.recv(65536)\n"
        "            if not d:break\n"
        "            b.sendall(d)\n"
        "    except OSError:pass\n"
        "    finally:\n"
        "        for s in (a,b):\n"
        "            try:s.close()\n"
        "            except OSError:pass\n"
        "def handle(c):\n"
        "    try:\n"
        "        rd(c,1)\n"
        "        rd(c,rd(c,1)[0])\n"
        "        c.sendall(b'\\x05\\x00')\n"
        "        rd(c,3)\n"
        "        at=rd(c,1)[0]\n"
        "        if at==1:ip='.'.join(str(b) for b in rd(c,4))\n"
        "        elif at==3:ip=rd(c,rd(c,1)[0]).decode()\n"
        "        else:ip=rd(c,16).decode()\n"
        "        port=int.from_bytes(rd(c,2),'big')\n"
        "        if (ip,port) in M:\n"
        "            ta,tp=M[(ip,port)]\n"
        "            r=socket.create_connection((ta,tp),5)\n"
        "            c.sendall(b'\\x05\\x00\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00')\n"
        "            threading.Thread(target=pipe,args=(c,r),daemon=True).start()\n"
        "            threading.Thread(target=pipe,args=(r,c),daemon=True).start()\n"
        "        else:\n"
        "            c.sendall(b'\\x05\\x04\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00')\n"
        "            c.close()\n"
        "    except OSError:\n"
        "        try:c.close()\n"
        "        except OSError:pass\n"
        "s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)\n"
        "s.bind(('127.0.0.1',int(sys.argv[2])));s.listen(16)\n"
        "while True:\n"
        "    c,_=s.accept();threading.Thread(target=handle,args=(c,),daemon=True).start()\n"
    )
    return subprocess.Popen([sys.executable, "-c", code, mapping_json, str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _fetch(url: str, socks: str, timeout: float = 15.0) -> tuple[int, int, str, str]:
    """Return (http_code, size, body, err) via the SOCKS5 fixture.

    The fetch environment is built explicitly with only the proxy set, so an
    inherited NO_PROXY cannot make curl bypass the proxy and turn a tunnel
    test into a direct hit.
    """
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "http_proxy": socks, "https_proxy": socks}
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), "-x", socks, url,
             "-w", "\n%{http_code} %{size_download}"],
            capture_output=True, text=True, timeout=timeout + 5, env=env)
        body, _, tail = out.stdout.rpartition("\n")
        code, _, size = tail.partition(" ")
        return int(code), int(size), body, out.stderr.strip()
    except Exception as exc:  # noqa: BLE001 - diagnostic tool
        return -1, 0, "", str(exc)


def _socks_unknown_target(socks_port: int) -> bool:
    """A raw SOCKS5 request for a destination outside the fixture allowlist
    must be rejected (reply code 4, host unreachable), on loopback only."""
    s = socket.create_connection(("127.0.0.1", socks_port), timeout=5)
    try:
        s.sendall(b"\x05\x01\x00")
        auth = s.recv(2)  # consume the auth-method reply first
        # VER=05 CMD=01(connect) RSV=00 ATYP=03(domain) LEN=07
        s.sendall(b"\x05\x01\x00\x03\x07" + b"unknown" + (9999).to_bytes(2, "big"))
        reply = s.recv(4)
        return len(auth) == 2 and auth[0] == 5 and len(reply) >= 2 and reply[1] == 4
    finally:
        s.close()


def _log_tail(log: Path, n: int = 12) -> str:
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(no log)"
    return "\n".join(lines[-n:])


def _strip_entry_interface(outbound: dict) -> None:
    # The app builder binds the entry to the physical interface; this
    # loopback fixture dials 127.0.0.1 directly, so only that placeholder
    # is removed. Nothing else of the built outbound is altered.
    sockopt = (outbound.get("streamSettings") or {}).get("sockopt")
    if sockopt and sockopt.get("interface") == "__IFACE__":
        del sockopt["interface"]


def _entry_profile(server_port: int) -> Profile:
    return Profile(name="masque-entry", protocol="masque",
                   address="127.0.0.1", port=server_port,
                   network="masque", security="tls",
                   username="u1", id="p1",
                   masque_http_version="h2",
                   sni="masque.local", pcs="")


def _exit_profile(vless_port: int) -> Profile:
    return Profile(name="vless-exit", protocol="vless",
                   address=DOC_VLESS_IP, port=vless_port,
                   id=VLESS_ID, encryption="none",
                   network="tcp", security="none")


def _client_cfg_standalone(work: Path, socks_port: int, server_port: int,
                           pin: str, http_version: str = "h2",
                           password: str = "p1") -> tuple[Path, Path]:
    """Standalone client built by the real outbounds.build."""
    profile = _entry_profile(server_port)
    profile.masque_http_version = http_version
    profile.id = password
    profile.pcs = pin
    outbound = outbounds.build(profile, "proxy")
    _strip_entry_interface(outbound)
    cfg = {
        "log": {"loglevel": "debug"},
        "inbounds": [{"tag": "socks-in", "listen": "127.0.0.1",
                      "port": socks_port, "protocol": "socks",
                      "settings": {"udp": False}}],
        "outbounds": [outbound],
        "routing": {"rules": [{"type": "field", "inboundTag": ["socks-in"],
                               "outboundTag": "proxy"}]},
    }
    cfg_path = work / f"client-{socks_port}.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg_path, work / f"client-{socks_port}.log"


def _client_cfg_chain(work: Path, socks_port: int, server_port: int,
                      vless_port: int, pin: str) -> tuple[Path, Path]:
    """H2 chain client built by the real chains.resolve/apply."""
    entry = _entry_profile(server_port)
    entry.pcs = pin
    entry.uid = "masque-entry-uid"
    exit_ = _exit_profile(vless_port)
    exit_.uid = "vless-exit-uid"
    plan = chains.resolve(chains.Chain(uid="probe-chain", name="probe",
                                       hops=[entry.uid, exit_.uid]),
                          {entry.uid: entry, exit_.uid: exit_})
    template = {
        "log": {"loglevel": "debug"},
        "inbounds": [],
        "outbounds": [{"tag": "proxy"}],
        "routing": {"rules": []},
    }
    chains.apply(template, plan)
    entry_out = next(o for o in template["outbounds"] if o.get("tag") == "chain-1")
    _strip_entry_interface(entry_out)
    template["inbounds"].append({"tag": "socks-in", "listen": "127.0.0.1",
                                 "port": socks_port, "protocol": "socks",
                                 "settings": {"udp": False}})
    template["routing"]["rules"].append(
        {"type": "field", "inboundTag": ["socks-in"], "outboundTag": "proxy"})
    cfg_path = work / f"client-{socks_port}.json"
    cfg_path.write_text(json.dumps(template), encoding="utf-8")
    return cfg_path, work / f"client-{socks_port}.log"


class Probe:
    def __init__(self, xray: Path) -> None:
        self.xray = xray
        self.work = Path(tempfile.mkdtemp(prefix="masque-probe-"))
        self._procs: list[subprocess.Popen] = []
        self.cert = self.key = None
        self.pin = ""

    def setup(self) -> None:
        if not self.xray.exists():
            raise SystemExit(f"Xray binary not found: {self.xray}")
        self.cert, self.key = _gen_cert(self.xray, self.work)
        self.pin = _cert_sha256(self.cert)

    def _masque_server(self, port: int, alpn: list[str], socks_port: int) -> tuple[Path, Path]:
        cfg = {
            "log": {"loglevel": "debug"},
            "inbounds": [{
                "tag": "masque-in", "listen": "127.0.0.1", "port": port,
                "protocol": "masque",
                "settings": {"users": [{"email": "u1", "pass": "p1", "level": 0}],
                             "address": ["10.0.0.1/24"], "mtu": 1280},
                "streamSettings": {
                    "method": "masque", "security": "tls",
                    "tlsSettings": {"serverName": "masque.local", "alpn": alpn,
                                    "certificates": [{"certificateFile": str(self.cert),
                                                       "keyFile": str(self.key)}]}}}],
            # The tunnel's userspace stack cannot dial 127.0.0.1, so the
            # server's exit goes through the host allowlist SOCKS fixture.
            "outbounds": [{"tag": "direct", "protocol": "socks",
                           "settings": {"servers": [{"address": "127.0.0.1",
                                                     "port": socks_port}]}}],
        }
        cfg_path = self.work / f"server-{port}.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        return cfg_path, self.work / f"server-{port}.log"

    def _run(self, cfg: Path, log: Path, up: float = 6.0) -> bool:
        proc = _start_xray(self.xray, cfg, log)
        self._procs.append(proc)
        return _wait_port(self._port_of(cfg), up)

    def _port_of(self, cfg: Path) -> int:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        for ib in data.get("inbounds", []):
            if ib.get("protocol") == "socks":
                return ib["port"]
        return data["inbounds"][0]["port"]

    def stop(self) -> None:
        for p in self._procs:
            try:
                p.terminate()
            except Exception:
                pass
        for p in self._procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xray", default=None,
                    help="path to the Xray binary (default: the bundled one)")
    args = ap.parse_args()
    xray = Path(args.xray) if args.xray else paths.xray_exe()

    probe = Probe(xray)
    results: list[tuple[str, bool, str]] = []
    try:
        probe.setup()
        print(f"workdir: {probe.work}")
        print(f"cert pin: {probe.pin}")

        target_port = _free_port()
        vless_port = _free_port()
        host_socks_port = _free_port()
        # Exact allowlist: the logical addresses map onto the loopback
        # fixtures; nothing else is forwarded.
        host_socks = _socks5_allowlist(host_socks_port, {
            (DOC_TARGET_IP, target_port): ("127.0.0.1", target_port),
            (DOC_VLESS_IP, vless_port): ("127.0.0.1", vless_port),
        })
        probe._procs.append(host_socks)
        target = _http_target(target_port, EXPECTED_BODY.encode("ascii"))
        probe._procs.append(target)
        time.sleep(0.5)

        # --- 0. fixture allowlist rejects unknown targets ------------------
        unknown = _socks_unknown_target(host_socks_port)
        results.append(("fixture rejects unknown target", unknown,
                        "SOCKS5 reply code 4 (host unreachable)"))
        print(f"[fixture allowlist] unknown target rejected={unknown}  -> {'PASS' if unknown else 'FAIL'}")

        # --- 1. H2 standalone data plane -----------------------------------
        srv_port = _free_port()
        socks_port = _free_port()
        s_cfg, s_log = probe._masque_server(srv_port, ["h2"], host_socks_port)
        probe._run(s_cfg, s_log)
        c_cfg, c_log = _client_cfg_standalone(probe.work, socks_port, srv_port, probe.pin)
        probe._run(c_cfg, c_log)

        url = f"http://{DOC_TARGET_IP}:{target_port}/"
        code, size, fetched, err = _fetch(url, f"socks5h://127.0.0.1:{socks_port}")
        ok = code == 200 and fetched == EXPECTED_BODY
        results.append(("H2 standalone data plane", ok,
                        f"HTTP {code} size={size}B exact-body={fetched == EXPECTED_BODY} {err}".strip()))
        print(f"[H2 standalone] HTTP {code} size={size}B exact-body={fetched == EXPECTED_BODY}  -> {'PASS' if ok else 'FAIL'}")
        if not ok:
            print(_log_tail(c_log))

        # --- 2. wrong credentials must be rejected ------------------------
        socks2 = _free_port()
        c2_cfg, c2_log = _client_cfg_standalone(probe.work, socks2, srv_port, probe.pin,
                                                password="WRONG")
        probe._run(c2_cfg, c2_log)
        code2, size2, fetched2, err2 = _fetch(url, f"socks5h://127.0.0.1:{socks2}")
        rejected = code2 != 200 and fetched2 != EXPECTED_BODY
        results.append(("H2 wrong credentials rejected", rejected,
                        f"HTTP {code2} size={size2}B {err2}".strip()))
        print(f"[H2 bad creds] HTTP {code2}  -> {'REJECTED (expected)' if rejected else 'ACCEPTED (BUG)'}")
        if not rejected:
            print(_log_tail(c2_log))

        # --- 3. wrong cert pin must be rejected ---------------------------
        socks3 = _free_port()
        c3_cfg, c3_log = _client_cfg_standalone(probe.work, socks3, srv_port,
                                                "0" * 64)
        probe._run(c3_cfg, c3_log)
        code3, size3, fetched3, err3 = _fetch(url, f"socks5h://127.0.0.1:{socks3}")
        pin_rejected = code3 != 200 and fetched3 != EXPECTED_BODY
        results.append(("H2 wrong cert pin rejected", pin_rejected,
                        f"HTTP {code3} size={size3}B {err3}".strip()))
        print(f"[H2 bad pin] HTTP {code3}  -> {'REJECTED (expected)' if pin_rejected else 'ACCEPTED (BUG)'}")
        if not pin_rejected:
            print(_log_tail(c3_log))

        # --- 4. H3 standalone (separate) ----------------------------------
        srv4 = _free_port()
        socks4 = _free_port()
        s4_cfg, s4_log = probe._masque_server(srv4, ["h3"], host_socks_port)
        probe._run(s4_cfg, s4_log)
        c4_cfg, c4_log = _client_cfg_standalone(probe.work, socks4, srv4, probe.pin,
                                                http_version="h3")
        probe._run(c4_cfg, c4_log)
        code4, size4, fetched4, err4 = _fetch(url, f"socks5h://127.0.0.1:{socks4}")
        ok4 = code4 == 200 and fetched4 == EXPECTED_BODY
        results.append(("H3 standalone data plane", ok4,
                        f"HTTP {code4} size={size4}B exact-body={fetched4 == EXPECTED_BODY} {err4}".strip()))
        print(f"[H3 standalone] HTTP {code4} size={size4}B exact-body={fetched4 == EXPECTED_BODY}  -> {'PASS' if ok4 else 'FAIL'}")
        if not ok4:
            print(_log_tail(c4_log))

        # --- 5. chain: MASQUE(H2) entry -> VLESS/TCP exit ------------------
        # The exit is dialed from inside the tunnel at the logical address,
        # which the host SOCKS fixture maps to the loopback VLESS server; the
        # exit's own forward goes through the same fixture to the loopback
        # HTTP target.
        vless_cfg = {
            "log": {"loglevel": "debug"},
            "inbounds": [{"tag": "vless-in", "listen": "127.0.0.1", "port": vless_port,
                          "protocol": "vless",
                          "settings": {"decryption": "none",
                                       "clients": [{"id": VLESS_ID}]},
                          "streamSettings": {"network": "tcp", "security": "none"}}],
            "outbounds": [{"tag": "direct", "protocol": "socks",
                           "settings": {"servers": [{"address": "127.0.0.1",
                                                     "port": host_socks_port}]}}],
        }
        vless_cfg_path = probe.work / "vless-exit.json"
        vless_cfg_path.write_text(json.dumps(vless_cfg), encoding="utf-8")
        vless_log = probe.work / "vless-exit.log"
        probe._run(vless_cfg_path, vless_log)

        socks5 = _free_port()
        c5_cfg, c5_log = _client_cfg_chain(probe.work, socks5, srv_port, vless_port,
                                           probe.pin)
        probe._run(c5_cfg, c5_log)
        code5, size5, fetched5, err5 = _fetch(url, f"socks5h://127.0.0.1:{socks5}")
        ok5 = code5 == 200 and fetched5 == EXPECTED_BODY
        results.append(("chain MASQUE->VLESS data plane", ok5,
                        f"HTTP {code5} size={size5}B exact-body={fetched5 == EXPECTED_BODY} {err5}".strip()))
        print(f"[chain MASQUE->VLESS] HTTP {code5} size={size5}B exact-body={fetched5 == EXPECTED_BODY}  -> {'PASS' if ok5 else 'FAIL'}")
        if not ok5:
            print(_log_tail(c5_log))
            print("--- vless exit log ---")
            print(_log_tail(vless_log))

        # --- 6. stopping the entry fails closed ----------------------------
        # Kill the MASQUE entry server; a new request through the chain
        # client must not reach the target at all.
        for p in probe._procs:
            if p.poll() is None and any(f"server-{srv_port}" in str(a) for a in p.args):
                p.terminate()
                try:
                    p.wait(timeout=5)
                except Exception:
                    p.kill()
                break
        time.sleep(1.0)
        code6, size6, fetched6, err6 = _fetch(url, f"socks5h://127.0.0.1:{socks5}")
        closed = code6 != 200 and fetched6 != EXPECTED_BODY
        results.append(("stopping entry fails closed", closed,
                        f"HTTP {code6} size={size6}B {err6}".strip()))
        print(f"[entry stopped] HTTP {code6}  -> {'FAIL-CLOSED (expected)' if closed else 'LEAKED (BUG)'}")
        if not closed:
            print(_log_tail(c5_log))

    finally:
        probe.stop()

    print("\n=== SUMMARY ===")
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    failed = [n for n, ok, _ in results if not ok]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
