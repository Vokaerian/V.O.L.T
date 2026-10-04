"""The Troubleshoot window's Qt-free half (troubleshooting phase 2, dispatch B;
PLAN.md §14, spec temp/troubleshoot-phase2/SPEC.md §5): the worker job that
reads a profile (read_profile: log parse + DLL type index + analysis + what
each mod is made of), and every text / grouping the window shows, so
tools/checks/volt_py_bepinex_troubleshoot.py can pin them without Qt.

- redact(): folder paths -> placeholders, for everything the user copies
  (Copy summary / Copy details): VOLT's data folder, the profile folder, the
  game folder, the home folder, then any other C:\\Users\\<name> / /home/<name>.
- rail_sections(): the finding rail, root cause first (FIRST ERROR · LIKELY
  ROOT CAUSE with its cascade indented, LATER PROBLEMS, HARMLESS only when
  asked for).
- headline / last_run_text / when_text / times_text / technical_text /
  summary_text: the window's words.
- mod_rows / mod_matches / related_finding: tab 2 "Mod contents".
- method_entries / mod_patches: tab 2's "Game methods" + "Game code it
  changes" over a patch table {target: {package: {kind: count}}}; the
  window shows them once dispatch C feeds one (set_patch_table).
- Run history (phase 4 dispatch D2, 0.6.42; the records are
  bepinex_runs.py's): stored_run_text / with_verdict (the run selector's
  entries), same_run (is the live log a stored run already?), run_when,
  baseline_text / changes_title / change_items / change_means (the "What
  changed since it last worked" rail section), new_tag, stored_log_note.
Nothing here raises on odd input it gets from the engine (bepinex_log_analysis
never raises either)."""

import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import bepinex_conflicts as bc
from . import bepinex_log_analysis as la
from . import bepinex_runs as runs
from . import bepinex_type_index as ti
from .applog import log

LOG_NAME = "LogOutput.log"  # BepInEx/LogOutput.log of the profile (spec §0.6: the only source)
SECTION_ROOT = "First error · likely root cause"
SECTION_LATER = "Later problems"
SECTION_HARMLESS = "Harmless"
KINDS = ("prefix", "postfix", "transpiler", "finalizer")
LINES_SHOWN = 12  # line numbers listed in the technical details before "…"
TYPES_SHOWN = 6  # TYPES row before "Show all"
NAMESPACES_SHOWN = 8


def log_file(bepinex_dir) -> Path:
    return Path(bepinex_dir) / LOG_NAME


# ---- redaction (Copy summary / Copy details) ----

_USER_DIRS = [re.compile(r"([A-Za-z]:[\\/]+Users[\\/]+)[^\\/\r\n\"'<>|]+", re.I), re.compile(r"(/home/)[^/\s]+"),
              re.compile(r"(/Users/)[^/\s]+")]


def redact(text: str, places: dict) -> str:
    """`text` with each path in `places` ({placeholder: path or None}) replaced
    by its placeholder - longest path first, either slash style, any case,
    only as a whole path segment - then any other user folder's name by
    <user>. Never raises."""
    try:
        text = str(text)
        pairs = []
        for name, path in places.items():
            p = str(path or "").rstrip("\\/")
            if len(p) > 3:  # never a bare drive / root
                pairs.append((p, name))
        for p, name in sorted(pairs, key=lambda x: -len(x[0])):
            alts = {p, p.replace("\\", "/"), p.replace("/", "\\")}
            rx = "|".join(re.escape(a) for a in sorted(alts, key=len, reverse=True))
            text = re.sub(f"(?:{rx})(?![\\w.-])", lambda _m, n=name: n, text, flags=re.I)
        for rx in _USER_DIRS:
            text = rx.sub(lambda m: m.group(1) + "<user>", text)
        return text
    except Exception:
        return ""


# ---- the worker job ----

