"""Log analyzer for Thunderstore/BepInEx profiles (troubleshooting phase 2,
PLAN.md §14, spec temp/troubleshoot-phase2/SPEC.md §2-§3): reads a profile's
BepInEx/LogOutput.log and explains what went wrong, advice only.

parse_log() streams the file line by line (never the whole text in one
string; a line longer than MAX_LINE is cut into pieces) and keeps only what
the analyzer needs: Warning/Error/Fatal messages grouped by a normalised
signature as they arrive (count, first/last line, one example with its stack
frames), the header (BepInEx / game / Unity versions, the plugin load order,
"Chainloader startup complete"), and the Harmony Info-channel structures for
the patch table (dispatch C): "### Harmony id=" + "### Started from ...,
location <dll>" pairs and "Patching <target> with N prefixes, ..." blocks with
their "* <patch method>" lines. Debug "Generated patch" IL dumps and every
other line are skipped without being stored.

analyze() turns the groups into findings: a failure FAMILY (ADVICE: plain
words per pattern, never per mod pair; no fix actions), the mod(s) involved
(ATTRIBUTION, strongest evidence first: a BepInEx loader message naming the
plugin > the plugin being loaded when the chainloader failed > the log Source
tag > the first stack frame whose namespace resolves through the DLL type
index (bepinex_type_index) > nobody; never a guess), a confidence
(certain / likely / possible + why), and root-cause-first ordering (the
earliest error = likely root cause; errors within CASCADE_S after it that
share a mod / namespace, or follow a load failure, are listed under it).
Known-noise messages (HARMLESS) are kept but marked harmless. The duplicate-
type check (two different enabled packages defining the same types) is added
as a profile finding when DLL scans are given.

Pure functions, Qt-free, nothing here raises (logged + empty/partial result).
tools/checks/volt_py_bepinex_log_analysis.py pins it; tools/analyze_log.py is
a tiny CLI over it.
"""

import hashlib
import os
import re
import time
from pathlib import Path

from . import bepinex_type_index as ti
from .applog import log

MAX_LINE = 64 * 1024  # longer physical lines are read in pieces (binary junk, IL dumps)
MAX_FRAMES = 40  # stack lines kept per example
MAX_GROUPS = 2000  # distinct signatures kept; more are counted in "dropped"
MAX_LINE_NUMBERS = 200  # line numbers kept per group
CASCADE_S = 3.0  # seconds after the root cause an error still counts as following it

# AsyncLoggers' optional prefix: "HH:mm:ss.fffffff" in UTC with the machine culture's time separator (":" on
# en-US, "." on e.g. Norwegian), or a bare number for its TickCount / FrameCount / Counter types (no time).
_LINE = re.compile(r"^(?:\[(?:(\d\d)[.:](\d\d)[.:](\d\d)\.(\d+)|-?\d+)\] )?"
                   r"\[(Info|Error|Warning|Debug|Message|Fatal) *:([^\]]*)\] ?(.*)$")
_HARMONY_ID = re.compile(r"^### Harmony id=(.*?), version=.*?(?:, location=(.*?))?(?:, env/clr.*)?$")
_STARTED = re.compile(r"^### Started from (.*), location (.*)$")
_PATCHING = re.compile(r"^Patching (.+) with (\d+) prefixes, (\d+) postfixes, (\d+) transpilers, (\d+) finalizers$")
_PATCH_KIND = re.compile(r"^\d+ (prefix|postfix|transpiler|finalizer)(?:es|s)?:$")
_LOADING = re.compile(r"^Loading \[(.+) ([\w.+-]+)\]$")
_HEADER = re.compile(r"^BepInEx ([\w.]+) - (.+?) \(")
_PKG_FOLDER = re.compile(r"[\\/](?:plugins|patchers)[\\/]([^\\/]+)[\\/]", re.I)
_EXC = re.compile(r"(?:^|Error: |Rethrow as )((?:[\w.]+\.)?(\w+(?:Exception|Error)))\b")

# ---- signature normalisation ----
_NORM = [
    (re.compile(r"[A-Za-z]:[\\/][^\s'\",;)]*"), "<path>"),
    (re.compile(r"(?<![\w.<])/(?:[\w.\-]+/)+[\w.\-]*"), "<path>"),
    (re.compile(r"<[0-9a-f]{16,}>"), "<hash>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<guid>"),
    (re.compile(r"0x[0-9a-fA-F]+|\b[0-9a-f]{8}\b"), "#"),
    (re.compile(r"\?-?\d+"), ""),
    (re.compile(r"\b\d+(\.\d+)*\b"), "#"),
    (re.compile(r"\s+"), " "),
]
_FRAME_NAME = re.compile(r"^\s*(?:at\s+)?([^\s(]+)")
_WRAPPER = ("DMD<", "Trampoline<", "Hook<", "(wrapper")


