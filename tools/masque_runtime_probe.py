"""Local MASQUE data-plane probe (diagnostics only, no runtime dependency).

Reproduces the previous R&D in an isolated temp dir: a local MASQUE TLS
server, a local VLESS/TCP exit, and an HTTP target. No TUN, no OS routes,
no DNS changes. Prints distinct config / handshake / data-plane outcomes.

Run:  python tools/masque_runtime_probe.py [--xray /path/to/xray]
Exit code 0 when the H2 standalone data plane is proven; non-zero otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_XRAY = Path("/Users/soroushdeimi/Desktop/myprojects/SUSHTUN/sushTun/xray")


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _local_ip() -> str:
    """A non-loopback, non-link-local local IPv4. The MASQUE tunnel's
    user-space stack cannot reach 127.0.0.1 (the server never sees the
    forward), so the HTTP target must be bound to a real interface address."""
    import subprocess
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
        addrs = re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out)
    except OSError:
        addrs = []
    for ip in addrs:
        if not ip.startswith("127.") and not ip.startswith("169.254."):
            return ip
    return addrs[0] if addrs else "127.0.0.1"


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


def _gen_cert(work: Path) -> tuple[Path, Path]:
    key = work / "key.pem"
    cert = work / "cert.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "1",
         "-subj", "/CN=masque.local",
         "-addext", "subjectAltName=DNS:masque.local,IP:127.0.0.1"],
        capture_output=True, check=True)
    return cert, key


def _start_xray(xray: Path, cfg: Path, log: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [str(xray), "run", "-c", str(cfg)],
        stdout=log.open("wb"), stderr=subprocess.STDOUT,
        env={**os.environ, "XRAY_LOCATION_ASSET": str(workdir_asset(xray))})


def workdir_asset(xray: Path) -> Path:
    return xray.parent


def _http_target(work: Path, port: int, bind: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", bind],
        cwd=str(work), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _socks5_proxy(port: int) -> subprocess.Popen:
    """A minimal host-side SOCKS5 proxy (no auth, IPv4 only).

    Xray's freedom outbound blackholes the local machine's own IP, so the
    chain's final hop must reach the local HTTP target through a plain socket
    proxy instead of another Xray freedom outbound.
    """
    code = (
        "import socket,threading\n"
        "def pipe(a,b):\n"
        "    try:\n"
        "        while True:\n"
        "            d=a.recv(65536)\n"
        "            if not d:break\n"
        "            b.sendall(d)\n"
        "    except OSError:pass\n"
        "    finally:\n"
        "        try:a.close()\n"
        "        except OSError:pass\n"
        "        try:b.close()\n"
        "        except OSError:pass\n"
        "def rd(c,n):\n"
        "    b=b''\n"
        "    while len(b)<n:b+=c.recv(n-len(b))\n"
        "    return b\n"
        "def handle(c):\n"
        "    rd(c,1)\n"
        "    rd(c,rd(c,1)[0])\n"
        "    c.sendall(b'\\x05\\x00')\n"
        "    rd(c,3)\n"
        "    at=rd(c,1)[0]\n"
        "    ip='.'.join(str(b) for b in rd(c,4)) if at==1 else rd(c,16).decode()\n"
        "    port=int.from_bytes(rd(c,2),'big')\n"
        "    try:\n"
        "        r=socket.create_connection((ip,port),5)\n"
        "        c.sendall(b'\\x05\\x00\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00')\n"
        "        threading.Thread(target=pipe,args=(c,r),daemon=True).start()\n"
        "        threading.Thread(target=pipe,args=(r,c),daemon=True).start()\n"
        "    except OSError:\n"
        "        c.sendall(b'\\x05\\x05\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00')\n"
        "        c.close()\n"
        "s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)\n"
        f"s.bind(('0.0.0.0',{port}));s.listen(16)\n"
        "while True:\n"
        "    c,_=s.accept();threading.Thread(target=handle,args=(c,),daemon=True).start()\n"
    )
    return subprocess.Popen([sys.executable, "-c", code],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _fetch(url: str, socks: str, timeout: float = 15.0) -> tuple[int, int, str]:
    """Return (http_code, size, tail) via a SOCKS5 proxy, or (-1,0,err)."""
    # NO_PROXY/no_proxy in the environment would make curl bypass the proxy
    # for 127.0.0.1 targets, silently turning a tunnel test into a direct hit.
    env = {k: v for k, v in os.environ.items() if k.lower() != "no_proxy"}
    try:
        out = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), "-x", socks, url,
             "-o", "/dev/null", "-w", "%{http_code} %{size_download}"],
            capture_output=True, text=True, timeout=timeout + 5, env=env)
        code, _, size = out.stdout.partition(" ")
        return int(code), int(size), out.stderr.strip()
    except Exception as exc:  # noqa: BLE001 - diagnostic tool
        return -1, 0, str(exc)


def _log_tail(log: Path, n: int = 12) -> str:
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(no log)"
    return "\n".join(lines[-n:])


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
        self.cert, self.key = _gen_cert(self.work)
        self.pin = _cert_sha256(self.cert)

    def _masque_server(self, port: int, alpn: list[str]) -> tuple[Path, Path]:
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
            "outbounds": [{"tag": "direct", "protocol": "freedom"}],
        }
        cfg_path = self.work / f"server-{port}.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        return cfg_path, self.work / f"server-{port}.log"

    def _client(self, port: int, server_port: int, alpn: list[str],
                user: str, password: str, socks_port: int,
                exit_profile: dict | None = None) -> tuple[Path, Path]:
        masque_out = {
            "tag": "proxy", "protocol": "masque",
            "settings": {"address": "127.0.0.1", "port": server_port,
                         "remoteDNS": ["1.1.0.1"]},
            "streamSettings": {
                "method": "masque",
                "masqueSettings": {"user": user, "pass": password},
                "security": "tls",
                "tlsSettings": {"serverName": "masque.local", "alpn": alpn,
                                "pinnedPeerCertSha256": self.pin}},
        }
        outbounds = [masque_out]
        routing_rules = [{"type": "field", "inboundTag": ["socks-in"],
                          "outboundTag": "proxy"}]
        if exit_profile is not None:
            # chain: MASQUE entry -> VLESS/TCP exit
            exit_profile = dict(exit_profile)
            exit_profile["tag"] = "exit"
            exit_profile["streamSettings"] = {
                "network": "tcp", "security": "none",
                "sockopt": {"dialerProxy": "proxy"}}
            outbounds = [exit_profile, masque_out]
            routing_rules = [
                {"type": "field", "inboundTag": ["socks-in"], "outboundTag": "exit"}]
        cfg = {
            "log": {"loglevel": "debug"},
            "inbounds": [{"tag": "socks-in", "listen": "127.0.0.1",
                          "port": socks_port, "protocol": "socks",
                          "settings": {"udp": False}}],
            "outbounds": outbounds,
            "routing": {"rules": routing_rules},
        }
        cfg_path = self.work / f"client-{socks_port}.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        return cfg_path, self.work / f"client-{socks_port}.log"

    def _run(self, name: str, cfg: Path, log: Path, up: float = 6.0) -> bool:
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
    ap.add_argument("--xray", default=str(DEFAULT_XRAY))
    args = ap.parse_args()
    xray = Path(args.xray)

    probe = Probe(xray)
    results: list[tuple[str, bool, str]] = []
    try:
        probe.setup()
        print(f"workdir: {probe.work}")
        print(f"cert pin: {probe.pin}")

        # --- 1. H2 standalone data plane -----------------------------------
        srv_port = _free_port()
        socks_port = _free_port()
        target_port = _free_port()
        target_ip = _local_ip()
        target = _http_target(probe.work, target_port, target_ip)
        probe._procs.append(target)
        time.sleep(0.5)

        s_cfg, s_log = probe._masque_server(srv_port, ["h2"])
        probe._run("server", s_cfg, s_log)
        c_cfg, c_log = probe._client(socks_port, srv_port, ["h2"], "u1", "p1", socks_port)
        probe._run("client", c_cfg, c_log)

        url = f"http://{target_ip}:{target_port}/"
        code, size, err = _fetch(url, f"socks5h://127.0.0.1:{socks_port}")
        ok = code == 200 and size > 0
        results.append(("H2 standalone data plane", ok,
                        f"HTTP {code} size={size}B {err}".strip()))
        print(f"[H2 standalone] HTTP {code} size={size}B  -> {'PASS' if ok else 'FAIL'}")
        if not ok:
            print(_log_tail(c_log))

        # --- 2. wrong credentials must be rejected ------------------------
        socks2 = _free_port()
        c2_cfg, c2_log = probe._client(socks2, srv_port, ["h2"], "u1", "WRONG", socks2)
        probe._run("client-bad", c2_cfg, c2_log)
        code2, size2, err2 = _fetch(url, f"socks5h://127.0.0.1:{socks2}")
        rejected = code2 != 200
        results.append(("H2 wrong credentials rejected", rejected,
                        f"HTTP {code2} size={size2}B {err2}".strip()))
        print(f"[H2 bad creds] HTTP {code2}  -> {'REJECTED (expected)' if rejected else 'ACCEPTED (BUG)'}")
        if not rejected:
            print(_log_tail(c2_log))

        # --- 3. H3 standalone (separate) ----------------------------------
        srv3 = _free_port()
        socks3 = _free_port()
        s3_cfg, s3_log = probe._masque_server(srv3, ["h3"])
        probe._run("server-h3", s3_cfg, s3_log)
        c3_cfg, c3_log = probe._client(socks3, srv3, ["h3"], "u1", "p1", socks3)
        probe._run("client-h3", c3_cfg, c3_log)
        code3, size3, err3 = _fetch(url, f"socks5h://127.0.0.1:{socks3}")
        ok3 = code3 == 200 and size3 > 0
        results.append(("H3 standalone data plane", ok3,
                        f"HTTP {code3} size={size3}B {err3}".strip()))
        print(f"[H3 standalone] HTTP {code3} size={size3}B  -> {'PASS' if ok3 else 'FAIL'}")
        if not ok3:
            print(_log_tail(c3_log))

        # --- 4. chain: MASQUE entry -> VLESS/TCP exit ----------------------
        # A local VLESS/TCP exit server that forwards to the HTTP target.
        # The exit is dialed from inside the tunnel, so it must be reachable at
        # a non-loopback address (the tunnel stack cannot reach 127.0.0.1). Its
        # final hop goes through a host SOCKS5 proxy, because Xray freedom
        # blackholes the local machine's own IP.
        vless_port = _free_port()
        host_socks_port = _free_port()
        host_socks = _socks5_proxy(host_socks_port)
        probe._procs.append(host_socks)
        time.sleep(0.3)
        vless_cfg = {
            "log": {"loglevel": "debug"},
            "inbounds": [{"tag": "vless-in", "listen": "0.0.0.0", "port": vless_port,
                          "protocol": "vless",
                          "settings": {"decryption": "none",
                                       "clients": [{"id": "11111111-1111-1111-1111-111111111111"}]},
                          "streamSettings": {"network": "tcp", "security": "none"}}],
            "outbounds": [{"tag": "direct", "protocol": "socks",
                           "settings": {"servers": [{"address": "127.0.0.1",
                                                     "port": host_socks_port}]}}],
        }
        vless_cfg_path = probe.work / "vless-exit.json"
        vless_cfg_path.write_text(json.dumps(vless_cfg), encoding="utf-8")
        vless_log = probe.work / "vless-exit.log"
        probe._run("vless-exit", vless_cfg_path, vless_log)

        socks4 = _free_port()
        exit_profile = {
            "protocol": "vless",
            "settings": {"vnext": [{"address": target_ip, "port": vless_port,
                                    "users": [{"id": "11111111-1111-1111-1111-111111111111",
                                               "encryption": "none"}]}]},
        }
        c4_cfg, c4_log = probe._client(socks4, srv_port, ["h2"], "u1", "p1", socks4,
                                       exit_profile=exit_profile)
        probe._run("client-chain", c4_cfg, c4_log)
        code4, size4, err4 = _fetch(url, f"socks5h://127.0.0.1:{socks4}")
        ok4 = code4 == 200 and size4 > 0
        results.append(("chain MASQUE->VLESS data plane", ok4,
                        f"HTTP {code4} size={size4}B {err4}".strip()))
        print(f"[chain MASQUE->VLESS] HTTP {code4} size={size4}B  -> {'PASS' if ok4 else 'FAIL'}")
        if not ok4:
            print(_log_tail(c4_log))
            print("--- vless exit log ---")
            print(_log_tail(vless_log))

    finally:
        probe.stop()

    print("\n=== SUMMARY ===")
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    h2_ok = next((ok for n, ok, _ in results if n == "H2 standalone data plane"), False)
    return 0 if h2_ok else 1


if __name__ == "__main__":
    sys.exit(main())
