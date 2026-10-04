"""Run history (troubleshooting phase 4, dispatch D1, 0.6.41; PLAN.md §14,
spec temp/troubleshoot-phase4/SPEC.md): every Modded launch of a Thunderstore
profile is kept as a run record - what ran (the manifest summary), what the
log analyzer found at exit, how long it was played - so the Troubleshoot
window can show older runs, the last run that worked, and what changed since.
Qt-free; every function logs `[runs] ...` and never raises.

Per profile, beside loadorder.json (copied by nothing: "Copy to new profile"
leaves it out, exports skip it, delete / replace take it with the folder):

  volt-runs/pending.json            written at a Modded launch, before bl.start
  volt-runs/pending.<hex>.claimed   a finisher's claim (os.replace of pending.json)
  volt-runs/<id>.log.snap           the claimed run's log, copied at claim time
  volt-runs/<id>.json               the run record (schema below)
  volt-runs/<id>.log.gz             its LogOutput.log (not kept when the raw log is > GZ_MAX)

<id> = the launch's start time, UTC, ISO 8601 basic with milliseconds
("20261004T215557.123Z"): it sorts by time and is a valid Windows file name.

Finishing is idempotent and crash-safe: whoever renames pending.json first
(os.replace is atomic; the loser's rename finds nothing) owns the run and
copies LogOutput.log at once, so a relaunch right after can't overwrite the
log being read. A log last written before the launch (minus LOG_SLACK_S) means
the game never started: the run is dropped. Callers: the screen when the
watched game exits, on screen open for every profile left pending (VOLT
closed / crashed, the game killed), and at every Modded launch (the previous
run first, then the new pending.json).

Record (schema 1):
  {schema, id, started (epoch), finished (epoch), volt_version (the VOLT that
   analyzed it; "New" tags compare only runs analyzed by the same version),
   launched_with (the VOLT that launched it), profile {slug, name},
   manifest {framework: <mod> | None, mods: [<mod>, ...]} with
   <mod> = {full_name, display_name, version, enabled (False for Inactive
   mods), active, installed_at},
   log {size, mtime, lines, first_ts, last_ts, duration_s, error, gz},
   header (parse_log's header), chainloader_done (bool: "Chainloader startup
   complete" was logged), play_s (float | None), play_from ("watch" |
   "launch" | None), findings (bepinex_log_analysis.analyze's, as stored at
   exit), counts, mark (None | "worked" | "didnt")}
"""

import gzip
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from . import bepinex_load_orders as lo
from . import bepinex_log_analysis as la
from . import bepinex_type_index as ti
from . import thunderstore as ts
from .applog import log
from .bepinex_patchlog import LOG_SLACK_S, log_path
from .fsutil import read_json, write_text_atomic

RUNS_DIR = "volt-runs"
PENDING = "pending.json"
SCHEMA_VERSION = 1
KEEP = 10  # runs kept per profile (user 2026-10-04)
GZ_MAX = 5 * 1024 * 1024  # a bigger raw log (an all-channels recording) keeps only its JSON
PROBABLY_WORKED_MIN = 5  # mods finished loading AND played at least this long = "probably worked"
STALE_S = 24 * 3600  # a claim / snapshot older than this was left by a crash mid-finish: pruned
MARKS = ("worked", "didnt")


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("volt-py")
    except Exception:
        return "unknown"


def runs_dir(tree) -> Path:
    return Path(tree) / RUNS_DIR


def run_id(epoch: float) -> str:
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime(epoch)) + f".{int(epoch * 1000) % 1000:03d}Z"


