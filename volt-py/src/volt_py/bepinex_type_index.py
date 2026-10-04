"""DLL type index for Thunderstore/BepInEx profiles (troubleshooting phase 2,
PLAN.md §14, spec temp/troubleshoot-phase2/SPEC.md §4): which installed
package defines which .NET type. Feeds the log analyzer's attribution
(bepinex_log_analysis: a stack frame's namespace -> the mod that owns it) and
the duplicate-type check (two different packages defining the same
fully-qualified type = copies of the same code, e.g. DawnLib stable beside
DawnLibExperimental).

read_types() is a pure-Python ECMA-335 metadata reader (no dependency): PE
headers -> CLI header -> metadata root -> #~ tables stream + #Strings heap;
reads the TypeDef table (nested types, from NestedClass, are left out: their
names are only meaningful under their outer type), the Assembly name, and
the plugin attributes bepinex_conflicts' byte scan already knows
(BepInPlugin guid/name, so a loader line "Loading [Name 1.0]" or a log
Source tag maps to a package). Method bodies are never read. Native DLLs and
anything odd come back None (skipped, never an error).

scan_package_types() reuses phase 1's file discovery (bepinex_conflicts
_tracked / _on_disk / BLOB_MAX, CODE_DIRS so patchers count too: AsyncLoggers
is a patcher) and is cached by the caller under bepinex_conflicts.scan_key,
like the screen's _scan_cache. Qt-free; nothing here raises.
tools/checks/volt_py_bepinex_log_analysis.py pins it.
"""

import hashlib
import time
from pathlib import Path

from . import bepinex_conflicts as bc
from .applog import log

# ---- ECMA-335 table schema (II.22): columns per table id ----
# "2"/"4" fixed bytes, "s" #Strings idx, "g" #GUID idx, "b" #Blob idx,
# "t:NN" simple index into table NN, "c:NAME" coded index.
_CODED = {  # name: (tag bits, tables; None = unused tag)
    "TypeDefOrRef": (2, (0x02, 0x01, 0x1B)),
    "HasConstant": (2, (0x04, 0x08, 0x17)),
    "HasCustomAttribute": (5, (0x06, 0x04, 0x01, 0x02, 0x08, 0x09, 0x0A, 0x00, 0x0E, 0x17, 0x14, 0x11,
                               0x1A, 0x1B, 0x20, 0x23, 0x26, 0x27, 0x28, 0x2A, 0x2C, 0x2B)),
    "HasFieldMarshal": (1, (0x04, 0x08)),
    "HasDeclSecurity": (2, (0x02, 0x06, 0x20)),
    "MemberRefParent": (3, (0x02, 0x01, 0x1A, 0x06, 0x1B)),
    "HasSemantics": (1, (0x14, 0x17)),
    "MethodDefOrRef": (1, (0x06, 0x0A)),
    "MemberForwarded": (1, (0x04, 0x06)),
    "Implementation": (2, (0x26, 0x23, 0x27)),
    "CustomAttributeType": (3, (None, None, 0x06, 0x0A, None)),
    "ResolutionScope": (2, (0x00, 0x1A, 0x23, 0x01)),
    "TypeOrMethodDef": (1, (0x02, 0x06)),
}
_TABLES = {
    0x00: "2 s g g g", 0x01: "c:ResolutionScope s s", 0x02: "4 s s c:TypeDefOrRef t:04 t:06",
    0x03: "t:04", 0x04: "2 s b", 0x05: "t:06", 0x06: "4 2 2 s b t:08", 0x07: "t:08", 0x08: "2 2 s",
    0x09: "t:02 c:TypeDefOrRef", 0x0A: "c:MemberRefParent s b", 0x0B: "2 c:HasConstant b",
    0x0C: "c:HasCustomAttribute c:CustomAttributeType b", 0x0D: "c:HasFieldMarshal b",
    0x0E: "2 c:HasDeclSecurity b", 0x0F: "2 4 t:02", 0x10: "4 t:04", 0x11: "b", 0x12: "t:02 t:14",
    0x13: "t:14", 0x14: "2 s c:TypeDefOrRef", 0x15: "t:02 t:17", 0x16: "t:17", 0x17: "2 s b",
    0x18: "2 t:06 c:HasSemantics", 0x19: "t:02 c:MethodDefOrRef c:MethodDefOrRef", 0x1A: "s", 0x1B: "b",
    0x1C: "2 c:MemberForwarded s t:1A", 0x1D: "4 t:04", 0x1E: "4 4", 0x1F: "4",
    0x20: "4 2 2 2 2 4 b s s", 0x21: "4", 0x22: "4 4 4", 0x23: "2 2 2 2 4 b s s b", 0x24: "4 t:23",
    0x25: "4 4 4 t:23", 0x26: "4 s b", 0x27: "4 4 s s c:Implementation", 0x28: "4 4 s c:Implementation",
    0x29: "t:02 t:02", 0x2A: "2 2 c:TypeOrMethodDef s", 0x2B: "c:MethodDefOrRef b", 0x2C: "t:2A c:TypeDefOrRef",
}