def _sizes(root, scans: dict, entries: dict) -> dict:
    """{(full_name, rel): bytes} for each scanned DLL (stat only)."""
    out = {}
    for name, scan in scans.items():
        for d in scan.get("dlls", ()):
            try:
                p = bc._on_disk(Path(root), d["file"])
                out[(name, d["file"])] = p.stat().st_size if p is not None else None
            except OSError:
                out[(name, d["file"])] = None
    return out


def read_profile(log_path, root, manifest: dict | None, cache: dict | None = None) -> dict:
    """Everything the window shows, read off the GUI thread: {"run" (parse_log;
    None when there is no log file), "findings", "duplicates", "counts", "mods"
    (mod_rows), "cache" (the scan_key cache it was given, with this pass's
    clean scans added), "ms"}. Never raises."""
    t0 = time.monotonic()
    cache = {} if cache is None else cache
    out = {"run": None, "findings": [], "duplicates": [], "counts": {"certain": 0, "likely": 0, "possible": 0,
                                                                         "harmless": 0},
           "mods": [], "cache": cache, "ms": 0}
    try:
        has_log = Path(log_path).is_file()
        run = la.parse_log(log_path) if has_log else la.parse_log([])
        scans = ti.scan_profile(root, manifest, cache) if manifest else {}
        res = la.analyze(run, scans, manifest)
        out.update(run=run if has_log else None, findings=res["findings"], duplicates=res["duplicates"],
                   counts=res["counts"])
        if manifest:
            entries = _entries(manifest)
            out["mods"] = mod_rows(scans, entries, res["duplicates"], _sizes(root, scans, entries))
    except Exception as err:
        log(f"[troubleshoot] read failed ({err!r}); partial result")
    out["ms"] = round((time.monotonic() - t0) * 1000)
    return out


def _entries(manifest: dict) -> dict:
    return {e["full_name"]: e for e in ([manifest["framework"]] if manifest.get("framework") else [])
            + manifest["active"] + manifest["inactive"]}


def display(entry: dict | None, full_name: str) -> str:
    """The screen's _display_name."""
    return (entry.get("display_name") or entry.get("name") or full_name) if entry else full_name


# ---- tab 1: the findings ----

def rail_sections(findings: list[dict], show_harmless: bool) -> list[tuple[str, list[tuple[dict, bool, str]]]]:
    """[(section label, [(finding, indented, second line)])] in rail order."""
    root = next((f for f in findings if f["group"] == "root"), None)
    sections = []
    first = [(f, f["group"] == "cascade", rail_sub(f, root)) for f in findings if f["group"] in ("root", "cascade")]
    later = [(f, False, rail_sub(f, root)) for f in findings if f["group"] == "later"]
    harmless = [(f, False, rail_sub(f, root)) for f in findings if f["group"] == "harmless"]
    if first:
        sections.append((SECTION_ROOT, first))
    if later:
        sections.append((SECTION_LATER, later))
    if show_harmless and harmless:
        sections.append((SECTION_HARMLESS, harmless))
    return sections


def _who(f: dict) -> str:
    return " · ".join(f.get("mod_names") or []) or "No mod named"


def _times(f: dict) -> str:
    return f" · ×{f['count']:,}" if f.get("count", 1) > 1 and f.get("family") != "duplicate_types" else ""


def _gap_s(f: dict, root: dict | None) -> int | None:
    if root is None or f.get("t") is None or root.get("t") is None:
        return None
    return max(0, round(f["t"] - root["t"]))


def rail_sub(f: dict, root: dict | None) -> str:
    if f["group"] == "cascade":
        gap = _gap_s(f, root)
        return ("Followed it" if gap is None else f"Followed it {gap} s later") + _times(f)
    if f.get("family") == "duplicate_types":
        return _who(f) + " · from their files"
    return _who(f) + _times(f)


def likely_count(counts: dict) -> int:
    return counts.get("certain", 0) + counts.get("likely", 0)


def problems(findings: list[dict]) -> list[dict]:
    """The findings shown without "Show harmless messages too"."""
    return [f for f in findings if f["severity"] != "harmless"]


def _which(profile: str, when: str | None) -> str:
    """"the last run of <profile>" (the live log), or "the run of <when>" (a stored run)."""
    return f"the run of {when}" if when else f"the last run of {profile}"


