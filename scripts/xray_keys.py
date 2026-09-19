"""List every JSON key an Xray-core release accepts, from its Go source.

    python scripts/xray_keys.py extract -o docs/xray/keys.json SRC [SRC ...]
    (SRC may be PATH@LABEL for an untagged checkout, e.g. ~/xray-core@main-dcdfc57)
    python scripts/xray_keys.py report > docs/xray/COVERAGE.md

`extract` takes one Xray-core source tree per release (oldest first, each a
checkout of a `vX.Y.Z` tag; the tag is read from core/core.go). It reads the
json struct tags under infra/conf and follows every field into the struct it
decodes to. A few fields are decoded at run time instead (`settings` picks a
struct by `protocol`, finalmask picks one by `type`); SLOTS below names those,
and extraction stops with an error when a release adds a raw field SLOTS does
not know, so a newer core can never be half-read in silence.

`report` joins keys.json with the hand-kept classification.toml and
status.toml (same folder) into the coverage report. tests/test_xray_coverage.py
fails when a client-side key has no status entry or the report is stale.
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

DOCS = Path(__file__).resolve().parent.parent / "docs" / "xray"
BASELINE = "26.3.27"  # the core sushTun bundles (scripts/fetch_deps.py)

_TYPE_RE = re.compile(r"^\s*type\s+(\w+)\s+(struct\s*\{|.+)$")
_VAR_STRUCT_RE = re.compile(r"^\s*var\s+(\w+)\s+struct\s*\{")
_FIELD_RE = re.compile(r"^\s*(\w+)\s+([^`]+?)\s*`([^`]*)`")
_EMBED_RE = re.compile(r"^\s*\*?([\w.]+)\s*(//.*)?$")
_JSON_TAG_RE = re.compile(r'json:"([^"]*)"')
_LOADER_RE = re.compile(r"^\s*(?:var\s+)?(\w+)\s*=\s*NewJSONConfigLoader\(")
# A creator's id is a string literal or a named constant (router_strategy.go).
_CREATOR_RE = re.compile(r'(?:"([\w.-]+)"|(\w+)):\s*func\(\)\s*interface\{\}\s*\{\s*'
                         r'return\s+(?:new\((\w+)\)|&(\w+)\{)')
_CONST_RE = re.compile(r'^\s*(\w+)\s+(?:string\s+)?=\s*"([^"]*)"')
_PACKAGE_RE = re.compile(r"^package\s+(\w+)")
_RECV_RE = re.compile(r"^func\s+\(\w+\s+\*?(\w+)\)")
_REMOVED_RE = re.compile(r"Print(RemovedFeatureError|DeprecatedFeatureWarning)")

# Fields whose JSON is decoded at run time. (struct, key) -> how to go on:
#   ("loader", VAR, DISCRIMINATOR)  a ConfigCreatorCache picked by a sibling key
#   ("types", [TYPE, ...])          decoded into these structs, merged
#   ("leaf", REASON)                a scalar or free value; nothing below it
# A value may instead be a dict keyed by the parent's JSON key, for a struct
# used under two keys with different meanings (finalmask tcp vs udp).
SLOTS: dict[tuple[str, str], object] = {
    ("InboundDetourConfig", "settings"): ("loader", "inboundConfigLoader", "protocol"),
    ("OutboundDetourConfig", "settings"): ("loader", "outboundConfigLoader", "protocol"),
    ("StrategyConfig", "settings"): ("loader", "strategyConfigLoader", "type"),
    ("RouterConfig", "rules"): ("types", ["RawFieldRule"]),
    ("TCPConfig", "header"): ("loader", "tcpHeaderLoader", "type"),
    ("KCPConfig", "header"): ("leaf", "removed: the core rejects it (finalmask replaces it)"),
    ("SplitHTTPConfig", "extra"): ("types", ["SplitHTTPConfig"]),
    ("Mask", "settings"): {"tcp": ("loader", "tcpmaskLoader", "type"),
                           "udp": ("loader", "udpmaskLoader", "type")},
    ("BlackholeConfig", "response"): ("loader", "configLoader", "type"),
    ("VLessOutboundVnext", "users"): ("types", ["protocol.User", "vless.Account"]),
    ("VLessInboundConfig", "clients"): ("types", ["protocol.User", "vless.Account"]),
    ("VMessOutboundTarget", "users"): ("types", ["protocol.User", "VMessAccount"]),
    ("VMessInboundConfig", "clients"): ("types", ["protocol.User", "VMessAccount"]),
    ("VLessInboundConfig", "users"): ("types", ["protocol.User", "vless.Account"]),
    ("VMessInboundConfig", "users"): ("types", ["protocol.User", "VMessAccount"]),
    ("OutboundDetourConfig", "proxySettings"): ("leaf", "removed: the core rejects it "
                                                "(use sockopt.dialerProxy)"),
    ("HTTPRemoteConfig", "users"): ("types", ["protocol.User", "HTTPAccount"]),
    ("SocksRemoteConfig", "users"): ("types", ["protocol.User", "SocksAccount"]),
    ("Config", "transport"): ("leaf", "removed: global transport is rejected by the core"),
    ("XDriveConfig", "template"): ("leaf", "a free-form request template, kept as a string"),
    ("Xdns", "domain"): ("leaf", "kept only so the core can reject it (use `domains`)"),
    # One pool object or a list of them (FakeDNSConfig.UnmarshalJSON).
    ("Config", "fakeDns"): ("types", ["FakeDNSPoolElementConfig"]),
}
# Leaves by (struct, key) for raw fields that hold a scalar or a free value.
RAW_LEAVES = {"dest", "target", "ports", "packet", "bytes"}
# protocol.User's `account` is filled from the same JSON object by the account
# struct listed next to it in SLOTS, never read as its own key.
SKIP = {("User", "account")}
_SCALARS = {"string", "bool", "byte", "rune", "int", "int8", "int16", "int32", "int64",
            "uint", "uint8", "uint16", "uint32", "uint64", "float32", "float64",
            "interface{}", "any", "json.RawMessage"}


@dataclass
class Field:
    key: str
    gotype: str
    name: str
    line: str
    embedded: bool = False


@dataclass
class Struct:
    name: str
    package: str
    fields: list[Field] = field(default_factory=list)


class Source:
    """The structs, aliases and loaders of one Xray-core checkout."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.structs: dict[str, Struct] = {}
        self.aliases: dict[str, str] = {}
        self.loaders: dict[str, dict[str, str]] = {}
        # (struct, Go field) -> "rejected" (an error) or "deprecated" (a warning)
        self.removed: dict[tuple[str, str], str] = {}
        self.consts: dict[str, str] = {}
        for path in sorted((root / "infra" / "conf").rglob("*.go")):
            if not path.name.endswith("_test.go"):
                self._parse(path, qualify=False)
        self._pkg_cache: dict[str, list[Path]] = {}

    def version(self) -> str:
        text = (self.root / "core" / "core.go").read_text()
        x, y, z = (re.search(rf"Version_{c}\s+byte\s*=\s*(\d+)", text).group(1)
                   for c in "xyz")
        return f"{x}.{y}.{z}"

    def _parse(self, path: Path, qualify: bool) -> None:
        lines = path.read_text(encoding="utf-8").splitlines()
        package = next((m.group(1) for ln in lines if (m := _PACKAGE_RE.match(ln))), "")
        rel = path.relative_to(self.root).as_posix()
        i, recv, loader = 0, "", None
        while i < len(lines):
            ln = lines[i]
            if m := _RECV_RE.match(ln):
                recv = m.group(1)
            if (m := _LOADER_RE.match(ln)) and not qualify:
                loader = m.group(1)
                self.loaders[loader] = {}
            if (m := _CONST_RE.match(ln)) and not qualify:
                self.consts.setdefault(m.group(1), m.group(2))
            if loader and (m := _CREATOR_RE.search(ln)):
                ident = m.group(1) or self.consts.get(m.group(2), m.group(2))
                self.loaders[loader][ident] = m.group(3) or m.group(4)
            if loader and ln.strip() in ("})", "}))", ")"):
                loader = None
            if (m := _REMOVED_RE.search(ln)) and recv and not qualify:
                what = "rejected" if m.group(1) == "RemovedFeatureError" else "deprecated"
                # Only fields in the `if`s that guard the call, nested ones too
                # (26.3.27 wraps allowInsecure's removal in a date check); a plain
                # assignment a line above (config.X = c.X) is not what it rejects.
                guard = " ".join(b for b in lines[max(0, i - 3):i]
                                 if re.match(r"\s*(\}\s*else\s+)?if\b", b))
                for fname in re.findall(r"\bc\.(\w+)\b", guard):
                    self.removed.setdefault((recv, fname), what)
            m = _TYPE_RE.match(ln) or _VAR_STRUCT_RE.match(ln)
            if m and (ln.rstrip().endswith("{") and "struct" in ln):
                name = m.group(1)
                if qualify:
                    name = f"{package}.{name}"
                st, i = self._struct_body(lines, i + 1, name, package, rel)
                self.structs.setdefault(name, st)
                continue
            if m and m.group(2) and "struct" not in m.group(2):
                alias = f"{package}.{m.group(1)}" if qualify else m.group(1)
                self.aliases.setdefault(alias, m.group(2).split("//")[0].strip())
            i += 1

    def _struct_body(self, lines, i, name, package, rel):
        st = Struct(name, package)
        depth = 1
        while i < len(lines) and depth:
            ln = lines[i]
            depth += ln.count("{") - ln.count("}")
            if depth == 1:
                if m := _FIELD_RE.match(ln):
                    fname, gotype, tags = m.groups()
                    tag = _JSON_TAG_RE.search(tags)
                    key = tag.group(1).split(",")[0] if tag else fname
                    if key != "-" and fname[0].isupper():
                        st.fields.append(Field(key, gotype.strip(), fname, f"{rel}:{i + 1}"))
                elif m := _EMBED_RE.match(ln):
                    st.fields.append(Field("", m.group(1), m.group(1), f"{rel}:{i + 1}",
                                           embedded=True))
            i += 1
        return st, i

    def qualified(self, name: str) -> Struct | None:
        """A struct from another package, e.g. vless.Account, parsed on demand."""
        if name in self.structs:
            return self.structs[name]
        pkg, _, short = name.partition(".")
        if pkg not in self._pkg_cache:
            self._pkg_cache[pkg] = [
                p for p in self.root.rglob("*.go")
                if not p.name.endswith("_test.go") and "infra/conf" not in p.as_posix()
                and re.search(rf"^package {pkg}\s*$",
                              p.read_text(encoding="utf-8", errors="ignore"), re.M)]
        for path in self._pkg_cache[pkg]:
            if re.search(rf"^type {short} struct", path.read_text(encoding="utf-8"), re.M):
                self._parse(path, qualify=True)
                return self.structs.get(name)
        return None