def _norm(text: str) -> str:
    for rx, rep in _NORM:
        text = rx.sub(rep, text)
    return text.strip()[:300]


def frame_name(line: str) -> str | None:
    """The dotted Type.Method of one stack line (Mono "Ns.T.M (args) (at f:1)",
    Unity "Ns.T:M(args)", .NET "  at Ns.T.M () [0x0] in <h>:IL_0"), or None
    for wrapper / dynamic-method / non-frame lines."""
    s = line.strip()
    if not s or s.startswith(("(wrapper", "Rethrow as", "Stack trace", "---")):
        return None
    m = _FRAME_NAME.match(s)
    if not m or any(w in m.group(1) for w in _WRAPPER):
        return None
    name = re.sub(r"\[[^\]]*\]", "", m.group(1)).replace("::", ".").replace(":", ".")
    return name if "." in name else None


def _is_framework(name: str) -> bool:
    return name.startswith(ti.FRAMEWORK_PREFIXES)


# ---- parse ----

def _new_run(path) -> dict:
    return {"path": str(path) if path else None, "mtime": None, "lines": 0, "first_ts": None, "last_ts": None,
            "duration_s": None, "header": {"bepinex": None, "game": None, "unity": None, "plugins_to_load": None,
                                            "chainloader_done_ts": None, "chainloader_done_line": None},
            "load_order": [], "groups": [], "dropped": 0, "harmony_ids": [], "patches": {},
            "patch_blocks": 0, "patch_lines": 0, "ms": 0, "error": None}