def headline(findings: list[dict], counts: dict, profile: str, when: str | None = None) -> str:
    n = likely_count(counts)
    if n:
        return f"{n} likely problem{'s' if n != 1 else ''} found in {_which(profile, when)}"
    if problems(findings):
        return f"No likely problems found in {_which(profile, when)}"
    return f"No problems found in {_which(profile, when)}"


def clean_text(profile: str, harmless: int, when: str | None = None) -> str:
    hidden = (f" {harmless} harmless message{'s are' if harmless != 1 else ' is'} hidden; tick "
              "\"Show harmless messages too\" to see them." if harmless else "")
    which = _which(profile, when)
    return f"{which[0].upper()}{which[1:]} logged no errors that point to a problem.{hidden}"


def _clock(epoch: float | None, now: datetime | None = None) -> str | None:
    if epoch is None:
        return None
    try:
        when = datetime.fromtimestamp(epoch)
    except (OverflowError, OSError, ValueError):
        return None
    now = now or datetime.now()
    day = ("today" if when.date() == now.date() else
           "yesterday" if (now.date() - when.date()).days == 1 else f"{when.day} {when:%b}")
    return f"{when:%H:%M} {day}"


def last_run_text(run: dict, running: bool, now: datetime | None = None) -> str:
    """'18:05 today · played 4 min · 41,212 log lines read'."""
    lines = f"{run.get('lines', 0):,} log lines read"
    if running:
        return f"now · the game is still running · {lines} so far"
    parts = [_clock(run.get("mtime"), now)]
    d = run.get("duration_s")
    if d is not None:
        parts.append("played under a minute" if d < 60 else f"played {round(d / 60)} min")
    parts.append(lines)
    return " · ".join(p for p in parts if p)


def profile_changed(updated_at, log_mtime: float | None) -> str | None:
    """The banner's saved-at time ("18:40") when the profile was saved after
    the log was last written, else None."""
    if not updated_at or log_mtime is None:
        return None
    try:
        saved = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
        if saved.tzinfo is None:
            saved = saved.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if saved.timestamp() <= log_mtime + 1:  # a save during the same second as the last log line: not "after"
        return None
    return f"{saved.astimezone():%H:%M}"


CHANGED_BANNER = "You changed this profile after this run (saved at {at}). Launch the game again to check the changes."
RUNNING_BANNER = "The game is still running, so its log isn't finished. These results are from the log so far."
CLOSED_BANNER = "The game has closed since VOLT read the log. Read it again to see the whole run."


def when_text(f: dict, root: dict | None) -> str:
    if f.get("family") == "duplicate_types":
        return "Found in the mods' files, not in the log"
    ts = f.get("ts")
    where = f"line {f['first_line']:,}" if f.get("first_line") else None
    if f["group"] == "root":
        return "First error of the run" + (f", {ts}" if ts else f", {where}" if where else "")
    if f["group"] == "cascade":
        gap = _gap_s(f, root)
        if ts and gap is not None:
            return f"{ts}, {gap} second{'s' if gap != 1 else ''} after the first error"
    return ts or (where[0].upper() + where[1:] if where else "")


def times_text(f: dict) -> str:
    if f.get("family") == "duplicate_types":
        return "Not a log message"
    n = f.get("count", 1)
    return "once" if n == 1 else f"{n:,} times (one row in the list)"


def steps_text(steps: list[str]) -> str:
    """what_to_try as TextBlocks text: one plain line, or numbered steps."""
    if len(steps) == 1:
        return steps[0]
    return "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))