def _base(gotype: str, package: str = "") -> tuple[str, str]:
    """(container marks, bare type) for a Go type: '*[]*Foo' -> ('[]', 'Foo')."""
    t, marks = gotype.strip(), ""
    while True:
        if t.startswith("*"):
            t = t[1:]
        elif t.startswith("[]"):
            t, marks = t[2:], marks + "[]"
        elif t.startswith("map["):
            t, marks = t[t.index("]") + 1:], marks + "{}"
        else:
            break
    if package and "." not in t and t not in _SCALARS and t[:1].isupper():
        t = f"{package}.{t}"
    return marks, t


class Extractor:
    def __init__(self, src: Source) -> None:
        self.src = src
        self.keys: dict[str, dict] = {}
        self.unknown: list[str] = []

    def run(self) -> dict[str, dict]:
        self._walk("Config", "", (), parent_key="")
        if self.unknown:
            raise SystemExit("raw fields SLOTS does not cover:\n  "
                             + "\n  ".join(sorted(set(self.unknown))))
        return self.keys

    def _struct(self, name: str) -> Struct | None:
        return self.src.structs.get(name) or (self.src.qualified(name) if "." in name else None)

    def _resolve(self, name: str, package: str) -> tuple[str, str]:
        """Follow `type X []Y` style aliases to the struct they hold."""
        marks = ""
        seen = set()
        while name not in seen:
            seen.add(name)
            alias = self.src.aliases.get(name) or self.src.aliases.get(name.split(".")[-1])
            if alias is None or name in self.src.structs:
                break
            more, name = _base(alias, package)
            marks += more
        return marks, name

    def _walk(self, struct: str, path: str, stack: tuple, parent_key: str) -> None:
        st = self._struct(struct)
        if st is None or struct in stack:
            return
        stack += (struct,)
        # Types inside infra/conf are unqualified; anything else keeps its package.
        pkg = "" if st.package == "conf" else st.package
        short = struct.split(".")[-1]
        for f in st.fields:
            if f.embedded:
                self._walk(_base(f.gotype, pkg)[1], path, stack, parent_key)
                continue
            if (short, f.key) in SKIP:
                continue
            key_path = f"{path}.{f.key}" if path else f.key
            marks, bare = _base(f.gotype, pkg)
            more, bare = self._resolve(bare, pkg)
            marks += more
            entry = {"type": f.gotype, "source": f.line}
            if (short, f.name) in self.src.removed:
                entry["state"] = self.src.removed[(short, f.name)]
            slot = SLOTS.get((short, f.key))
            if isinstance(slot, dict):
                slot = slot.get(parent_key)
            target = self._struct(bare)
            if slot and bare != "json.RawMessage" and target and target.fields:
                # A release turned this raw field into a plain struct (blackhole's
                # `response` in 26.9.8): read its tags like any other.
                slot = None
            self.keys[key_path] = entry
            child = key_path + marks.replace("{}", ".*")
            nested = slot[1] if slot and slot[0] == "types" else [bare]
            if any(n in stack for n in nested):
                # xhttp's `extra` is a whole xhttpSettings again and its
                # `downloadSettings` a whole streamSettings: point at the first
                # copy instead of listing every key twice.
                entry["same_as"] = next(n for n in nested if n in stack)
                continue
            if slot:
                self._slot(slot, child, stack, f.key)
            elif bare == "json.RawMessage":
                if f.key not in RAW_LEAVES:
                    self.unknown.append(f"{short}.{f.key} ({f.line})")
            elif target:
                self._walk(bare, child, stack, f.key)

    def _slot(self, slot: tuple, path: str, stack: tuple, key: str) -> None:
        kind = slot[0]
        if kind == "loader":
            _, var, disc = slot
            if var not in self.src.loaders:
                raise SystemExit(f"loader {var} is gone: update SLOTS")
            for ident, typ in sorted(self.src.loaders[var].items()):
                self._walk(typ, f"{path}{{{disc}={ident}}}", stack, key)
        elif kind == "types":
            for typ in slot[1]:
                self._walk(typ, path, stack, key)


