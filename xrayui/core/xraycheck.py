"""Validate a set of routing rules with the real Xray binary.

Used by routing rule set import/export (2b) and the geo updater to catch a
config Xray would refuse to start with -- for example a rule referencing a
geosite category a particular geo data source doesn't ship -- before it ever
reaches the live connection. Never touches the live connection's process,
config or log: its own throwaway config lives under state_dir().
"""
from __future__ import annotations

import json
import subprocess

from .. import paths
from . import proc

_CONFIG_NAME = "xraycheck.json"


def check_rules(rules: list[dict], asset_dir=None) -> str | None:
    """None if `rules` validates, else a short reason.

    Runs `xray run -test` against a minimal config: proxy/direct/block
    outbounds (freedom/freedom/blackhole) plus the given routing rules.
    """
    cfg = {
        "log": {"loglevel": "warning"},
        "inbounds": [],
        "outbounds": [
            {"tag": "proxy", "protocol": "freedom"},
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": rules},
    }
    paths.state_dir().mkdir(parents=True, exist_ok=True)
    config_path = paths.state_dir() / _CONFIG_NAME
    config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    env = proc.child_env({"XRAY_LOCATION_ASSET": str(asset_dir or paths.asset_dir())})
    try:
        result = subprocess.run(
            [str(paths.xray_exe()), "run", "-test", "-c", str(config_path)],
            capture_output=True, text=True, env=env, cwd=str(paths.base_dir()),
            timeout=20, creationflags=proc.CREATE_NO_WINDOW, startupinfo=proc._startupinfo(),
        )
    except subprocess.TimeoutExpired:
        return "validation timed out"

    if result.returncode == 0:
        return None
    output = "\n".join(filter(None, (result.stdout, result.stderr)))
    lines = [ln for ln in output.splitlines() if ln.strip()]
    last = lines[-1] if lines else "xray -test failed"
    # Same convention as the speedtest "invalid config" fix: Xray's own
    # error is one long " > "-joined chain of wrapped context; only the
    # last segment is the actual reason.
    return last.rsplit(" > ", 1)[-1].strip()