def technical_text(f: dict) -> str:
    t = f.get("technical") or {}
    if f.get("family") == "duplicate_types":
        return ("Both mods define these types (examples):\n" + "\n".join("  " + s for s in t.get("subjects", ()))
                + f"\n\n{f.get('count', 0):,} shared types in all")
    lines = [t.get("text") or ""] + ["  " + fr for fr in t.get("frames", ())]
    if t.get("subjects"):
        lines += ["", "Named in the messages: " + ", ".join(t["subjects"])]
    level = {"error": "Error", "warning": "Warning"}.get(f["severity"], "Harmless")
    lines += ["", f"Source: {t.get('source') or 'none named'} · {level}"]
    first, last, ts = f.get("first_line"), f.get("last_line"), f.get("ts")
    if first:
        at = f"line {first:,}" + (f" ({ts})" if ts else "")
        lines.append(f"First at {at}, last at line {last:,}" if last and last != first else f"At {at}")
    nums = t.get("line_numbers") or []
    if f.get("count", 1) > 1 and nums:
        shown = ", ".join(f"{n:,}" for n in nums[:LINES_SHOWN])
        lines.append(f"{f['count']:,} times: lines {shown}" + (" …" if f["count"] > LINES_SHOWN else ""))
    return "\n".join(lines).strip("\n")


def detail_text(f: dict) -> str:
    """One finding as plain text (Copy details; redact() it first)."""
    return "\n\n".join([
        f["title"],
        f"Confidence: {f['confidence']} ({f['why_confidence']})",
        "Mods: " + (", ".join(f.get("mod_names") or []) or "none named"),
        "What happened: " + f["what_happened"],
        "What it means: " + f["what_it_means"],
        "What to try:\n" + steps_text(f["what_to_try"]),
        "Technical details:\n" + technical_text(f),
    ])


def summary_text(findings: list[dict], counts: dict, *, game: str, profile: str, version: str,
                 last_run: str, show_harmless: bool, when: str | None = None) -> str:
    """Copy summary (redact() it first): the headline, the run, the rail.
    `when`: a stored run's time (the headline names that run)."""
    out = [f"VOLT {version} troubleshoot summary: {game}, profile \"{profile}\"",
           f"{'Run' if when else 'Last run'}: {last_run}", headline(findings, counts, profile, when) + "."]
    root = next((f for f in findings if f["group"] == "root"), None)
    for label, items in rail_sections(findings, show_harmless):
        out += ["", label.upper()]
        for f, indent, _sub in items:
            mods = ", ".join(f.get("mod_names") or []) or "no mod named"
            where = when_text(f, root)
            out.append(f"{'    ' if indent else ''}- [{f['confidence']}] {f['title']} ({mods}; {times_text(f)}"
                       + (f"; {where}" if where else "") + ")")
    hidden = sum(1 for f in findings if f["group"] == "harmless")
    if hidden and not show_harmless:
        out += ["", f"({hidden} harmless message{'s' if hidden != 1 else ''} not listed)"]
    return "\n".join(out)


# ---- run history (phase 4 dispatch D2, 0.6.42): the run selector, What changed, New tags ----

VERDICT_WORDS = {"worked": "worked", "didnt": "didn't work", "probably": "probably worked"}
MARK_WORDS = {"worked": "worked", "didnt": "didn't work"}
NO_CHANGES = "No mods were added, removed, updated or switched on or off since then."
LOG_NOT_KEPT = "VOLT didn't keep this run's log: it was over 5 MB (a patch-details recording). The findings were saved when the run ended."
LOG_GONE = "This run's saved log file is missing. The findings were saved when the run ended."


def run_when(rec: dict, now: datetime | None = None) -> str:
    """A stored run's time, "18:05 yesterday" (when its log was last written,
    else the launch)."""
    lg = rec.get("log") or {}
    return _clock(lg.get("mtime") or rec.get("started"), now) or "an earlier launch"


def with_verdict(text: str, rec: dict | None) -> str:
    word = VERDICT_WORDS.get(runs.verdict(rec)) if rec else None
    return f"{text} · {word}" if word else text


def stored_run_text(rec: dict, now: datetime | None = None) -> str:
    """A stored run's selector entry, in the live entry's words: '18:05
    yesterday · played 12 min · 41,212 log lines read · probably worked'
    (played = the watch's measure, else the log's own span)."""
    lg = rec.get("log") or {}
    play = rec.get("play_s")
    text = last_run_text({"mtime": lg.get("mtime") or rec.get("started"), "lines": lg.get("lines") or 0,
                          "duration_s": play if isinstance(play, (int, float)) else lg.get("duration_s")}, False, now)
    return with_verdict(text, rec)