def extract(roots: list[str]) -> dict:
    releases, per_release = [], {}
    for root in roots:
        # A checkout past its last tag still reports that tag's version, so
        # an untagged one is named on the command line: PATH@LABEL.
        path, _, label = root.partition("@")
        src = Source(Path(path).expanduser())
        ver = label or src.version()
        releases.append(ver)
        per_release[ver] = Extractor(src).run()
    out: dict[str, dict] = {}
    for ver in releases:
        for key, info in per_release[ver].items():
            entry = out.setdefault(key, {"first": ver, "removed": None, **info})
            entry.update({k: v for k, v in info.items() if k in ("type", "source")})
            for state in ("deprecated", "rejected"):
                if info.get("state") == state and not entry.get(f"{state}_in"):
                    entry[f"{state}_in"] = ver
            entry.pop("state", None)
    for key, entry in out.items():
        present = [v for v in releases if key in per_release[v]]
        gone = [v for v in releases if releases.index(v) > releases.index(present[-1])]
        entry["removed"] = gone[0] if gone else None
        if releases[0] in present and releases[0] != BASELINE:
            entry["first"] = f"<={releases[0]}"
        elif releases[0] in present:
            entry["first"] = f"<={BASELINE}"
    return {"releases": releases, "keys": dict(sorted(out.items()))}