def _u(data: bytes, pos: int, size: int) -> int:
    return int.from_bytes(data[pos:pos + size], "little") if pos + size <= len(data) else -1


def _cstr(data: bytes, pos: int, limit: int = 1024) -> str:
    end = data.find(b"\x00", pos, pos + limit)
    return data[pos:end if end >= 0 else pos].decode("utf-8", "replace")


def _metadata(data: bytes) -> int | None:
    """File offset of the CLI metadata root, or None (not a managed PE)."""
    if data[:2] != b"MZ":
        return None
    pe = _u(data, 0x3C, 4)
    if pe < 0 or data[pe:pe + 4] != b"PE\x00\x00":
        return None
    nsec, opt_size = _u(data, pe + 6, 2), _u(data, pe + 20, 2)
    opt = pe + 24
    magic = _u(data, opt, 2)
    dirs = opt + (96 if magic == 0x10B else 112 if magic == 0x20B else -10**9)
    if dirs < 0 or _u(data, dirs - 4, 4) < 15:  # NumberOfRvaAndSizes: the CLI header is directory 14
        return None
    secs = [(_u(data, s + 12, 4), max(_u(data, s + 8, 4), _u(data, s + 16, 4)), _u(data, s + 20, 4))
            for s in (opt + opt_size + 40 * i for i in range(nsec))]

    def off(rva: int) -> int | None:
        for va, size, raw in secs:
            if va <= rva < va + size:
                return rva - va + raw
        return None

    cli = off(_u(data, dirs + 14 * 8, 4)) if _u(data, dirs + 14 * 8, 4) > 0 else None
    if cli is None:
        return None
    root = off(_u(data, cli + 8, 4))
    return root if root is not None and _u(data, root, 4) == 0x424A5342 else None


def read_types(data: bytes) -> dict | None:
    """{"assembly": str, "types": ["Ns.Type", ...] (top-level TypeDefs, minus
    <Module>), "plugins": [[guid, name], ...]} for a managed DLL's bytes;
    None for a native DLL or anything the reader doesn't understand. Never
    raises."""
    try:
        root = _metadata(data)
        if root is None:
            return None
        vlen = _u(data, root + 12, 4)
        p = root + 16 + vlen  # Flags (2), Streams (2), then the stream headers
        streams = {}
        count, p = _u(data, p + 2, 2), p + 4
        for _ in range(count):
            o, size, name = _u(data, p, 4), _u(data, p + 4, 4), _cstr(data, p + 8, 32)
            streams[name] = (root + o, size)
            p += 8 + (len(name) + 4) // 4 * 4  # name + NUL, padded to 4
        tbl = streams.get("#~") or streams.get("#-")
        strings = streams.get("#Strings")
        if tbl is None or strings is None:
            return None
        t = tbl[0]
        heap = data[t + 6]
        valid = _u(data, t + 8, 8)
        if valid >> 0x2D:  # a table id this schema doesn't know (obfuscator / newer format)
            return None
        p = t + 24
        rows = {}
        for i in range(64):
            if valid >> i & 1:
                rows[i] = _u(data, p, 4)
                p += 4
        if heap & 0x40:  # #- extra data
            p += 4
        idx = {"s": 4 if heap & 1 else 2, "g": 4 if heap & 2 else 2, "b": 4 if heap & 4 else 2}

        def width(col: str) -> int:
            if col in idx:
                return idx[col]
            if col.startswith("t:"):
                return 2 if rows.get(int(col[2:], 16), 0) < 0x10000 else 4
            if col.startswith("c:"):
                bits, tabs = _CODED[col[2:]]
                most = max(rows.get(x, 0) if x is not None else 0 for x in tabs)
                return 2 if most < 1 << (16 - bits) else 4
            return int(col)

        layout, starts = {}, {}
        for i in sorted(rows):
            cols = [width(c) for c in _TABLES[i].split()]
            layout[i], starts[i] = cols, p
            p += sum(cols) * rows[i]
        sbase = strings[0]

        def string(pos: int, size: int) -> str:
            return _cstr(data, sbase + _u(data, pos, size))

        def cells(table: int, r: int) -> list[int]:  # (offset, width) per column, row r (0-based)
            cols, pos, out = layout[table], starts[table] + sum(layout[table]) * r, []
            for w in cols:
                out.append((pos, w))
                pos += w
            return out

        nested = set()
        for r in range(rows.get(0x29, 0)):
            c = cells(0x29, r)
            nested.add(_u(data, *c[0]))
        types = []
        for r in range(rows.get(0x02, 0)):
            if r + 1 in nested:
                continue
            c = cells(0x02, r)
            name, ns = string(*c[1]), string(*c[2])
            if name != "<Module>":
                types.append(f"{ns}.{name}" if ns else name)
        assembly = string(*cells(0x20, 0)[7]) if rows.get(0x20) else ""
        plugins = []
        if b"BepInPlugin" in data:  # phase 1's attribute-blob scan, keeping the name too
            for m in bc._PROLOG.finditer(data):
                s = bc._ser_strings(data, m.end())
                if s and len(s) == 3 and bc._ID.match(s[0]) and bc._VERSION.match(s[2]) and s[:2] not in plugins:
                    plugins.append(s[:2])
        return {"assembly": assembly, "types": types, "plugins": plugins}
    except Exception:  # odd/obfuscated headers: treat as unreadable
        return None