def same_run(run: dict | None, rec: dict) -> bool:
    """The live log IS this stored run (the game has exited and VOLT kept it):
    same last-write time (within a second) and the same line count."""
    lg = rec.get("log") or {}
    try:
        return run is not None and abs(float(run["mtime"]) - float(lg["mtime"])) < 1 and run.get("lines") == lg.get("lines")
    except (KeyError, TypeError, ValueError):
        return False


def changes_title(kind: str) -> str:
    return "What changed since it last worked" if kind == "worked" else "What changed since the previous run"


def baseline_text(kind: str, base: dict, now: datetime | None = None) -> str:
    """The header under What changed: which run it compares with."""
    which = "your last run that worked" if kind == "worked" else "the previous run"
    return f"Compared with {which} ({run_when(base, now)})."


def new_tag(base: dict, now: datetime | None = None) -> str:
    return f"New since {run_when(base, now)}"


def _n_mods(n: int) -> str:
    return f"{n} mod{'s' if n != 1 else ''}"


def change_items(diff: dict) -> list[dict]:
    """bepinex_runs.diff_manifests -> the rail rows of What changed: [{"key",
    "title", "sub", "mods": [(full_name, name, detail)], "muted"}] - mod
    loader, added, removed, newer, older, switched on, switched off, then
    reinstalled (muted)."""
    def name(m):
        return m.get("display_name") or m.get("full_name") or "?"

    def row(key, title, mods, muted=False):
        return {"key": key, "title": title, "sub": " · ".join(n for _f, n, _d in mods), "mods": mods, "muted": muted}

    out = []
    fw = diff.get("framework")
    if fw:
        new = fw["new"]
        out.append({"key": "framework", "title": "Mod loader " + ("updated" if fw["direction"] == "newer" else "is an older version"),
                    "sub": f"{name(new)} {fw['old'].get('version')} → {new.get('version')}",
                    "mods": [(new.get("full_name"), name(new), f"{fw['old'].get('version')} → {new.get('version')}")],
                    "muted": False})
    simple = lambda ms: [(m.get("full_name"), name(m), m.get("version") or "") for m in ms]  # noqa: E731
    if diff.get("added"):
        out.append(row("added", f"Added: {_n_mods(len(diff['added']))}", simple(diff["added"])))
    if diff.get("removed"):
        out.append(row("removed", f"Removed: {_n_mods(len(diff['removed']))}", simple(diff["removed"])))
    for direction, title in (("newer", "Newer version"), ("older", "Older version")):
        ups = [u for u in diff.get("updated") or [] if u["direction"] == direction]
        if ups:
            out.append(row(direction, f"{title}: {_n_mods(len(ups))}",
                           [(u["mod"].get("full_name"), name(u["mod"]), f"{u['old']} → {u['new']}") for u in ups]))
    if diff.get("switched_on"):
        out.append(row("switched_on", f"Switched on: {_n_mods(len(diff['switched_on']))}", simple(diff["switched_on"])))
    if diff.get("switched_off"):
        out.append(row("switched_off", f"Switched off: {_n_mods(len(diff['switched_off']))}", simple(diff["switched_off"])))
    if diff.get("reinstalled"):
        out.append(row("reinstalled", f"Reinstalled, same version: {_n_mods(len(diff['reinstalled']))}",
                       simple(diff["reinstalled"]), muted=True))
    return out


_MEANS = {
    "framework": "The mod loader itself (BepInEx) changed version. Mods made for one version usually work with the "
                 "next, but if many mods broke at once, this is the first thing to check.",
    "added": "These mods weren't in that run. A new mod is the most common reason a working profile breaks: switch "
             "them off one at a time and launch again to find out.",
    "removed": "These mods were in that run and aren't in this one. If another mod needed them, it may fail to load now.",
    "newer": "These mods were updated since then. An update can bring new problems, or need a newer version of "
             "another mod.",
    "older": "These mods are an older version than in that run. Mods that need the newer version may fail.",
    "switched_on": "These mods were switched off in that run and are switched on now.",
    "switched_off": "These mods were switched on in that run and are switched off now. Mods that need them may fail.",
    "reinstalled": "Installed again at the same version. This rarely matters; listed in case a file was replaced.",
}