# -- configs sushTun writes -----------------------------------------------------------
def unknown_paths(cfg: dict, keys: dict[str, dict]) -> list[str]:
    """Keys in a rendered config that the baseline core does not know.

    Go's decoder drops unknown keys without a word and matches names
    case-insensitively, so a typo or a key from another core version
    silently does nothing. Paths use the keys.json form: `[]` for lists,
    `{protocol=...}` / `{type=...}` where a sibling picks the struct.
    """
    known = {k.lower() for k, e in keys.items() if in_baseline(e)}
    prefixes = {k[:i] for k in known for i in range(len(k)) if k[i] in ".[{"}
    out: list[str] = []

    def walk(obj, path: str) -> None:
        if isinstance(obj, list):
            for item in obj:
                walk(item, f"{path}[]")
            return
        if not isinstance(obj, dict):
            return
        pick = obj.get("protocol") or obj.get("type")
        for key, val in obj.items():
            sub = f"{path}.{key}" if path else key
            low = sub.lower()
            if key == "settings" and pick:
                sub, low = f"{sub}{{{'protocol' if 'protocol' in obj else 'type'}={pick}}}", \
                    f"{low}{{{'protocol' if 'protocol' in obj else 'type'}={str(pick).lower()}}}"
            if key == "header" and isinstance(val, dict) and val.get("type"):
                sub, low = f"{sub}{{type={val['type']}}}", f"{low}{{type={val['type']}}}"
                val = {k: v for k, v in val.items() if k != "type"}
            if low not in known and low not in prefixes:
                if f"{path.lower()}.*" in prefixes or f"{path.lower()}.*" in known:
                    walk(val, f"{path}.*")  # a map: policy.levels.<n>
                    return
                out.append(sub)
                continue
            if low in prefixes:
                walk(val, sub)

    walk(cfg, "")
    return sorted(set(out))


