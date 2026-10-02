"""Bundled-core loopback proof: no TUN, host routes, or DNS changes."""
from __future__ import annotations

import json
import socket
import struct
import subprocess
import threading
import time
from contextlib import ExitStack
from http.client import HTTPResponse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from xrayui.core import chains, render
from xrayui.core.profiles import Profile

XRAY = Path(__file__).resolve().parent.parent / "xray"
pytestmark = pytest.mark.skipif(not XRAY.is_file(), reason="bundled xray is missing")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    assert predicate(), "timed out waiting for loopback server"


def receive(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise OSError("connection closed")
        data += chunk
    return data


def socks_request(port, target, *, close=False):
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.settimeout(10)
        sock.sendall(b"\x05\x01\x00")
        if receive(sock, 2) != b"\x05\x00":
            raise OSError("SOCKS authentication failed")
        sock.sendall(b"\x05\x01\x00\x01\x7f\x00\x00\x01" + struct.pack("!H", target))
        reply = receive(sock, 4)
        if reply[1] != 0:
            raise OSError("SOCKS connection failed")
        receive(sock, (4 if reply[3] == 1 else 16) + 2)
        headers = b"Connection: close\r\n" if close else b""
        sock.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n" + headers + b"\r\n")
        with HTTPResponse(sock) as response:
            response.begin()
            assert response.status == 200
            return response.read()


@pytest.fixture
def lab(tmp_path):
    with ExitStack() as stack:
        requests = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                requests.append(self.path)
                body = b"ordered-chain-target"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        stack.callback(http.server_close)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        stack.callback(thread.join, 5)
        stack.callback(http.shutdown)
        processes = []

        def launch(config, port):
            index = len(processes)
            config_path = tmp_path / f"config-{index}.json"
            config_path.write_text(json.dumps(config))
            output = stack.enter_context((tmp_path / f"process-{index}.log").open("w+"))
            proc = subprocess.Popen([str(XRAY), "run", "-c", str(config_path)],
                                    stdout=output, stderr=subprocess.STDOUT)
            processes.append(proc)

            def stop():
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
            stack.callback(stop)

            def ready():
                if proc.poll() is not None:
                    output.seek(0)
                    pytest.fail(output.read())
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        return True
                except OSError:
                    return False
            wait_until(ready)
            return proc

        def chain_client(count, protocol="shadowsocks", network="tcp", udp_target=None,
                         hostnames=False):
            items, servers, logs = [], [], []
            for n in range(count):
                port = free_port()
                profile = Profile(uid=f"hop-{n}", protocol=protocol, network=network,
                                  address="127.0.0.1", port=port,
                                  id="11111111-1111-1111-1111-111111111111",
                                  ss_method="aes-128-gcm", service_name="chain")
                items.append(profile)
                log = tmp_path / f"access-{n}.log"
                logs.append(log)
                if protocol == "shadowsocks":
                    settings = {"method": profile.ss_method, "password": profile.id,
                                "network": "tcp,udp"}
                elif protocol == "trojan":
                    settings = {"clients": [{"password": profile.id}]}
                else:
                    settings = {"clients": [{"id": profile.id}], "decryption": "none"}
                stream = {"network": network}
                if network == "grpc":
                    stream["grpcSettings"] = {"serviceName": "chain"}
                config = {"log": {"access": str(log), "loglevel": "warning"},
                          "inbounds": [{"listen": "127.0.0.1", "port": port,
                                        "protocol": protocol, "settings": settings,
                                        "streamSettings": stream}],
                          "outbounds": [{"protocol": "freedom"}]}
                if hostnames:
                    config["dns"] = {"hosts": {f"hop-{i}.invalid": "127.0.0.1" for i in range(count)},
                                     "servers": [{"address": "127.0.0.1", "port": free_port()}]}
                    config["outbounds"][0]["settings"] = {"domainStrategy": "UseIP"}
                    profile.address = f"hop-{n}.invalid"
                servers.append(launch(config, port))
            chain = chains.Chain(uid="runtime", name="Runtime", hops=[p.uid for p in items])
            port = free_port()
            inbound = {"tag": "test-in", "listen": "127.0.0.1", "port": port,
                       "protocol": "socks", "settings": {"auth": "noauth"}}
            if udp_target:
                inbound.update(protocol="dokodemo-door",
                               settings={"address": "127.0.0.1", "port": udp_target,
                                         "network": "tcp,udp"})
            template = tmp_path / "client-template.json"
            template.write_text(json.dumps({
                "log": {"loglevel": "warning"}, "inbounds": [inbound],
                "outbounds": [{"tag": "proxy", "protocol": "freedom"}]}))
            options = {}
            if hostnames:
                options = {"server_ip": "127.0.0.1", "dns_cfg": {
                    "remote_via_tunnel": True,
                    "raw_override": json.dumps({"servers": [{"address": "127.0.0.1",
                                                              "port": free_port()}]})}}
            config = json.loads(render.build_text(chains.resolve(chain, items), "", template,
                                                  **options))
            launch(config, port)
            return port, servers, logs, items

        yield chain_client, http.server_port, requests, launch


@pytest.mark.parametrize("protocol,network", [
    ("shadowsocks", "tcp"), ("vless", "tcp"), ("vmess", "tcp"), ("trojan", "tcp"),
    ("vless", "grpc"), ("vless", "httpupgrade"),
])
def test_three_hops_reach_target_in_order(lab, protocol, network):
    create, target, requests, _launch = lab
    port, _servers, logs, items = create(3, protocol, network)
    assert b"ordered-chain-target" in socks_request(port, target)
    assert requests == ["/"]
    destinations = [items[1].port, items[2].port, target]
    for log, dest in zip(logs, destinations, strict=True):
        wait_until(lambda log=log, dest=dest: log.exists() and f"127.0.0.1:{dest}" in log.read_text())
        assert "accepted" in log.read_text()


def test_failed_middle_hop_never_reaches_target(lab):
    create, target, requests, _launch = lab
    port, servers, _logs, _items = create(3)
    assert b"ordered-chain-target" in socks_request(port, target)
    servers[1].terminate()
    servers[1].wait(timeout=5)
    count = len(requests)
    try:
        response = socks_request(port, target)
    except OSError:
        response = b""
    assert b"ordered-chain-target" not in response
    time.sleep(0.2)
    assert len(requests) == count


def test_two_hops_reach_target(lab):
    create, target, requests, _launch = lab
    port, _servers, logs, items = create(2)
    assert b"ordered-chain-target" in socks_request(port, target)
    assert requests == ["/"]
    for log, dest in zip(logs, [items[1].port, target], strict=True):
        wait_until(lambda log=log, dest=dest: log.exists() and f"127.0.0.1:{dest}" in log.read_text())


def test_three_hops_relay_udp(lab):
    create, _target, _requests, _launch = lab
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as target:
        target.bind(("127.0.0.1", 0))
        target.settimeout(10)
        port, _servers, logs, items = create(3, udp_target=target.getsockname()[1])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(10)
            client.sendto(b"chain-udp", ("127.0.0.1", port))
            data, peer = target.recvfrom(1024)
            assert data == b"chain-udp"
            target.sendto(b"chain-udp-reply", peer)
            assert client.recvfrom(1024)[0] == b"chain-udp-reply"
        for log, dest in zip(logs, [items[1].port, items[2].port, target.getsockname()[1]], strict=True):
            wait_until(lambda log=log, dest=dest: log.exists() and f"127.0.0.1:{dest}" in log.read_text())


@pytest.mark.parametrize("network", ["tcp", "grpc", "httpupgrade"])
def test_entry_pin_and_remote_hop_hostname_resolution(lab, network):
    create, target, requests, _launch = lab
    port, _servers, logs, _items = create(3, "vless", network, hostnames=True)
    assert b"ordered-chain-target" in socks_request(port, target)
    assert requests == ["/"]
    for log, hostname in zip(logs[:2], ["hop-1.invalid", "hop-2.invalid"], strict=True):
        wait_until(lambda log=log, hostname=hostname: log.exists() and hostname in log.read_text())


@pytest.mark.parametrize("protocol,network", [
    ("shadowsocks", "tcp"), ("vless", "tcp"), ("vmess", "tcp"), ("trojan", "tcp"),
    ("vless", "grpc"), ("vless", "httpupgrade"),
])
def test_immediate_close_responses_are_delivered(lab, protocol, network):
    create, target, requests, _launch = lab
    port, _servers, _logs, _items = create(3, protocol, network)
    for _ in range(5):
        assert b"ordered-chain-target" in socks_request(port, target, close=True)
    assert len(requests) == 5