def scan_package_types(root, entry: dict) -> dict:
    """read_types over `entry`'s tracked DLLs under bepinex_conflicts.CODE_DIRS
    (own or .disabled name): {"dlls": [{"file", "sha1", "assembly", "types",
    "plugins"}], "native": n, "skipped": n}. "skipped" = missing / unreadable
    / over BLOB_MAX (the caller doesn't cache those, like phase 1). Never raises."""
    out = {"dlls": [], "native": 0, "skipped": 0}
    for rel in bc._tracked(entry, bc.CODE_DIRS):
        try:
            path = bc._on_disk(Path(root), rel)
            if path is None or path.stat().st_size > bc.BLOB_MAX:
                out["skipped"] += 1
                continue
            data = path.read_bytes()
        except OSError:
            out["skipped"] += 1
            continue
        info = read_types(data)
        if info is None:
            out["native"] += 1
        else:  # sha1: byte-identical copies in two packages are one copy (shared_types)
            out["dlls"].append({"file": rel, "sha1": hashlib.sha1(data).hexdigest(), **info})
    return out


def scan_profile(root, manifest: dict, cache: dict | None = None) -> dict:
    """scan_package_types for every installed package (framework included),
    reusing `cache` (scan_key -> result; filled in place with clean scans):
    {full_name: scan}. Logs counts and time. Never raises."""
    t0 = time.monotonic()
    cache = {} if cache is None else cache
    out, fresh = {}, 0
    try:
        entries = ([manifest["framework"]] if manifest.get("framework") else []) + manifest["active"] + manifest["inactive"]
        for e in entries:
            key = bc.scan_key(e)
            if key not in cache:
                scan = scan_package_types(root, e)
                fresh += 1
                if scan["skipped"]:
                    out[e["full_name"]] = scan
                    continue
                cache[key] = scan
            out[e["full_name"]] = cache[key]
    except Exception as err:
        log(f"[typeindex] scan failed ({err!r}); partial result")
    dlls = sum(len(s["dlls"]) for s in out.values())
    log(f"[typeindex] {len(out)} packages ({fresh} scanned, {len(out) - fresh} cached): {dlls} managed DLLs, "
        f"{sum(s['native'] for s in out.values())} native, {sum(s['skipped'] for s in out.values())} skipped, "
        f"{(time.monotonic() - t0) * 1000:.0f} ms")
    return out


# ---- lookup ----

# Frames/names from these are never a mod's own code, even when a package
# bundles a copy (a Newtonsoft.Json.dll in some mod's folder).
FRAMEWORK_PREFIXES = ("System.", "Microsoft.", "Mono.", "MonoMod.", "HarmonyLib.", "BepInEx.", "UnityEngine.",
                      "Unity.", "Newtonsoft.", "TMPro.", "Steamworks.", "DunGen.", "On.", "IL.")