def parse_log(source) -> dict:
    """Run dict (module docstring) from a log path or an iterable of lines.
    Keys: path, mtime, lines, first_ts / last_ts ("hh:mm:ss" UTC: AsyncLoggers'
    clock; None without it) + duration_s, header {bepinex, game, unity, plugins_to_load,
    chainloader_done_ts, chainloader_done_line (the ts is None in a log without
    timestamps, BepInEx's default; the line number says it happened)}, load_order [{name, version, line, ts}], groups
    [group dicts, file order], dropped, harmony_ids [{id, started_from,
    location, folder, line}], patches {target: {"prefix"|"postfix"|
    "transpiler"|"finalizer": [patch method, ...]}} (the LAST block per target:
    Harmony lists every patch on a target cumulatively), patch_blocks,
    patch_lines, ms, error (None, or why reading stopped early). Never raises."""
    t0 = time.monotonic()
    path = source if isinstance(source, (str, os.PathLike)) else None
    run = _new_run(path)
    groups: dict[str, dict] = {}
    state = {"rec": None, "mode": None, "block": None, "kind": None, "loading": None, "t_base": 0.0, "t_last": None,
             "hid": None}

    def ts_of(m) -> tuple[str | None, float | None]:
        if not m.group(1):
            return None, None
        t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + float("0." + m.group(4))
        if state["t_last"] is not None and t + state["t_base"] < state["t_last"] - 43200:
            state["t_base"] += 86400  # the run passed midnight
        t += state["t_base"]
        state["t_last"] = t
        return f"{m.group(1)}:{m.group(2)}:{m.group(3)}", t

    def finish():
        rec = state["rec"]
        state["rec"] = None
        if rec is not None:
            _add(groups, rec, run)

    def feed(no: int, line: str):
        line = line.rstrip("\r\n")
        m = _LINE.match(line)
        if m is None:  # continuation of the previous message
            mode = state["mode"]
            if mode == "rec" and len(state["rec"]["frames"]) < MAX_FRAMES and line.strip():
                state["rec"]["frames"].append(line[:300])
            elif mode == "hid":
                s = _STARTED.match(line)
                if s and state["hid"] is not None:
                    state["hid"].update(started_from=s.group(1), location=s.group(2),
                                        folder=(_PKG_FOLDER.search(s.group(2)) or [None, None])[1])
            elif mode == "patch":
                k = _PATCH_KIND.match(line)
                if k:
                    state["kind"] = k.group(1)
                elif line.startswith("* ") and state["kind"]:
                    state["block"].setdefault(state["kind"], []).append(line[2:].strip())
                    run["patch_lines"] += 1
            return
        finish()
        state["mode"] = None
        ts, t = ts_of(m)
        if ts:
            run["first_ts"] = run["first_ts"] or (ts, t)
            run["last_ts"] = (ts, t)
        level, src, text = m.group(5), m.group(6).strip(), m.group(7)
        if level in ("Warning", "Error", "Fatal"):
            state["rec"] = {"line": no, "ts": ts, "t": t, "level": level, "source": src, "text": text[:2000],
                            "frames": [], "loading": state["loading"]}
            state["mode"] = "rec"
        elif level in ("Info", "Message"):
            if src == "HarmonyX":
                if text.startswith("### Harmony id="):
                    h = _HARMONY_ID.match(text)
                    state["hid"] = {"id": h.group(1) if h else text[15:], "started_from": None, "location": None,
                                    "folder": None, "line": no}
                    run["harmony_ids"].append(state["hid"])
                    state["mode"] = "hid"
                else:
                    p = _PATCHING.match(text)
                    if p:
                        state["block"] = run["patches"][p.group(1)] = {}
                        state["kind"] = None
                        run["patch_blocks"] += 1
                        state["mode"] = "patch"
            elif src == "BepInEx":
                hd = run["header"]
                if (lm := _LOADING.match(text)):
                    state["loading"] = lm.group(1)
                    run["load_order"].append({"name": lm.group(1), "version": lm.group(2), "line": no, "ts": ts})
                elif text == "Chainloader startup complete":
                    hd["chainloader_done_ts"], hd["chainloader_done_line"] = ts, no
                    state["loading"] = None
                elif text.startswith("Running under Unity"):
                    hd["unity"] = text.rsplit(" v", 1)[-1]
                elif text.endswith("plugins to load"):
                    hd["plugins_to_load"] = int(text.split()[0]) if text.split()[0].isdigit() else None
                elif hd["bepinex"] is None and (h := _HEADER.match(text)):
                    hd["bepinex"], hd["game"] = h.group(1), h.group(2)

    no = 0
    try:
        if path is not None:
            p = Path(path)
            run["mtime"] = p.stat().st_mtime
            with open(p, encoding="utf-8", errors="replace", newline="") as f:
                while True:
                    line = f.readline(MAX_LINE)
                    if not line:
                        break
                    no += 1
                    feed(no, line)
        else:
            for line in source:
                no += 1
                feed(no, str(line)[:MAX_LINE])
    except Exception as err:  # unreadable / vanished mid-read: keep what was read
        run["error"] = repr(err)
        log(f"[loganalysis] reading stopped at line {no}: {err!r}")
    try:
        finish()
    except Exception:
        pass
    run["lines"] = no
    run["groups"] = sorted(groups.values(), key=lambda g: g["first_line"])
    if run["first_ts"] and run["last_ts"]:
        run["duration_s"] = round(run["last_ts"][1] - run["first_ts"][1], 1)
        run["first_ts"], run["last_ts"] = run["first_ts"][0], run["last_ts"][0]
    run["ms"] = round((time.monotonic() - t0) * 1000)
    log(f"[loganalysis] parsed {run['path'] or 'lines'}: {no} lines, {len(run['groups'])} message groups "
        f"({sum(g['count'] for g in run['groups'])} messages, {run['dropped']} dropped), "
        f"{len(run['harmony_ids'])} Harmony ids, {run['patch_blocks']} patch blocks / {len(run['patches'])} targets, "
        f"{run['ms']} ms")
    return run