def _dump(path: Path, obj) -> None:
    """Raises OSError."""
    write_text_atomic(path, json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def summarize(manifest: dict | None) -> dict:
    """The manifest summary stored with a run: what decides what ran (no
    files, no configs, no order)."""
    def mod(e, active):
        return {"full_name": e.get("full_name"), "display_name": e.get("display_name") or e.get("name") or e.get("full_name"),
                "version": e.get("version") or "", "enabled": bool(active and e.get("enabled", True)), "active": active,
                "installed_at": e.get("installed_at")}
    m = manifest or {}
    fw = m.get("framework")
    return {"framework": mod(fw, True) if fw else None,
            "mods": [mod(e, True) for e in m.get("active") or []] + [mod(e, False) for e in m.get("inactive") or []]}


# ---- launch ----

def write_pending(tree, manifest: dict | None, now: float | None = None) -> str | None:
    """At a Modded launch, after the previous run was claimed: the new run's
    pending.json. Its id, or None when it couldn't be written."""
    started = time.time() if now is None else now
    rid = run_id(started)
    try:
        _dump(runs_dir(tree) / PENDING, {"schema": SCHEMA_VERSION, "id": rid, "started": started,
                                          "volt_version": _version(), "manifest": summarize(manifest)})
        log(f"[runs] {Path(tree).name}: run {rid} pending")
        return rid
    except Exception as err:
        log(f"[runs] {Path(tree).name}: writing {PENDING} FAILED, this run isn't kept: {err!r}")
        return None


def discard_pending(tree) -> None:
    """The launch didn't start (bl.start failed): its pending run goes."""
    try:
        os.remove(runs_dir(tree) / PENDING)
        log(f"[runs] {Path(tree).name}: the launch failed, pending run discarded")
    except OSError:
        pass


def pending_trees(load_orders_root) -> list[Path]:
    """Every profile folder with a pending run."""
    try:
        return [Path(e.path) for e in os.scandir(load_orders_root) if e.is_dir() and (runs_dir(e.path) / PENDING).is_file()]
    except OSError:
        return []


# ---- finish ----

def claim(tree) -> dict | None:
    """Takes the profile's pending run: os.replace(pending.json -> a unique
    claim) and a copy of the log, both at once (cheap: a rename + one file
    copy, fine on the GUI thread right before a relaunch). None when there is
    nothing to claim (no pending run, or another finisher got it first)."""
    d = runs_dir(tree)
    mine = d / f"pending.{uuid.uuid4().hex}.claimed"
    try:
        os.replace(d / PENDING, mine)
    except FileNotFoundError:
        return None
    except OSError as err:
        log(f"[runs] {Path(tree).name}: claiming the pending run FAILED: {err!r}")
        return None
    try:
        pending = read_json(mine)
        rid, started = str(pending["id"]), float(pending["started"])
    except Exception as err:
        log(f"[runs] {Path(tree).name}: the pending run is unreadable, dropped: {err!r}")
        _remove(mine)
        return None
    out = {"path": mine, "pending": pending, "id": rid, "started": started, "snap": None, "mtime": None, "size": None}
    src = log_path(tree)
    try:
        st = src.stat()
        out["mtime"], out["size"] = st.st_mtime, st.st_size
        if st.st_mtime >= started - LOG_SLACK_S:
            snap = d / f"{rid}.log.snap"
            shutil.copyfile(src, snap)
            out["snap"] = snap
    except FileNotFoundError:
        pass
    except OSError as err:
        log(f"[runs] {Path(tree).name}: copying the log of run {rid} FAILED: {err!r}")
    log(f"[runs] {Path(tree).name}: run {rid} claimed (log {'copied' if out['snap'] else 'not used'})")
    return out


def finish_run(tree, *, play_s: float | None = None, ended_at: float | None = None, cache: dict | None = None,
               claimed: dict | None = None) -> dict | None:
    """Finishes the profile's pending run (or `claimed`, from claim()): the
    stored record, or None (nothing pending, another finisher has it, the
    game never wrote its log, or saving failed). `play_s`: the watch's
    measure; else `ended_at` - the launch time (a re-attached watch); else
    None. `cache`: the type-index scan_key cache (filled in place). Heavy
    (log parse + DLL scan): a worker job. Never raises."""
    t0 = time.monotonic()
    name = Path(tree).name
    c = claimed if claimed is not None else claim(tree)
    if c is None:
        return None
    try:
        rid, started = c["id"], c["started"]
        if c["snap"] is None:
            why = ("no log file" if c["mtime"] is None else "the log couldn't be copied" if c["mtime"] >= started - LOG_SLACK_S
                   else "the log is older than the launch (the game didn't start?)")
            log(f"[runs] {name}: run {rid} dropped: {why}")
            return None
        run = la.parse_log(c["snap"])
        try:
            manifest = lo.normalize_manifest(read_json(Path(tree) / lo.MANIFEST_FILE), name)
        except Exception as err:
            log(f"[runs] {name}: profile unreadable, analysing run {rid} without mod names: {err!r}")
            manifest = None
        pending_m = c["pending"].get("manifest") or summarize(None)
        toggles = {m["full_name"]: m["enabled"] for m in pending_m.get("mods") or [] if m.get("full_name")}
        scans = ti.scan_profile(tree, manifest, {} if cache is None else cache) if manifest else None
        res = la.analyze(run, scans, manifest, toggles)
        if play_s is not None:
            play, src = float(play_s), "watch"
        elif ended_at is not None:
            play, src = max(0.0, ended_at - started), "launch"
        else:
            play, src = None, None
        gz = (c["size"] or 0) <= GZ_MAX
        record = {
            "schema": SCHEMA_VERSION, "id": rid, "started": started, "finished": time.time(),
            "volt_version": _version(), "launched_with": c["pending"].get("volt_version"),
            "profile": {"slug": name, "name": (manifest or {}).get("name") or name},
            "manifest": pending_m,
            "log": {"size": c["size"], "mtime": c["mtime"], "lines": run["lines"], "first_ts": run["first_ts"],
                    "last_ts": run["last_ts"], "duration_s": run["duration_s"], "error": run["error"], "gz": gz},
            "header": run["header"], "chainloader_done": run["header"].get("chainloader_done_line") is not None,
            "play_s": play, "play_from": src, "findings": res["findings"], "counts": res["counts"], "mark": None}
        d = runs_dir(tree)
        if gz:
            with open(c["snap"], "rb") as f:
                data = gzip.compress(f.read(), 6)
            tmp = d / f"{rid}.log.gz.tmp"
            tmp.write_bytes(data)
            os.replace(tmp, d / f"{rid}.log.gz")
        _dump(d / f"{rid}.json", record)
        log(f"[runs] {name}: run {rid} kept: {len(res['findings'])} findings {res['counts']}, "
            f"mods loaded {'yes' if record['chainloader_done'] else 'no'}, "
            f"played {'?' if play is None else f'{play / 60:.1f} min'} ({src or 'unknown'}), log {c['size'] or 0:,} bytes"
            f"{'' if gz else f' (over {GZ_MAX >> 20} MB: log not kept)'}, {(time.monotonic() - t0) * 1000:.0f} ms")
        prune(tree)
        return record
    except Exception as err:
        log(f"[runs] {name}: finishing run {c.get('id')} FAILED, not kept: {err!r}")
        return None
    finally:
        _remove(c["path"])
        if c.get("snap"):
            _remove(c["snap"])


def _remove(p) -> None:
    try:
        os.remove(p)
    except OSError:
        pass


def prune(tree, keep: int = KEEP) -> None:
    """Keeps the newest `keep` runs (record + log); removes claims /
    snapshots a crash left behind (older than STALE_S)."""
    d = runs_dir(tree)
    try:
        ids = sorted(p.name[:-5] for p in d.glob("*.json") if p.name != PENDING)
        for rid in ids[:-keep] if len(ids) > keep else []:
            for p in (d / f"{rid}.json", d / f"{rid}.log.gz"):
                _remove(p)
            log(f"[runs] {Path(tree).name}: run {rid} pruned (keeping {keep})")
        now = time.time()
        for p in list(d.glob("*.claimed")) + list(d.glob("*.snap")) + list(d.glob("*.tmp")):
            if now - p.stat().st_mtime > STALE_S:
                _remove(p)
                log(f"[runs] {Path(tree).name}: removed stale {p.name}")
    except OSError as err:
        log(f"[runs] {Path(tree).name}: prune FAILED: {err!r}")


# ---- reading ----

def load_run(tree, rid: str) -> dict | None:
    try:
        r = read_json(runs_dir(tree) / f"{rid}.json")
    except FileNotFoundError:
        return None
    except Exception as err:
        log(f"[runs] {Path(tree).name}: run {rid} unreadable, skipped: {err!r}")
        return None
    return r if isinstance(r, dict) and r.get("schema") == SCHEMA_VERSION and r.get("id") == rid else None


def list_runs(tree) -> list[dict]:
    """The profile's stored runs, newest first (unreadable ones skipped)."""
    try:
        ids = sorted((p.name[:-5] for p in runs_dir(tree).glob("*.json") if p.name != PENDING), reverse=True)
    except OSError:
        return []
    return [r for r in (load_run(tree, i) for i in ids) if r is not None]


def log_text(tree, rid: str) -> str | None:
    """A stored run's log, or None (not kept / unreadable)."""
    try:
        return gzip.decompress((runs_dir(tree) / f"{rid}.log.gz").read_bytes()).decode("utf-8", "replace")
    except Exception:
        return None


def mark_run(tree, rid: str, mark: str | None) -> bool:
    """The user's "worked" / "didn't work" (None clears it). False when the
    run is gone or it couldn't be saved."""
    if mark is not None and mark not in MARKS:
        return False
    r = load_run(tree, rid)
    if r is None:
        return False
    try:
        _dump(runs_dir(tree) / f"{rid}.json", {**r, "mark": mark})
    except Exception as err:
        log(f"[runs] {Path(tree).name}: marking run {rid} FAILED: {err!r}")
        return False
    log(f"[runs] {Path(tree).name}: run {rid} marked {mark}")
    return True


# ---- last known good, baseline, what changed ----

def verdict(run: dict) -> str | None:
    """"worked" / "didnt" (the user's mark), "probably" (mods finished
    loading and played >= PROBABLY_WORKED_MIN), else None."""
    if run.get("mark") in MARKS:
        return run["mark"]
    play = run.get("play_s")
    if run.get("chainloader_done") and isinstance(play, (int, float)) and play >= PROBABLY_WORKED_MIN * 60:
        return "probably"
    return None


def last_known_good(runs: list[dict]) -> dict | None:
    """The newest run (runs newest first) that worked: the user's mark wins
    for the run it's on, else the automatic rule."""
    return next((r for r in runs if verdict(r) in ("worked", "probably")), None)


def baseline(runs: list[dict], rid: str | None = None) -> tuple[dict | None, str | None]:
    """What a run is compared with: (the last known good run older than
    `rid`, "worked"), else (the run just before it, "previous"), else
    (None, None). `rid` None = compare the live log with every stored run."""
    older = [r for r in runs if rid is None or r["id"] < rid]
    good = last_known_good(older)
    if good is not None:
        return good, "worked"
    return (older[0], "previous") if older else (None, None)


def new_signatures(run: dict, base: dict | None) -> set[str]:
    """Signatures (technical.signature) of `run`'s findings that `base`
    doesn't have. Empty without a baseline, or when the two were analyzed by
    different VOLT versions (an engine change would mark everything new)."""
    if base is None or run.get("volt_version") != base.get("volt_version"):
        return set()
    sig = lambda f: (f.get("technical") or {}).get("signature")  # noqa: E731
    before = {sig(f) for f in base.get("findings") or []}
    return {sig(f) for f in run.get("findings") or [] if sig(f) and sig(f) not in before}


def new_problems(run: dict, base: dict | None) -> list[dict]:
    """`run`'s certain / likely problems that are new since `base` (the
    status line counts these)."""
    new = new_signatures(run, base)
    return [f for f in run.get("findings") or [] if f.get("severity") != "harmless"
            and f.get("confidence") in ("certain", "likely") and (f.get("technical") or {}).get("signature") in new]


def new_problems_text(n: int) -> str:
    return f"{n} new problem{'' if n == 1 else 's'} since the last run - see Troubleshoot."


def diff_manifests(a: dict | None, b: dict | None) -> dict:
    """What changed from manifest summary `a` (the baseline) to `b`, keyed by
    full_name: {added, removed: [mod], updated: [{mod, old, new, direction
    "newer" | "older"}], switched_on, switched_off: [mod] (Inactive = off),
    framework: {old, new, direction} | None, reinstalled: [mod] (same version,
    installed_at changed: shown muted)}. Order, configs and files are
    ignored."""
    out = {"added": [], "removed": [], "updated": [], "switched_on": [], "switched_off": [], "framework": None,
           "reinstalled": []}
    try:
        a, b = a or {}, b or {}

        def direction(old, new):
            return "newer" if ts.version_key(new) > ts.version_key(old) else "older"

        fa, fb = a.get("framework"), b.get("framework")
        if fa and fb and fa.get("version") != fb.get("version"):
            out["framework"] = {"old": fa, "new": fb, "direction": direction(fa.get("version"), fb.get("version"))}
        elif fa and fb and fa.get("installed_at") != fb.get("installed_at") and fa.get("installed_at") and fb.get("installed_at"):
            out["reinstalled"].append(fb)
        ma = {m["full_name"]: m for m in a.get("mods") or [] if m.get("full_name")}
        mb = {m["full_name"]: m for m in b.get("mods") or [] if m.get("full_name")}
        out["added"] = [m for n, m in mb.items() if n not in ma]
        out["removed"] = [m for n, m in ma.items() if n not in mb]
        for n, new in mb.items():
            old = ma.get(n)
            if old is None:
                continue
            if old.get("version") != new.get("version"):
                out["updated"].append({"mod": new, "old": old.get("version"), "new": new.get("version"),
                                       "direction": direction(old.get("version"), new.get("version"))})
            elif old.get("installed_at") and new.get("installed_at") and old["installed_at"] != new["installed_at"]:
                out["reinstalled"].append(new)
            if bool(old.get("enabled")) != bool(new.get("enabled")):
                out["switched_on" if new.get("enabled") else "switched_off"].append(new)
    except Exception as err:
        log(f"[runs] diff failed ({err!r}); showing no changes")
    return out