def change_means(key: str) -> str:
    return _MEANS.get(key, "")


def stored_log_note(rec: dict, has_file: bool) -> str | None:
    """A stored run whose log isn't there: the technical details say why."""
    if not (rec.get("log") or {}).get("gz", True):
        return LOG_NOT_KEPT
    return None if has_file else LOG_GONE


# ---- tab 2: Mod contents ----

def mod_rows(scans: dict, entries: dict, duplicates: list[dict], sizes: dict | None = None) -> list[dict]:
    """[{"id", "name", "files": [(rel, bytes | None)], "namespaces", "types"
    (sorted full names), "shares": [{"id", "name", "count", "examples"}]}]:
    mods that share code first, then the rest, each by name."""
    sizes = sizes or {}
    shares: dict[str, list[dict]] = {}
    for d in duplicates:
        a, b = d["packages"]
        for me, other in ((a, b), (b, a)):
            shares.setdefault(me, []).append({"id": other, "name": display(entries.get(other), other),
                                              "count": d["shared_types"], "examples": list(d.get("examples", ()))})
    rows = []
    for name, scan in scans.items():
        types = sorted({t for d in scan.get("dlls", ()) for t in d["types"]})
        spaces = sorted({t.rpartition(".")[0] for t in types if "." in t and "<" not in t})
        rows.append({"id": name, "name": display(entries.get(name), name),
                     "files": [(d["file"], sizes.get((name, d["file"]))) for d in scan.get("dlls", ())],
                     "namespaces": spaces, "types": types, "shares": shares.get(name, [])})
    rows.sort(key=lambda r: (not r["shares"], r["name"].casefold()))
    return rows


def mod_matches(row: dict, query: str) -> bool:
    q = query.strip().casefold()
    if not q:
        return True
    return (q in row["name"].casefold() or q in row["id"].casefold()
            or any(q in f.casefold() for f, _ in row["files"]) or any(q in s.casefold() for s in row["namespaces"])
            or any(q in t.casefold() for t in row["types"]))


def size_text(n: int | None) -> str:
    if n is None:
        return ""
    return f"{n} B" if n < 1024 else f"{round(n / 1024):,} KB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MB"


def mod_sub(row: dict) -> str:
    n, t = len(row["files"]), len(row["types"])
    return f"{n} file{'s' if n != 1 else ''} · {t:,} type{'s' if t != 1 else ''}"


def namespaces_text(row: dict) -> str:
    s = row["namespaces"]
    if not s:
        return "None"
    return ", ".join(s[:NAMESPACES_SHOWN]) + (f" and {len(s) - NAMESPACES_SHOWN} more" if len(s) > NAMESPACES_SHOWN else "")


def types_text(row: dict, show_all: bool) -> str:
    t = row["types"]
    if not t:
        return "None"
    shown = t if show_all else t[:TYPES_SHOWN]
    return ("\n" if show_all else ", ").join(shown) + ("" if show_all or len(t) <= TYPES_SHOWN else f" … ({len(t):,} in all)")


def share_text(share: dict) -> str:
    ex = ", ".join(share["examples"][:3])
    return (f"{share['count']:,} of the same types (pieces of code) are in both mods' files"
            + (f", for example {ex}." if ex else "."))


SHARE_ADVICE = ("Two copies of the same code usually means two versions of one mod are installed. The game may use a "
                "mix of both, and either can break. Keep one of them switched on.")