def _add(groups: dict, rec: dict, run: dict) -> None:
    """Folds one finished Warning/Error/Fatal record into its signature group."""
    text = rec["text"]
    fam = family_of(rec["level"], rec["source"], text)
    exc = _EXC.search(text)
    first = next((n for n in map(frame_name, rec["frames"]) if n and not _is_framework(n)), "")
    subject = None
    if FAMILIES[fam].get("collapse"):  # one group per family+source; the varying part kept as a subject
        sm = FAMILIES[fam]["rx"].search(text)
        subject = sm.group("subject") if sm and "subject" in sm.groupdict() else None
        sig = f"{fam}|{rec['source']}"
    else:
        sig = f"{rec['source']}|{_norm(text)}|{_norm(first)}"
    g = groups.get(sig)
    if g is None:
        if len(groups) >= MAX_GROUPS:
            run["dropped"] += 1
            return
        g = groups[sig] = {"sig": sig, "id": hashlib.sha1(sig.encode("utf-8", "replace")).hexdigest()[:10],
                           "family": fam, "level": rec["level"], "source": rec["source"], "text": text,
                           "exception": exc.group(2) if exc else None, "frames": rec["frames"],
                           "first_frame": first or None, "loading": rec["loading"], "count": 0,
                           "first_line": rec["line"], "last_line": rec["line"], "line_numbers": [],
                           "ts": rec["ts"], "t": rec["t"], "subjects": [],
                           "harmless": bool(FAMILIES[fam].get("harmless")) or _harmless(rec["source"], text)}
    g["count"] += 1
    g["last_line"] = rec["line"]
    if len(g["line_numbers"]) < MAX_LINE_NUMBERS:
        g["line_numbers"].append(rec["line"])
    if subject and subject not in g["subjects"] and len(g["subjects"]) < 50:
        g["subjects"].append(subject)


# ---- failure families + advice (plain words; Thunderstore games say "profile") ----
# Order matters: the first match wins. "rx" runs on the message's first line;
# "exc" on its exception type name. "certain" = the log itself proves it.
FAMILIES: dict[str, dict] = {
    "incompatible": {
        "rx": re.compile(r"^Could not load \[(?P<plugin>.+) [\w.+-]+\] because it is incompatible with: (?P<other>.+)$"),
        "certain": True, "loader": True,
        "title": "{mod} didn't load: it's incompatible with another mod",
        "means": "{mod} says it can't run beside {other}. BepInEx (the mod loader) skipped {mod} so the game "
                 "could start, so nothing from {mod} works in this run.",
        "try": ["Decide which of the two you want to keep.",
                "Switch the other one off in this profile, then launch again.",
                "If you need both, check the mods' pages: one of them may have a newer version that works together."]},
    "missing_dependency": {
        "rx": re.compile(r"^Could not load \[(?P<plugin>.+) [\w.+-]+\] because it has missing dependencies: (?P<other>.+)$"),
        "certain": True, "loader": True,
        "title": "{mod} didn't load: a mod it needs is missing",
        "means": "{mod} needs {other}, which isn't in this profile or isn't switched on (or is too old), "
                 "so BepInEx skipped {mod}.",
        "try": ["Install or switch on the missing mod in this profile (the warnings button lists required mods).",
                "If it's installed, update it: the version may be older than {mod} needs."]},
    "dependency_not_loaded": {
        "rx": re.compile(r"^Skipping \[(?P<plugin>.+) [\w.+-]+\] because it has a dependency that was not loaded"),
        "certain": True, "loader": True,
        "title": "{mod} didn't load because a mod it needs failed first",
        "means": "{mod} itself is probably fine: a mod it relies on didn't load, so BepInEx skipped it too.",
        "try": ["Fix the earlier problem first (it's listed above this one); this one usually goes away with it."]},
    "newer_version": {
        "rx": re.compile(r"^Skipping \[(?P<plugin>.+) [\w.+-]+\] because a newer version exists"),
        "certain": True, "loader": True, "harmless": True,
        "title": "An older copy of {mod} was skipped",
        "means": "Two copies of {mod} are installed; BepInEx used the newer one and ignored the other.",
        "try": ["Nothing needed. To tidy up, remove the older copy from this profile."]},
    "load_error": {
        "rx": re.compile(r"^Error loading \[(?P<plugin>.+) [\w.+-]+\] ?: "),
        "certain": True, "loader": True,
        "title": "{mod} crashed while loading",
        "means": "BepInEx started {mod} but it failed during start-up, so it probably isn't working in this run.",
        "try": ["Update {mod} if there's a newer version.",
                "Check that the mods it needs are installed and up to date.",
                "If it keeps happening, switch {mod} off and tell its author (copy the details below)."]},
    "missing_member": {
        "exc": ("MissingMethodException", "MissingFieldException", "MissingMemberException"),
        "title": "{mod} uses game code that isn't there",
        "means": "{mod} tried to use a part of the game (or of another mod) that doesn't exist in the version "
                 "you have. It was most likely made for a different game or library version. The part of {mod} "
                 "that ran into this probably doesn't work.",
        "try": ["Update {mod}: a newer version may support your game version.",
                "If there's no update, check whether your game was updated recently; the mod may need time to catch up.",
                "Switch {mod} off if the problem bothers you."]},
    "type_load": {
        "exc": ("TypeLoadException", "BadImageFormatException", "ReflectionTypeLoadException",
                "FileNotFoundException", "FileLoadException"),
        "rx": re.compile(r"Could not load (?:file or assembly|type)"),
        "title": "{mod} couldn't load part of its code",
        "means": "Part of {mod}'s code couldn't be loaded. This usually means a mod or a library it uses is the "
                 "wrong version, or two different copies of the same library are installed.",
        "try": ["Update {mod} and the libraries it needs.",
                "Look for two mods that contain copies of the same code (listed above if VOLT found any) and keep only one.",
                "If it started after an update, try the previous version of the mod."]},
    "netprefab_dup": {
        "rx": re.compile(r"NetworkPrefab \((?P<subject>.*?)\) has a duplicate GlobalObjectIdHash"),
        "collapse": True,
        "title": "Some network objects share the same ID",
        "means": "The game found objects that are meant to be unique online but share an ID ({subjects}). "
                 "Often harmless, but it may cause desyncs in multiplayer.",
        "try": ["If multiplayer works, you can ignore this.",
                "If players see different things, look for two mods that add the same items or map objects."]},
    "could_not_patch": {
        "rx": re.compile(r"\b(Could not patch|Failed to patch|Patching exception)\b", re.I),
        "title": "{mod} couldn't change part of the game",
        "means": "{mod} tried to change a piece of the game's code and couldn't. That feature of {mod} "
                 "probably doesn't work; another mod changing the same code, or a game update, may be the reason.",
        "try": ["Update {mod}.", "If it started after adding another mod, try switching that one off to test."]},
    "patch_failed": {
        "rx": re.compile(r"^Error while running (?P<method>.+?)\. Error: "),
        "title": "{mod} hit an error in its game change",
        "means": "Code that {mod} added to the game crashed while running. That part of {mod} may not work; "
                 "sometimes this comes from another mod changing the same thing.",
        "try": ["Update {mod}.", "If it keeps happening, switch {mod} off and tell its author (copy the details below)."]},
    "bad_data": {
        "exc": ("ArgumentException", "JsonSerializationException", "JsonReaderException", "FormatException",
                "KeyNotFoundException"),
        "title": "{mod} couldn't read some data",
        "means": "{mod} read a value it didn't understand, often from an old save or config file made by a "
                 "different version of the mod.",
        "try": ["Update {mod}.",
                "If it mentions a save or config, that file may be from an older version: back it up, then let the mod make a new one."]},
    "null_ref": {
        "exc": ("NullReferenceException",),
        "title": "{mod} hit an error (something it expected wasn't there)",
        "means": "{mod} looked for something that didn't exist yet. Often a side effect of another error, "
                 "or of two mods changing the same thing.",
        "try": ["Fix any earlier problem first; this one often goes away with it.", "Update {mod}."]},
    "error": {
        "title": "{mod} reported an error",
        "means": "An error we don't have advice for yet. It's grouped and shown with the exact text below.",
        "try": ["Update {mod} if there's a newer version.", "Search for the error text with the mod's name, or ask its author."]},
    "warning": {
        "title": "{mod} reported a warning",
        "means": "A warning, not an error: the game kept going. It may or may not matter.",
        "try": ["Only look into this if something in the game doesn't work as expected."]},
}