# -- report ---------------------------------------------------------------------
def load_rules() -> tuple[list[dict], list[dict]]:
    cls = tomllib.loads((DOCS / "classification.toml").read_text(encoding="utf-8"))["rule"]
    status = tomllib.loads((DOCS / "status.toml").read_text(encoding="utf-8"))["key"]
    return cls, status


def glob(pattern: str) -> re.Pattern:
    """`*` matches anything (dots and brackets too); everything else is literal,
    because key paths are full of `[]` and `{}` that fnmatch would misread."""
    return re.compile("^" + ".*".join(re.escape(part) for part in pattern.split("*")) + "$")


def first_match(key: str, entries: list[dict]) -> dict | None:
    """First entry whose pattern matches wins, so specific entries go first."""
    for e in entries:
        pats = e.setdefault("_re", [glob(p) for p in e["match"]])
        if any(r.match(key) for r in pats):
            return e
    return None


def classify(key: str, rules: list[dict]) -> dict | None:
    return first_match(key, rules)


def status_of(key: str, statuses: list[dict]) -> dict | None:
    return first_match(key, statuses)


def in_baseline(entry: dict) -> bool:
    """Accepted by the bundled core, whatever later releases do with it."""
    return entry["first"].startswith("<=")


def section(key: str) -> str:
    return re.split(r"[.\[{]", key, maxsplit=1)[0]


class Row(NamedTuple):
    key: str
    entry: dict
    cls: str
    rule: dict | None
    status: dict | None
    gated: bool


