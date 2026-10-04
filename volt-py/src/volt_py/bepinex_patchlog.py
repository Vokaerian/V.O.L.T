"""Record patch details (troubleshooting phase 2, dispatch C, 0.6.39; PLAN.md
§14, spec temp/troubleshoot-phase2/SPEC.md §6): one launch of a profile with
HarmonyX's Info log channel on, and the patch table read from that launch's
log. Qt-free; every function logs `[patchlog] ...` and never raises (except
where its docstring says otherwise).

Per profile, VOLT-side state beside loadorder.json (the profile's own folder,
like the manifest; copied with "Copy to new", deleted with the profile, never
inside BepInEx/ so the game and Edit Config never see it):

- `patch-details.json` (tiny, read whenever a window opens):
  {"record": bool (the switch), "pending": {original, written, at} | null,
  "last": {at, targets} | null}.
- `patch-table.json` (compact, written once per recording; read by the
  Troubleshoot window's worker): {schema, recorded_at, log_mtime, targets,
  patch_lines, harmony_ids, unmatched, disagree, methods: {target: [[kind
  index, package or "", patch method], ...]}}. The Debug IL dumps are never
  read (bepinex_log_analysis drops them).

The cfg edit is crash-safe (spec §6): at a Modded launch with the switch on,
`arm` saves the pending restore (the user's own `[Harmony.Logger]
LogChannels` value, None when the key is absent, and the value VOLT writes)
BEFORE it edits BepInEx.cfg, and writes value + Info (never IL / Debug /
All). `restore` puts the user's value back only while the file still holds
what VOLT wrote (compared as a set of channels: BepInEx re-saves flags in its
own order); a value the user changed meanwhile is left alone and logged. The
screen calls restore when the watched game exits, and on opening for every
profile still pending (VOLT closed / crashed / the game killed). A missing
BepInEx.cfg (the profile never launched: BepInEx writes it on its first run)
is never created or touched; the switch stays on for the next launch. An
absent key restores to BepInEx's own default "Warn, Error": that is what an
absent key means, and BepInEx writes the key back on its next save anyway.
"""

import json
import os
import time
from pathlib import Path

from . import bepinex_config as bcfg
from . import bepinex_log_analysis as la
from . import bepinex_type_index as ti
from .applog import log
from .bepinex_install import BEPINEX_DIR, CONFIG_FOLDER
from .fsutil import read_json, write_json, write_text_atomic

STATE_FILE = "patch-details.json"
TABLE_FILE = "patch-table.json"
SCHEMA_VERSION = 1
CFG_NAME = "BepInEx.cfg"
SECTION, KEY = "Harmony.Logger", "LogChannels"
DEFAULT_CHANNELS = "Warn, Error"  # BepInEx's default (the cfg's own "# Default value:" line)
INFO = "Info"
KINDS = ("prefix", "postfix", "transpiler", "finalizer")
UNMATCHED = "?"  # a patch whose class VOLT couldn't match to one installed mod: "?<top namespace>"
LOG_SLACK_S = 5  # the log must be written after the launch (minus this) to be the recording


def cfg_path(tree) -> Path:
    return Path(tree) / BEPINEX_DIR / CONFIG_FOLDER / CFG_NAME


def log_path(tree) -> Path:
    return Path(tree) / BEPINEX_DIR / "LogOutput.log"


# ---- state ----

def load_state(tree) -> dict:
    """{"record": bool, "pending": dict | None, "last": dict | None}; defaults
    when the file is missing or unreadable."""
    raw = {}
    try:
        raw = read_json(Path(tree) / STATE_FILE)
    except FileNotFoundError:
        pass
    except Exception as err:
        log(f"[patchlog] {Path(tree) / STATE_FILE} unreadable, using defaults: {err!r}")
    raw = raw if isinstance(raw, dict) else {}
    pending, last = raw.get("pending"), raw.get("last")
    return {"record": bool(raw.get("record")), "pending": pending if isinstance(pending, dict) else None,
            "last": last if isinstance(last, dict) else None}


def _save(tree, state: dict) -> None:
    """Raises OSError."""
    write_json(Path(tree) / STATE_FILE, {"schema_version": SCHEMA_VERSION, **state})