# Known noise (megadong evidence, handoff report): warnings that don't point at a problem.
# NOT here (user 2026-10-04, dispatch B): "The referenced script ... is missing!" and HarmonyX
# "AccessTools.X: Could not find ..." - they can point at a missing mod / a failed probe, so they show
# as ordinary warnings (possible).
# (source or None for any, regex on the message)
HARMLESS = [
    (None, re.compile(r"does not have a InjectionIdentifierAttribute, this is deprecated")),
    ("ReXuvination", re.compile(r"^Patching [\w.-]+$")),
    (None, re.compile(r"^Deleted \d+ (temp files|unknown bundles)")),
    (None, re.compile(r"must be instantiated using the ScriptableObject\.CreateInstance method")),
    (None, re.compile(r"assembly not found\. Skipping optional patch")),
    (None, re.compile(r"warning\(s\) while loading .*sound_pack\.json|^WARN: 'version' should not be empty")),
    (None, re.compile(r"^The game will freeze for a moment")),
    (None, re.compile(r"^Caching vertexes for \d+ items")),
    (None, re.compile(r"^Found save: .* now migrating")),
    (None, re.compile(r'^Invalid instance for ".*" plugin\. Skipping\.$')),
]


def _harmless(source: str, text: str) -> bool:
    return any((s is None or s == source) and rx.search(text) for s, rx in HARMLESS)