def report(data: dict) -> str:
    rules, statuses = load_rules()
    keys = data["keys"]
    rows, totals = [], {}
    for key, e in keys.items():
        c = classify(key, rules)
        cls = c["class"] if c else "UNCLASSIFIED"
        st = status_of(key, statuses) if cls == "client" else None
        gated = not in_baseline(e)
        sec = section(key)
        t = totals.setdefault(sec, {"client": 0, "server": 0, "internal": 0, "gated": 0,
                                    "full": 0, "partial": 0, "imported": 0, "alias": 0,
                                    "unsupported": 0, "UNCLASSIFIED": 0})
        if gated:
            t["gated"] += 1
        else:
            t[cls] = t.get(cls, 0) + 1
            if st:
                t[st["status"]] += 1
        rows.append(Row(key, e, cls, c, st, gated))
    out = ["# Xray-core key coverage", "",
           f"Generated by `scripts/xray_keys.py report` from docs/xray/keys.json "
           f"(releases {', '.join(data['releases'])}), classification.toml and "
           "status.toml. Do not edit by hand.", "",
           f"Baseline core: **{BASELINE}** (bundled). Keys that first appear later are "
           "listed as gated: recorded, not implemented.", "",
           "## Totals per section (baseline keys)", "",
           "| section | client | full | partial | raw JSON only | alias | unsupported | "
           "server-only | internal | gated (newer core) |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    cols = ("client", "full", "partial", "imported", "alias", "unsupported", "server",
            "internal", "gated")
    for sec, t in sorted(totals.items()):
        out.append(f"| {sec} | " + " | ".join(str(t[c]) for c in cols) + " |")
    s = {c: sum(t[c] for t in totals.values()) for c in cols}
    out.append("| **all** | " + " | ".join(f"**{s[c]}**" for c in cols) + " |")
    covered = s["full"] + s["partial"] + s["imported"] + s["alias"]
    out += ["", f"Client-side keys reachable today: **{covered} of {s['client']}** "
            f"({covered * 100 // max(s['client'], 1)}%); with a form (full or partial): "
            f"**{s['full'] + s['partial']}** ({(s['full'] + s['partial']) * 100 // max(s['client'], 1)}%)."]
    out += ["", "## Client-side keys", "",
            "Status: full = a form or setting writes it (and links carry it where they "
            "have a field); partial = written with a fixed value or in one form only; "
            "imported = only inside raw JSON the user pastes or imports; alias = "
            "another spelling of a covered key; unsupported = never written. "
            "Link: yes = parsed and written back; import = parsed only; no = links "
            "have no field; n/a = not a per-server setting.", "",
            "| key | since | status | link | subscription | where | note |",
            "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r.cls != "client" or r.gated:
            continue
        st = r.status or {}
        out.append(f"| `{r.key}` | {r.entry['first']} | {st.get('status', '**MISSING**')} | "
                   f"{st.get('link', '')} | {st.get('sub', '')} | "
                   f"{', '.join(st.get('files', []))} | {st.get('note', '')} |")
    out += ["", "## Server-only and internal keys", "",
            "| key | class | reason |", "|---|---|---|"]
    for r in rows:
        if r.cls in ("server", "internal") and not r.gated:
            out.append(f"| `{r.key}` | {r.cls} | {r.rule['reason']} |")
    out += ["", "## Gated: newer than the bundled core", "",
            "| key | first | removed | class |", "|---|---|---|---|"]
    for r in rows:
        if r.gated:
            out.append(f"| `{r.key}` | {r.entry['first']} | {r.entry['removed'] or ''} | "
                       f"{r.cls} |")
    rejected = [(k, e) for k, e in keys.items() if e.get("rejected_in")]
    if rejected:
        out += ["", "## Accepted by the parser but rejected when built", "",
                "Present in the struct tags, but the core refuses (or warns on) the key "
                "(`PrintRemovedFeatureError` / `PrintDeprecatedFeatureWarning` next to it).",
                "", "| key | since |", "|---|---|"]
        out += [f"| `{k}` | {e['rejected_in']} |" for k, e in rejected]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if argv[:1] == ["extract"]:
        args, out = argv[1:], None
        if args[:1] == ["-o"]:
            out, args = Path(args[1]), args[2:]
        if not args:
            print(__doc__)
            return 2
        # Built fully before anything is written: a shell `>` would empty
        # keys.json when a newer core stops the run.
        text = json.dumps(extract(args), indent=1) + "\n"
        if out:
            out.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
        return 0
    if argv[:1] == ["report"]:
        data = json.loads((DOCS / "keys.json").read_text(encoding="utf-8"))
        sys.stdout.write(report(data))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