def set_record(tree, on: bool, why: str = "") -> bool:
    """The switch (Settings checkbox / the Troubleshoot window's button).
    False when it couldn't be saved."""
    state = load_state(tree)
    try:
        _save(tree, {**state, "record": bool(on)})
    except OSError as err:
        log(f"[patchlog] record switch {'on' if on else 'off'} for {tree} FAILED to save: {err!r}")
        return False
    log(f"[patchlog] record switch {'on' if on else 'off'} for {tree}{f' ({why})' if why else ''}")
    return True


def pending_trees(load_orders_root) -> list[Path]:
    """Every profile folder whose state still has a pending restore."""
    out = []
    try:
        for e in os.scandir(load_orders_root):
            if e.is_dir() and (Path(e.path) / STATE_FILE).is_file() and load_state(e.path)["pending"]:
                out.append(Path(e.path))
    except OSError:
        pass
    return out


# ---- the cfg edit ----

def _tokens(value: str | None) -> set[str]:
    return {t.strip().casefold() for t in (value or "").split(",") if t.strip()}


def with_info(value: str | None) -> str | None:
    """`value` (None = absent = the default) with Info added; None when it
    already logs Info (Info or All). "None" is dropped (None + Info = Info)."""
    toks = [t.strip() for t in (DEFAULT_CHANNELS if value is None else value).split(",") if t.strip()]
    low = {t.casefold() for t in toks}
    if "info" in low or "all" in low:
        return None
    return ", ".join([t for t in toks if t.casefold() != "none"] + [INFO])


def _find(doc):
    return next((e for e in doc.entries if e.section.strip() == SECTION and e.key == KEY), None)