def family_of(level: str, source: str, text: str) -> str:
    """The FAMILIES key for one message (its first line)."""
    exc = _EXC.search(text)
    name = exc.group(2) if exc else ""
    for key, f in FAMILIES.items():
        if f.get("loader") and source != "BepInEx":
            continue
        if name and name in f.get("exc", ()):
            return key
        if "rx" in f and f["rx"].search(text):
            return key
    return "warning" if level == "Warning" else "error"


# ---- attribution + findings ----
_GENERIC_SOURCES = {"unity log", "harmonyx", "bepinex", "preloader", ""}


def _plugin_pkg(index: dict | None, name: str | None) -> str | None:
    hit = (index or {}).get("plugins", {}).get((name or "").strip().casefold())
    return next(iter(hit)) if hit and len(hit) == 1 else None


def attribute_group(g: dict, index: dict | None, dup_pairs: list[frozenset]) -> dict:
    """{"mods": [...], "also": [...], "how": "loader"|"loading"|"source"|"frame"|None,
    "certain": bool, "plugins": [names as the log printed them]} for one group.
    Rules (module docstring); a frame that resolves to several enabled packages
    counts only when they are a flagged duplicate-type pair (then both)."""
    out = {"mods": [], "also": [], "how": None, "certain": False, "plugins": []}
    fam = FAMILIES[g["family"]]
    if fam.get("loader"):
        m = fam["rx"].search(g["text"])
        if m:
            out["plugins"] = [m.group("plugin")] + ([m.group("other")] if "other" in m.groupdict() else [])
            pkg = _plugin_pkg(index, m.group("plugin"))
            out.update(mods=[pkg] if pkg else [], how="loader", certain=True)
            for o in out["plugins"][1:]:
                for part in re.split(r",\s*", o):
                    q = _plugin_pkg(index, re.sub(r" \(.*\)$", "", part))
                    if q and q not in out["mods"]:
                        out["also"].append(q)
            return out
    names = []  # a failing Harmony patch names its own method first ("static void Ns.Cls::M(args)")
    if g["family"] == "patch_failed" and (pm := fam["rx"].search(g["text"])):
        names.append(frame_name(re.sub(r"\(.*", "", pm.group("method")).split(" ")[-1]))
    for f in g["frames"]:
        if "BepInEx.Bootstrap.Chainloader" in f:
            break  # frames past the chainloader are hooks around the loader (AsyncLoggers), not the culprit
        names.append(frame_name(f))
    chain = []  # packages per resolvable frame, innermost first
    for n in names:
        if not n or _is_framework(n) or index is None:
            continue
        hits = ti.attribute(index, n)
        pk = list(dict.fromkeys(p for p, _ in hits))
        if len(pk) == 1 or (len(pk) == 2 and frozenset(pk) in dup_pairs):
            chain.append(pk)
    if chain:
        mods = chain[0]
        also = list(dict.fromkeys(p for c in chain[1:] for p in c if p not in mods))
        top_is_mod = bool(names) and names[0] is not None and bool(ti.attribute(index, names[0]))
        out.update(mods=mods, also=also, how="frame", certain=top_is_mod and not also and len(mods) == 1)
        return out
    if g["loading"] and any("BepInEx.Bootstrap.Chainloader" in f for f in g["frames"]):
        pkg = _plugin_pkg(index, g["loading"])
        out["plugins"] = [g["loading"]]
        if pkg:
            out.update(mods=[pkg], how="loading")
            return out
    if g["source"].casefold() not in _GENERIC_SOURCES:
        pkg = _plugin_pkg(index, g["source"])
        if pkg:
            out.update(mods=[pkg], how="source")
    return out


_HOW = {
    "loader": "BepInEx, the mod loader, names the mod in its own message.",
    "loading": "It happened while BepInEx was starting {mod}.",
    "source": "The message comes from {mod}'s own log.",
    "frame": "{mod}'s code is in the error's stack trace.",
}