def related_finding(findings: list[dict], a: str, b: str) -> str | None:
    """The tab 1 finding "See what this caused in the last run" opens for the
    pair (a, b): the first load failure blamed on either, else the pair's own
    duplicate-type finding."""
    pair = {a, b}
    for f in findings:
        if f.get("family") == "type_load" and pair & set(f.get("mods") or ()):
            return f["id"]
    return next((f["id"] for f in findings if f.get("family") == "duplicate_types" and set(f["mods"]) == pair), None)


# ---- tab 2: game methods (fed by dispatch C's patch table) ----

def method_entries(targets: dict) -> list[dict]:
    """[{"target", "mods": [full_name], "kinds": {kind: total}}] from a patch
    table {target: {package: {kind: count}}}: changed by 2+ mods first, then by
    name."""
    out = []
    for target, by_mod in (targets or {}).items():
        kinds = {k: sum(int(v.get(k, 0)) for v in by_mod.values()) for k in KINDS}
        out.append({"target": target, "mods": sorted(by_mod), "kinds": kinds})
    out.sort(key=lambda e: (len(e["mods"]) < 2, e["target"].casefold()))
    return out


def kinds_text(kinds: dict) -> str:
    plural = {"prefix": "prefixes", "postfix": "postfixes", "transpiler": "transpilers", "finalizer": "finalizers"}
    return ", ".join(f"{n} {plural[k] if n > 1 else k}" for k in KINDS if (n := kinds.get(k, 0)))


def mod_patches(targets: dict, mod: str, name_of=lambda n: n) -> list[tuple[str, str, str]]:
    """[(target, how, also changed by)] for one mod."""
    rows = []
    for target, by_mod in sorted((targets or {}).items(), key=lambda x: x[0].casefold()):
        mine = by_mod.get(mod)
        if mine:
            how = kinds_text(mine)
            also = ", ".join(sorted(name_of(m) for m in by_mod if m != mod)) or "–"
            rows.append((target, how, also))
    return rows


# ---- Game methods: the recorded patch table (dispatch C, 0.6.39; bepinex_patchlog.py stores it) ----

NONE_TITLE = "No diagnostic run yet"
PENDING_TITLE = "Will record on the next launch"
RECORD_BUTTON = "Record patch details on next launch"
RECORD_NOTE = ("One launch only, then VOLT turns it off again. That launch's log file is about 5 times bigger. "
               "Also in Settings, Troubleshooting.")
RUNNING_TIP = "Unavailable while the game is running"


def none_text(profile: str) -> str:
    return ("To list which game code each mod changes, the game has to write it down while it starts. VOLT can "
            f"turn that on for one launch of {profile}.")


def pending_text(profile: str) -> str:
    return (f"Start {profile} with the \"Modded\" button and wait for the main menu. When the game has closed, come "
            "back here: this table fills in.")


def method_owner(target: str) -> str:
    """"void QuickMenuManager::Start()" -> "QuickMenuManager" (the type, without its namespace)."""
    return target.split("::", 1)[0].rsplit(" ", 1)[-1].rsplit(".", 1)[-1] or target


def method_why(n_mods: int) -> str:
    return ("Sharing a method is common; it only matters if a problem shows up there." if n_mods > 1
            else "One mod only; nothing overlaps here.")


def method_means(names: list[str]) -> str:
    if len(names) > 1:
        return (f"{len(names)} mods change this part of the game's code. That is common and usually fine: each adds "
                "its own step before or after the game's.")
    return f"Only {names[0]} changes this part of the game's code."


def method_try(names: list[str], target: str) -> str:
    area = method_owner(target)
    if len(names) > 1:
        return (f"Nothing, unless a problem shows up around {area}. Then these are the mods to switch off first, "
                "one at a time.")
    return f"Nothing to do here. If a problem shows up around {area}, {names[0]} is the mod to look at."


def patch_status(count: int | None, recorded: str | None, pending: bool) -> str:
    """The Mod contents bar's right-hand status."""
    if count is not None:
        what = f"{count:,} game method{'' if count == 1 else 's'}"
        return f"Patch details recorded {recorded} · {what}" if recorded else f"Patch details: {what}"
    return "Patch details: will record on next launch" if pending else "No patch details recorded yet"