def _insert(text: str, value: str) -> str:
    """`text` with `LogChannels = value` added under [Harmony.Logger] (the
    section appended when missing)."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    for i, raw in enumerate(lines):
        if raw.strip() == f"[{SECTION}]":
            head = raw if raw.endswith("\n") else raw + nl
            return "".join(lines[:i]) + head + f"{KEY} = {value}{nl}" + "".join(lines[i + 1:])
    sep = "" if not text or text.endswith("\n") else nl
    return f"{text}{sep}{nl}[{SECTION}]{nl}{KEY} = {value}{nl}"


def arm(tree, now: float | None = None) -> str:
    """At a Modded launch of this profile: "off" (switch off), "pending" (a
    restore is still pending: the cfg is left as is and this launch records
    with it), "no-cfg" (BepInEx.cfg doesn't exist yet: not touched, the switch
    stays on), "already-info" (the user's own value logs Info: nothing to
    change, still recorded), "armed" (Info added), "error"."""
    path = cfg_path(tree)
    try:
        state = load_state(tree)
        if not state["record"]:
            return "off"
        if state["pending"]:
            log(f"[patchlog] arm: a restore is still pending for {path}; left as is, this launch records with it")
            return "pending"
        if not path.is_file():
            log(f"[patchlog] arm: {path} doesn't exist yet (BepInEx writes it on the profile's first launch): "
                "not recording this launch, the switch stays on")
            return "no-cfg"
        text = bcfg.read_text(path)
        if text is None:
            log(f"[patchlog] arm: {path} isn't UTF-8 text; not touched, not recording")
            return "error"
        doc = bcfg.parse(text)
        entry = _find(doc)
        original = entry.value if entry else None
        new = with_info(original)
        pending = {"original": original, "written": original if new is None else new,
                   "at": time.time() if now is None else now}
        _save(tree, {**state, "pending": pending})  # BEFORE the edit: a crash from here on still restores
        if new is None:
            log(f"[patchlog] arm: {path}: LogChannels {original!r} already logs Info; nothing changed, recording")
            return "already-info"
        if entry is not None:
            doc.set_value(entry, new)
            out = doc.render()
        else:
            out = _insert(text, new)
        try:
            bcfg.write_text(path, out)
        except OSError as err:
            _save(tree, {**state, "pending": None})
            log(f"[patchlog] arm: writing {path} FAILED, not recording: {err!r}")
            return "error"
        log(f"[patchlog] arm: {path}: LogChannels {original if original is not None else '(absent)'!r} -> {new!r} "
            "(pending restore saved first)")
        return "armed"
    except Exception as err:
        log(f"[patchlog] arm: {path} FAILED, not recording: {err!r}")
        return "error"


def restore(tree) -> str:
    """Puts the user's own LogChannels back after a recording run: "nothing"
    (no pending restore), "restored", "unchanged" (VOLT changed nothing),
    "user-changed" (the value isn't VOLT's any more: left alone), "no-cfg"
    (the file is gone), "error" (kept pending, retried next time)."""
    state = load_state(tree)
    p = state["pending"]
    if not p:
        return "nothing"
    path = cfg_path(tree)
    original, written = p.get("original"), p.get("written")
    target = original if original is not None else DEFAULT_CHANNELS
    current = None
    try:
        if written == original:
            outcome = "unchanged"
        elif not path.is_file():
            outcome = "no-cfg"
        else:
            text = bcfg.read_text(path)
            doc = bcfg.parse(text or "")
            entry = _find(doc) if text is not None else None
            current = entry.value if entry else None
            if entry is None or _tokens(current) != _tokens(written):
                outcome = "user-changed"
            else:
                if current != target:
                    doc.set_value(entry, target)
                    bcfg.write_text(path, doc.render())
                outcome = "restored"
        _save(tree, {**load_state(tree), "pending": None})
    except Exception as err:
        log(f"[patchlog] restore {path} FAILED, kept pending (retried next time): {err!r}")
        return "error"
    if outcome == "restored":
        log(f"[patchlog] restore {path}: LogChannels {current!r} -> {target!r}"
            + (" (the key was absent before: BepInEx's default)" if original is None else ""))
    elif outcome == "user-changed":
        log(f"[patchlog] restore {path}: LogChannels is now {current!r}, not VOLT's {written!r}: "
            f"changed by someone else meanwhile, left as is (the value before recording was {original!r})")
    else:
        log(f"[patchlog] restore {path}: {outcome}")
    return outcome


# ---- the patch table ----

def _class_of(method: str) -> str:
    """"static void Ns.Cls::M(args)" -> "Ns.Cls" (the return type may hold spaces)."""
    return method.split("::", 1)[0].rsplit(" ", 1)[-1]


def _enabled(manifest: dict) -> list[str]:
    entries = ([manifest["framework"]] if manifest.get("framework") else []) + list(manifest.get("active") or [])
    return [e["full_name"] for e in entries if e.get("enabled", True)]


def _harmony_match(owners: list[tuple[list[str], str]], cls: str) -> str | None:
    """The package of the Harmony instance whose starting class shares the
    longest dotted prefix (at least the top namespace) with `cls`; None when
    nothing matches or the best match is ambiguous."""
    parts = cls.replace("+", ".").split(".")
    best, hits = 0, set()
    for start, pkg in owners:
        n = 0
        while n < min(len(parts), len(start)) and parts[n] == start[n]:
            n += 1
        if n > best:
            best, hits = n, {pkg}
        elif n == best and n:
            hits.add(pkg)
    return next(iter(hits)) if best and len(hits) == 1 else None


def build_table(run: dict, scans: dict | None, manifest: dict | None, recorded_at: float | None = None) -> dict:
    """The stored table from a parse_log run. Each patch method's package:
    PRIMARY the type index (its class is defined in that package's DLL;
    enabled packages only); FALLBACK the Harmony instance whose `### Started
    from` class shares its namespace, mapped to a package by the instance's
    plugins/<Package>/ or patchers/<Package>/ location. When both answer and
    differ, the type index wins (the class's own DLL is the stronger proof: a
    library's Harmony instance can apply another mod's patch) and the
    disagreement is counted + logged. Neither -> "?<top namespace>"."""
    t0 = time.monotonic()
    enabled = set(_enabled(manifest)) if manifest else set()
    index = ti.build_index({n: s for n, s in (scans or {}).items() if n in enabled}) if scans else None
    owners = []  # (the namespace of the class each Harmony instance started from, its package)
    for h in run.get("harmony_ids") or []:
        if h.get("started_from") and h.get("folder") in enabled:
            parts = _class_of(h["started_from"]).replace("+", ".").split(".")
            owners.append((parts[:-1] or parts, h["folder"]))
    cache: dict[str, str] = {}
    unmatched = disagree = lines = 0
    examples: list[str] = []

    def package(cls: str) -> str:
        nonlocal unmatched, disagree
        if cls in cache:
            return cache[cls]
        hits = [p for p, _ in ti.attribute(index, cls)] if index else []
        hits = list(dict.fromkeys(hits))
        harmony = _harmony_match(owners, cls)
        if len(hits) == 1:
            pkg = hits[0]
            if harmony and harmony != pkg:
                disagree += 1
                if len(examples) < 5:
                    examples.append(f"{cls}: type index {pkg}, Harmony id {harmony}")
        elif hits and harmony in hits:
            pkg = harmony  # two packages define the class (a duplicate pair): the Harmony location decides
        elif harmony and not hits:
            pkg = harmony
        else:
            pkg = UNMATCHED + cls.split(".", 1)[0]
            unmatched += 1
        cache[cls] = pkg
        return pkg

    methods = {}
    for target, kinds in (run.get("patches") or {}).items():
        rows = []
        for k, kind in enumerate(KINDS):
            for m in kinds.get(kind) or ():
                rows.append([k, package(_class_of(m)), m])
                lines += 1
        methods[target] = rows
    table = {"schema": SCHEMA_VERSION, "recorded_at": recorded_at, "log_mtime": run.get("mtime"),
             "targets": len(methods), "patch_lines": lines, "harmony_ids": len(run.get("harmony_ids") or []),
             "unmatched": unmatched, "disagree": disagree, "methods": methods}
    log(f"[patchlog] table: {len(methods)} targets, {lines} patch lines, {len(cache)} patch classes "
        f"({unmatched} not matched to a mod, {disagree} where the type index and the Harmony id disagree"
        + (f": {'; '.join(examples)}" if examples else "") + f"), {(time.monotonic() - t0) * 1000:.0f} ms")
    return table


def record_table(tree, manifest: dict | None, cache: dict | None = None, started: float | None = None) -> dict:
    """Worker job after a recording run: parse the profile's log, build and
    store the table. {"ok": bool, "targets": n, "reason": str, "cache": the
    type cache, "ms"}. ok False (nothing stored) when the log predates the
    launch or holds no patch details. Never raises."""
    t0 = time.monotonic()
    cache = {} if cache is None else cache
    try:
        run = la.parse_log(log_path(tree))
        reason = ""
        if run["mtime"] is None:
            reason = "no log file"
        elif started is not None and run["mtime"] < started - LOG_SLACK_S:
            reason = "the log is older than the launch (the game didn't start?)"
        elif not run["patch_blocks"]:
            reason = "the log has no patch details (the game closed before the mods loaded?)"
        if reason:
            log(f"[patchlog] nothing recorded for {tree}: {reason}")
            return {"ok": False, "targets": 0, "reason": reason, "cache": cache,
                    "ms": round((time.monotonic() - t0) * 1000)}
        scans = ti.scan_profile(tree, manifest, cache) if manifest else {}
        table = build_table(run, scans, manifest, started if started is not None else run["mtime"])
        text = json.dumps(table, ensure_ascii=False, separators=(",", ":"))
        write_text_atomic(Path(tree) / TABLE_FILE, text)
        finish_state(tree, {"ok": True, "targets": table["targets"]}, started)  # here, not in the done-handler:
        # it must happen even when the screen is left before the job ends (its result is then dropped)
        ms = round((time.monotonic() - t0) * 1000)
        log(f"[patchlog] recorded {Path(tree) / TABLE_FILE}: "
            f"{table['targets']} game methods, {len(text) // 1024} KB, {ms} ms (log {run['lines']} lines, "
            f"{run['patch_blocks']} patch blocks, {len(run['harmony_ids'])} Harmony ids)")
        return {"ok": True, "targets": table["targets"], "reason": "", "cache": cache, "ms": ms}
    except Exception as err:
        log(f"[patchlog] recording {tree} FAILED: {err!r}")
        return {"ok": False, "targets": 0, "reason": repr(err), "cache": cache,
                "ms": round((time.monotonic() - t0) * 1000)}


def finish_state(tree, result: dict, started: float | None) -> None:
    """After record_table: a stored table switches the switch off and keeps
    {at, targets} for the status line; nothing stored keeps the switch on (the
    next launch tries again)."""
    if not result.get("ok"):
        return
    state = load_state(tree)
    try:
        _save(tree, {**state, "record": False, "last": {"at": started, "targets": result["targets"]}})
        log(f"[patchlog] record switch off for {tree} (recorded {result['targets']} game methods)")
    except OSError as err:
        log(f"[patchlog] saving the recording's state for {tree} FAILED: {err!r}")


def load_table(tree) -> dict | None:
    """The stored table, or None (none / unreadable / another schema)."""
    try:
        table = read_json(Path(tree) / TABLE_FILE)
    except FileNotFoundError:
        return None
    except Exception as err:
        log(f"[patchlog] {Path(tree) / TABLE_FILE} unreadable: {err!r}")
        return None
    if not isinstance(table, dict) or table.get("schema") != SCHEMA_VERSION or not isinstance(table.get("methods"), dict):
        return None
    return table


def targets_view(table: dict) -> dict:
    """{target: {package: {kind: n}}} (set_patch_table's shape)."""
    out = {}
    for target, rows in table["methods"].items():
        by = out[target] = {}
        for k, pkg, _m in rows:
            d = by.setdefault(pkg, {})
            d[KINDS[k]] = d.get(KINDS[k], 0) + 1
    return out


def technical_text(target: str, rows: list) -> str:
    """The Harmony Info lines for one target, as the log printed them."""
    counts = [sum(1 for r in rows if r[0] == k) for k in range(4)]
    out = [f"Patching {target} with {counts[0]} prefixes, {counts[1]} postfixes, {counts[2]} transpilers, "
           f"{counts[3]} finalizers"]
    plural = ("prefixes", "postfixes", "transpilers", "finalizers")
    for k in range(4):
        if counts[k]:
            out.append(f"{counts[k]} {plural[k]}:")
            out += [f"* {m}" for kk, _p, m in rows if kk == k]
    return "\n".join(out)


# ---- words (Settings > Troubleshooting > PATCH DETAILS; the Troubleshoot window) ----

RECORD_LABEL = "Record patch details on next launch"
RECORD_TOOLTIP = ("Adds Info to [Harmony.Logger] LogChannels in this profile's BepInEx.cfg for one launch, then puts "
                  "your own setting back.")
SETTINGS_NOTE = ("For the \"Mod contents\" tab in Troubleshoot: the next launch of {profile} writes down which game "
                 "code each mod changes. VOLT turns this off again after that one launch. That launch's log file is "
                 "about 5 times bigger than usual.")
NO_PROFILE = "Open a profile first."


def when_text(epoch) -> str | None:
    from .bepinex_troubleshoot import _clock  # "19:23 today" (the Log analyzer's LAST RUN clock)
    return _clock(epoch) if isinstance(epoch, (int, float)) else None


def status_line(state: dict, profile: str, *, cfg_exists: bool, running: bool) -> str:
    """The muted line under the Settings checkbox."""
    last = state.get("last") or {}
    when = when_text(last.get("at"))
    n = last.get("targets", 0)
    recorded = f"Last recorded {when}: {n:,} changed game method{'' if n == 1 else 's'}." if when else ""
    if running:
        return f"Unavailable while the game is running. {recorded}".strip()
    if state.get("record") or state.get("pending"):
        if not cfg_exists:
            return (f"{profile} hasn't been launched yet, so its mod loader has no settings file to switch this on "
                    f"in. Launch it once with \"Modded\"; the launch after that records.")
        return f"Will record on the next launch of {profile}, then switch itself off."
    if recorded:
        return f"{recorded} Tick it again after you change mods, for a fresh list."
    return f"Not recorded yet for {profile}."


def note_text(table: dict) -> str:
    """The patch table's footnote in the Troubleshoot window."""
    when = when_text(table.get("recorded_at"))
    return f"From the recorded launch at {when}." if when else "From the recorded launch."