def analyze(run: dict, scans: dict | None = None, manifest: dict | None = None,
            toggles: dict | None = None) -> dict:
    """{"findings": [...], "duplicates": [...], "counts": {...}} for a parse_log
    Run. `scans` (full_name -> bepinex_type_index.scan_package_types) and
    `manifest` (the profile's loadorder.json; `toggles` override its enabled
    flags) enable attribution + the duplicate-type check; without them every
    finding is unattributed. Finding dict:
      id, group ("root" | "cascade" | "later" | "harmless"), title,
      severity ("error" | "warning" | "harmless"), confidence ("certain" |
      "likely" | "possible"), why_confidence, mods [full_name], also_involved
      [full_name], mod_names [display names], plugins [names as logged],
      family, count, first_line, last_line, ts ("hh:mm:ss" | None), t (seconds on
      the log's clock, for ordering | None), what_happened, what_it_means,
      what_to_try [str], technical {exception, text, source, frames [str],
      line_numbers [int], subjects [str], signature}, cascade_of (id | None).
    Order: root, its cascades, later problems (file order), harmless. Never raises."""
    t0 = time.monotonic()
    try:
        return _analyze(run, scans, manifest, toggles, t0)
    except Exception as err:
        log(f"[loganalysis] analysis failed ({err!r}); no findings")
        return {"findings": [], "duplicates": [], "counts": {"certain": 0, "likely": 0, "possible": 0, "harmless": 0}}


def _analyze(run, scans, manifest, toggles, t0) -> dict:
    entries, enabled, declared = {}, [], {}
    if manifest:
        from .bepinex_load_orders import _declared_dependencies
        all_e = ([manifest["framework"]] if manifest.get("framework") else []) + manifest["active"] + manifest["inactive"]
        entries = {e["full_name"]: e for e in all_e}
        enabled = [e["full_name"] for e in all_e[:len(all_e) - len(manifest["inactive"])]]  # framework + Active
        enabled = [n for n in enabled if (toggles or {}).get(n, entries[n].get("enabled", True))]
        declared = {n: _declared_dependencies(e) for n, e in entries.items()}
    index = ti.build_index({n: scans[n] for n in enabled if n in scans}) if scans and manifest else None
    dups = [d for d in ti.shared_types(scans, enabled, declared) if d["flagged"]] if index else []
    dup_pairs = [frozenset(d["packages"]) for d in dups]

    def disp(n):
        e = entries.get(n)
        return (e.get("display_name") or e.get("name") or n) if e else n

    findings = []
    for g in run.get("groups", ()):
        a = attribute_group(g, index, dup_pairs)
        fam = FAMILIES[g["family"]]
        harmless = g["harmless"]
        sev = "harmless" if harmless else ("warning" if g["level"] == "Warning" else "error")
        mod = " and ".join(disp(m) for m in a["mods"]) or (a["plugins"][0] if a["plugins"] else "A mod")
        other = a["plugins"][1] if len(a["plugins"]) > 1 else "another mod"
        if fam.get("certain"):
            conf, why = "certain", "BepInEx, the mod loader, says so in its own message."
        elif a["certain"] and sev == "error":
            conf = "certain"
            why = f"The error happened inside {mod}'s own code and no other mod is on its stack trace."
        elif a["mods"] and sev == "error":
            conf = "likely"
            why = _HOW[a["how"]].format(mod=mod) + " The cause may still be a different mod."
        else:
            conf = "possible"
            why = ("No mod is named in the error." if not a["mods"] else _HOW[a["how"]].format(mod=mod)) + (
                " It's a warning, so it may not matter." if sev == "warning" else
                " It's on the list of messages known to be harmless." if harmless else "")
        if any(frozenset(p) in dup_pairs for p in [a["mods"]]) and g["family"] == "type_load":
            why += " These two mods contain copies of the same code (see that finding)."
        times = "once" if g["count"] == 1 else f"{g['count']:,} times"
        fill = {"mod": mod, "other": other, "subjects": ", ".join(g["subjects"][:6]) or "several objects"}
        findings.append({
            "id": g["id"], "group": "harmless" if harmless else "later", "title": fam["title"].format(**fill),
            "severity": sev, "confidence": conf, "why_confidence": why, "mods": a["mods"], "also_involved": a["also"],
            "mod_names": [disp(m) for m in a["mods"]], "plugins": a["plugins"], "family": g["family"],
            "count": g["count"], "first_line": g["first_line"], "last_line": g["last_line"], "ts": g["ts"], "t": g["t"],
            "what_happened": f"The log shows this {times}" + (f", first at {g['ts']}" if g["ts"] else "")
                             + f": “{g['text'][:300]}”",
            "what_it_means": fam["means"].format(**fill),
            "what_to_try": [s.format(**fill) for s in fam["try"]],
            "technical": {"exception": g["exception"], "text": g["text"], "source": g["source"],
                          "frames": list(g["frames"]), "line_numbers": list(g["line_numbers"]),
                          "subjects": list(g["subjects"]), "signature": g["sig"]},
            "cascade_of": None})
    _order(findings)
    for d in dups:  # profile evidence, not the log: two DLLs provably define the same types
        a, b = d["packages"]
        findings.insert(sum(1 for f in findings if f["group"] in ("root", "cascade")), {
            "id": "dup-" + hashlib.sha1(f"{a}|{b}".encode()).hexdigest()[:8], "group": "later",
            "title": f"{disp(a)} and {disp(b)} contain copies of the same code",
            "severity": "error", "confidence": "certain",
            "why_confidence": f"Both mods' files define the same {d['shared_types']:,} pieces of code (types).",
            "mods": [a, b], "also_involved": [], "mod_names": [disp(a), disp(b)], "plugins": [],
            "family": "duplicate_types", "count": d["shared_types"], "first_line": None, "last_line": None,
            "ts": None, "t": None,
            "what_happened": f"{disp(a)} and {disp(b)} are both switched on and their DLL files define "
                             f"{d['shared_types']:,} of the same types (for example {', '.join(d['examples'][:3])}).",
            "what_it_means": "They are most likely two versions of the same mod or library. The game can only use one "
                             "copy, so mods that need the other copy may break, often with load errors.",
            "what_to_try": [f"Keep one of them: switch {disp(b)} or {disp(a)} off in this profile.",
                            "If another mod needs a specific one, keep that one (the details pane shows \"Needed by\")."],
            "technical": {"exception": None, "text": "", "source": "", "frames": [], "line_numbers": [],
                          "subjects": d["examples"], "signature": f"duplicate_types|{a}|{b}"},
            "cascade_of": None})
    counts = {c: sum(1 for f in findings if f["confidence"] == c and f["severity"] != "harmless")
              for c in ("certain", "likely", "possible")}
    counts["harmless"] = sum(1 for f in findings if f["severity"] == "harmless")
    log(f"[loganalysis] {len(findings)} findings ({counts}), {len(dups)} duplicate-type pairs, "
        f"{'with' if index else 'without'} the type index, {(time.monotonic() - t0) * 1000:.0f} ms")
    return {"findings": findings, "duplicates": dups, "counts": counts}