def build_index(scans: dict) -> dict:
    """{"types": {type: [(package, dll)]}, "namespaces": {ns: {package: dll}},
    "plugins": {casefolded guid/name/assembly: package}} over `scans`
    (full_name -> scan_package_types result)."""
    types, spaces, plugins = {}, {}, {}
    for pkg, scan in scans.items():
        for d in scan.get("dlls", ()):
            for t in d["types"]:
                types.setdefault(t, []).append((pkg, d["file"]))
                ns = t.rpartition(".")[0]
                while ns:
                    spaces.setdefault(ns, {}).setdefault(pkg, d["file"])
                    ns = ns.rpartition(".")[0]
            for key in [d["assembly"]] + [x for pl in d["plugins"] for x in pl]:
                if key:
                    plugins.setdefault(key.casefold(), set()).add(pkg)
    return {"types": types, "namespaces": spaces, "plugins": plugins}


def attribute(index: dict, name: str) -> list[tuple[str, str]]:
    """[(package, dll)] defining the longest dotted prefix of `name` (a type,
    a namespace or a frame like "LethalCasino.Patches.MenuManagerPatch.StartPatch";
    nested "+" / "/" read as "."): a type match first, else a namespace.
    [] for framework names (FRAMEWORK_PREFIXES) or no match. More than one
    package = ambiguous; the caller decides (the analyzer skips it)."""
    name = (name or "").replace("+", ".").replace("/", ".").replace(":", ".").strip(". ")
    if not name or name.startswith(FRAMEWORK_PREFIXES):
        return []
    parts = name.split(".")
    for n in range(len(parts), 0, -1):
        hit = index["types"].get(".".join(parts[:n]))
        if hit:
            return list(dict.fromkeys(hit))
    for n in range(len(parts), 0, -1):
        hit = index["namespaces"].get(".".join(parts[:n]))
        if hit:
            return list(hit.items())
    return []


# ---- duplicate-type check ----

def _ignored(t: str) -> bool:
    """Types that legitimately appear in many unrelated DLLs: compiler /
    tooling-generated helpers, polyfill attributes, the BepInEx template's
    plugin-info class. Derived from the megadong profile (handoff report)."""
    short = t.rpartition(".")[2]
    return ("<" in t or t.startswith(("System.", "Microsoft.", "__GEN.", "NetcodePatcher."))
            or short in IGNORED_NAMES or short.endswith("Attribute") and "IgnoresAccessChecks" in short)


IGNORED_NAMES = {"MyPluginInfo", "PluginInfo", "ThisAssembly", "IgnoresAccessChecksToAttribute",
                 "EmbeddedAttribute", "RefSafetyRulesAttribute", "NullableAttribute", "NullableContextAttribute",
                 "IsReadOnlyAttribute", "IsUnmanagedAttribute", "IsExternalInit",
                 "$BurstDirectCallInitializer", "UnitySourceGeneratedAssemblyMonoScriptTypes_v1"}  # Unity build output
DUPLICATE_MIN = 20  # see the handoff report: real clashes vs shared helpers on megadong


def shared_types(scans: dict, names: list[str], declared=None) -> list[dict]:
    """[{"packages": [a, b], "shared_types": N, "examples": [...], "flagged": bool,
    "dependency": bool}] for every pair of `names` (full_names, in order) whose
    DLLs define a common non-ignored type, most shared first. A type both get
    from byte-identical DLL files is one copy, not counted (phase 1's rule:
    identical copies are harmless; HookGenPatcher / AutoHookGenPatcher's
    MonoMod.dll). "flagged" =
    N >= DUPLICATE_MIN and neither package declares the other a dependency
    (`declared`: full_name -> iterable of full_names it depends on). Never raises."""
    try:
        owners: dict[str, dict[str, set]] = {}  # type -> {package: {sha1 of the DLLs defining it}}
        for n in names:
            for d in (scans.get(n) or {}).get("dlls", ()):
                for t in d["types"]:
                    if not _ignored(t):
                        owners.setdefault(t, {}).setdefault(n, set()).add(d.get("sha1"))
        pairs: dict[tuple, list[str]] = {}
        for t, pk in owners.items():
            pk = list(pk.items())
            for i, (a, ha) in enumerate(pk):
                for b, hb in pk[i + 1:]:
                    if ha != hb or None in ha:
                        pairs.setdefault((a, b), []).append(t)
        declared = declared or {}
        out = []
        for (a, b), ts in pairs.items():
            dep = b in set(declared.get(a, ())) or a in set(declared.get(b, ()))
            out.append({"packages": [a, b], "shared_types": len(ts), "examples": sorted(ts)[:8],
                        "dependency": dep, "flagged": len(ts) >= DUPLICATE_MIN and not dep})
        out.sort(key=lambda d: -d["shared_types"])
        return out
    except Exception as err:
        log(f"[typeindex] duplicate check failed ({err!r})")
        return []