_LOAD_FAILURES = {"type_load", "incompatible", "missing_dependency", "dependency_not_loaded", "load_error"}


def _top_ns(f: dict) -> str | None:
    fr = next((frame_name(x) for x in f["technical"]["frames"] if frame_name(x) and not _is_framework(frame_name(x))), None)
    return fr.split(".")[0] if fr else None


def _order(findings: list[dict]) -> None:
    """Root cause / cascade / later / harmless, in place (spec §3)."""
    errors = [f for f in findings if f["severity"] == "error"]
    if errors:
        root = min(errors, key=lambda f: f["first_line"])
        root["group"] = "root"
        for f in errors:
            if f is root:
                continue
            close = (f["t"] - root["t"] <= CASCADE_S) if root["t"] is not None and f["t"] is not None else True
            linked = (set(f["mods"]) & set(root["mods"]) or (_top_ns(f) and _top_ns(f) == _top_ns(root))
                      or root["family"] in _LOAD_FAILURES)
            if f["first_line"] > root["first_line"] and close and linked:
                f["group"], f["cascade_of"] = "cascade", root["id"]
    rank = {"root": 0, "cascade": 1, "later": 2, "harmless": 3}
    findings.sort(key=lambda f: (rank[f["group"]], f["first_line"] or 0))


def analyze_log(path, profile_root=None, manifest: dict | None = None, cache: dict | None = None) -> dict:
    """parse_log + (with a profile: bepinex_type_index.scan_profile) + analyze,
    in one call for the CLI / a worker job: {"run", "findings", "duplicates",
    "counts"}. `cache` is the scan_key -> scan cache. Never raises."""
    run = parse_log(path)
    scans = None
    if profile_root is not None and manifest is not None:
        scans = ti.scan_profile(profile_root, manifest, cache)
    return {"run": run, **analyze(run, scans, manifest)}
