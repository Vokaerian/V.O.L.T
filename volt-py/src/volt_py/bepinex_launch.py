"""Launching a Thunderstore/BepInEx game with a load order (THUNDERSTORE.md
§2's Run, as built for Valheim stage 3c). Qt-free and game-agnostic: the
manager screen (screens/bepinex_main_screen.py) supplies the game's facts
(valheim.py's STEAM_APPID / GAME_EXES[0] / find_game_exe) and shows the
dialogs; everything that touches disk or a process lives here, so the next
BepInEx game reuses it unchanged.

How a modded run works (the way TMM / r2modman / Gale do it, proven against a
real TMM profile - temp/handoff/2026-09-28-211853-valheim-3c-scoping.md):
  1. The load order's own Doorstop loader files - the framework package's
     root-level *.dll (winhttp.dll for Valheim) + doorstop_config.ini, read
     from the manifest's framework file list, never hardcoded - are copied
     UNCHANGED into the real game folder (inject). A same-named file already
     there is moved to <APP-ROOT>/launch-backup/ first and put back on
     cleanup, so the folder ends exactly as found.
  2. The game is started through Steam: steam.exe -applaunch <appid>
     --doorstop-enabled true --doorstop-target-assembly <tree>/BepInEx/core/
     BepInEx.Preloader.dll (Doorstop 4's dialect; 3.x's --doorstop-enable /
     --doorstop-target when <tree>/.doorstop_version is missing or older,
     r2modman's own rule). The absolute target goes on the command line, not
     into the ini, so the copied ini keeps its shipped RELATIVE target: a
     leftover injection is inert for any launch VOLT didn't start (no such
     file next to the game -> Doorstop no-ops -> vanilla). BepInEx derives
     its root from the target's path, which is what makes a load order a
     self-contained tree outside the game install.
  3. The game is never VOLT's child (steam.exe hands off to the running
     client and returns), so the screen polls `tasklist` for the game's
     image name (running_pids) until it has been seen and is gone, then
     cleanup() removes what was injected and restores what was backed up.

A launch record <APP-ROOT>/launch.json is written before the first copy and
updated after every step, removed only after a clean cleanup: recover()
(run when the manager opens and before every launch) either re-attaches to
a game still running from a previous VOLT session, or cleans up a stale
record's leftovers. A vanilla launch (start(modded=False)) injects nothing
and writes no record, but runs the same recovery and already-running checks.

Windows only for now (steam.exe, tasklist, the proxy DLL): platform_error()
says so elsewhere; Linux/Proton comes with Linux packaging (CLAUDE.md §3).
"""

import csv
import io
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .applog import clip, log
from .fsutil import read_json, write_json

RECORD_FILE = "launch.json"
BACKUP_DIR = "launch-backup"
DOORSTOP_INI = "doorstop_config.ini"
DOORSTOP_VERSION_FILE = ".doorstop_version"
PRELOADER = ("BepInEx", "core", "BepInEx.Preloader.dll")
START_TIMEOUT_S = 180  # Steam may update the game, show its launch-option chooser, or start the client itself
POLL_INTERVAL_S = 2
CLEANUP_RETRIES = 5  # a delete refused by an AV rescan / an Explorer handle: retried once a second
SCHEMA_VERSION = 1


class LaunchError(Exception):
    """A launch refused or failed, with a message fit for the user."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def platform_error() -> str | None:
    """None where launching is supported, else the reason to show."""
    if sys.platform == "win32":
        return None
    return f"Run isn't supported on {sys.platform} yet (Windows only for now)."


# ---- what gets injected ----
def inject_set(manifest: dict) -> list[str]:
    """The loader files copied beside the game exe: every ROOT-level (no
    '/') framework file ending in .dll, plus doorstop_config.ini. Skips
    .doorstop_version (a manager marker Doorstop never reads - and keeping
    it out of the game folder keeps it a reliable foreign-install signal),
    doorstop_libs/ (Linux/mac), the .sh launchers and changelog.txt."""
    files = ((manifest or {}).get("framework") or {}).get("files") or []
    return sorted(
        {f for f in files if "/" not in f and (f.lower().endswith(".dll") or f.lower() == DOORSTOP_INI)},
        key=str.lower,
    )


def preloader_path(tree_root) -> Path:
    return Path(tree_root).joinpath(*PRELOADER)


def framework_missing(tree_root, manifest: dict) -> list[str]:
    """Tree-relative names the launch needs that aren't in the tree: the
    inject set + the preloader. Empty when the framework is complete."""
    tree_root = Path(tree_root)
    names = inject_set(manifest)
    missing = [n for n in names if not (tree_root / n).is_file()]
    if not names:
        missing.append(f"{DOORSTOP_INI} / the proxy .dll (no framework files recorded)")
    if not preloader_path(tree_root).is_file():
        missing.append("/".join(PRELOADER))
    return missing


# ---- the command line ----
def doorstop_version(tree_root) -> tuple[int, ...] | None:
    """<tree>/.doorstop_version as a tuple (4.4.0 -> (4, 4, 0)); None when
    missing or unreadable."""
    try:
        text = (Path(tree_root) / DOORSTOP_VERSION_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.match(r"\s*(\d+(?:\.\d+)*)", text)
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def doorstop_args(tree_root, target=None) -> list[str]:
    """The Doorstop override arguments for this tree: version 4+ ->
    --doorstop-enabled true --doorstop-target-assembly <abs>; 3.x or no
    version file -> --doorstop-enable true --doorstop-target <abs>."""
    target = Path(target) if target else preloader_path(tree_root)
    ver = doorstop_version(tree_root)
    if ver and ver[0] >= 4:
        return ["--doorstop-enabled", "true", "--doorstop-target-assembly", str(target)]
    return ["--doorstop-enable", "true", "--doorstop-target", str(target)]


def steam_argv(steam_exe, appid: str, args=()) -> list[str]:
    """steam.exe -applaunch <appid> <args...>: Steam appends the extra
    arguments to the game's own command line (list form - Popen quotes a
    path with spaces itself)."""
    return [str(steam_exe), "-applaunch", str(appid), *map(str, args)]


# ---- the launch record ----
def record_path(app_root) -> Path:
    return Path(app_root) / RECORD_FILE


def backup_dir(app_root) -> Path:
    return Path(app_root) / BACKUP_DIR


def read_record(app_root) -> dict | None:
    p = record_path(app_root)
    try:
        rec = read_json(p)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        log(f"launch record {p} is unreadable ({err!r}); treating it as absent")
        return None
    if not isinstance(rec, dict) or not isinstance(rec.get("game_dir"), str):
        log(f"launch record {p} has no game_dir; treating it as absent")
        return None
    rec.setdefault("injected", [])
    rec.setdefault("backed_up", [])
    return rec


def write_record(app_root, record: dict) -> None:
    write_json(record_path(app_root), record)


def remove_record(app_root) -> None:
    record_path(app_root).unlink(missing_ok=True)


# ---- inject / cleanup ----
def inject(app_root, game_dir, tree_root, manifest: dict, *, load_order: str, load_order_name: str,
           exe_name: str, argv: list[str]) -> dict:
    """Copies the inject set from the tree into the game folder, backing up
    any same-named file already there. The record is written before the
    first copy and after every step, so a crash mid-way leaves an exact
    list of what to undo. On any failure everything done so far is undone
    (cleanup) and LaunchError raised."""
    game_dir, tree_root = Path(game_dir), Path(tree_root)
    names = inject_set(manifest)
    record = {
        "schema_version": SCHEMA_VERSION, "game_dir": str(game_dir), "load_order": load_order,
        "load_order_name": load_order_name, "exe_name": exe_name, "modded": True,
        "injected": [], "backed_up": [], "started_at": _now(), "argv": list(argv),
    }
    backups = backup_dir(app_root)
    try:
        write_record(app_root, record)
        for name in names:
            dest = game_dir / name
            if dest.exists():
                backups.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(backups / name))  # not os.replace: APP-ROOT and the game may be on different drives
                record["backed_up"].append(name)
                write_record(app_root, record)
                log(f"run: backed up pre-existing {name} from {game_dir} -> {backups}")
            _copy(tree_root / name, dest)
            record["injected"].append(name)
            write_record(app_root, record)
        log(f"run: injected {record['injected']} -> {game_dir} (backed up {record['backed_up']})")
    except OSError as err:
        log(f"run: inject failed at {clip(record)}: {err!r}; rolling back")
        res = cleanup(app_root, retries=1)
        log(f"run: rollback {clip(res)}")
        raise LaunchError(
            f"Couldn't copy the BepInEx loader files into the game folder ({err}). "
            f"Check that the folder is writable and that antivirus isn't quarantining the copied .dll."
        ) from err
    return record


def _copy(src: Path, dest: Path) -> None:
    # Byte-for-byte, no metadata (shutil.copy2 can fail on some Windows ACLs).
    with open(src, "rb") as f_in, open(dest, "wb") as f_out:
        while chunk := f_in.read(1 << 20):
            f_out.write(chunk)


def _retry(op, what: str, retries: int, delay: float) -> Exception | None:
    """Runs op() up to `retries` times, `delay` seconds apart, returning the
    last OSError (None on success)."""
    err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            op()
            if attempt > 1:
                log(f"run: {what} succeeded on attempt {attempt}")
            return None
        except FileNotFoundError:
            return None  # already gone / already restored: the goal state
        except OSError as e:
            err = e
            log(f"run: {what} failed (attempt {attempt} of {retries}): {e!r}")
            if attempt < retries:
                time.sleep(delay)
    return err


def cleanup(app_root, retries: int = CLEANUP_RETRIES, delay: float = 1.0) -> dict:
    """Undoes the record: deletes each injected name from the game folder,
    moves each backed-up file back, then removes the record. Only names the
    record lists are ever touched. A stuck file (retries exhausted) is left
    in `failed` and the record is rewritten with just what's left, so the
    next recovery pass retries exactly that. {removed, restored, failed}
    where failed = [(name, error text)]."""
    record = read_record(app_root)
    result: dict = {"removed": [], "restored": [], "failed": []}
    if record is None:
        return result
    game_dir, backups = Path(record["game_dir"]), backup_dir(app_root)
    for name in list(record["injected"]):
        err = _retry(lambda: os.remove(game_dir / name), f"remove {game_dir / name}", retries, delay)
        if err is None:
            result["removed"].append(name)
            record["injected"].remove(name)
        else:
            result["failed"].append((name, str(err)))
    for name in list(record["backed_up"]):
        if name in record["injected"]:
            continue  # the injected copy is still stuck there: restoring over it would fail too
        err = _retry(lambda: shutil.move(str(backups / name), str(game_dir / name)), f"restore {backups / name}", retries, delay)
        if err is None:
            result["restored"].append(name)
            record["backed_up"].remove(name)
        else:
            result["failed"].append((name, str(err)))
    if record["injected"] or record["backed_up"]:
        write_record(app_root, record)
        log(f"run: cleanup incomplete for {game_dir}: {clip(result)}; record kept for the next recovery pass")
    else:
        remove_record(app_root)
        try:
            backups.rmdir()  # only when empty
        except OSError:
            pass
        log(f"run: cleanup done for {game_dir}: removed {result['removed']}, restored {result['restored']}")
    return result


# ---- process watch ----
def parse_tasklist(text: str, exe_name: str) -> set[int]:
    """PIDs from `tasklist /FI "IMAGENAME eq <exe>" /FO CSV /NH` output: the
    CSV rows whose image name equals exe_name (case-insensitive). The
    "INFO: No tasks are running..." line is localized free text, never a
    matching row, so it parses to nothing."""
    pids: set[int] = set()
    for row in csv.reader(io.StringIO(text or "")):
        if len(row) >= 2 and row[0].strip().lower() == exe_name.lower() and row[1].strip().isdigit():
            pids.add(int(row[1]))
    return pids


def running_pids(exe_name: str) -> set[int]:
    """The PIDs of every running process with this image name (Windows;
    an empty set elsewhere or when tasklist itself fails)."""
    if sys.platform != "win32":
        return set()
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace", timeout=15,  # the no-tasks line is localized text
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as err:
        log(f"run: tasklist failed: {err!r}")
        return set()
    return parse_tasklist(out.stdout, exe_name)


def launch(argv: list[str]) -> int:
    """Starts argv detached (no console, nothing inherited) and returns its
    pid - steam.exe's own, which hands off to the client and exits; the
    game is watched by image name instead."""
    child = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return child.pid


# ---- recovery + the launch itself ----
def recover(app_root, retries: int = CLEANUP_RETRIES, delay: float = 1.0) -> dict:
    """What a leftover launch record means now: {"state": "none"} without
    one; "running" (the record's exe is still running - VOLT was restarted
    mid-game, the caller re-attaches and cleans up when it exits) with the
    record; "cleaned" / "incomplete" after cleaning up a stale record, with
    cleanup()'s result."""
    record = read_record(app_root)
    if record is None:
        return {"state": "none"}
    pids = running_pids(record.get("exe_name") or "")
    if pids:
        log(f"run: launch record from {record.get('started_at')} found and {record.get('exe_name')} is running "
            f"(pids {sorted(pids)}): re-attaching")
        return {"state": "running", "record": record, "pids": pids}
    log(f"run: stale launch record from {record.get('started_at')} ({record.get('exe_name')} not running): cleaning up "
        f"injected {record['injected']}, backed up {record['backed_up']}")
    result = cleanup(app_root, retries, delay)
    return {"state": "incomplete" if result["failed"] else "cleaned", "record": record, "result": result}


def start(app_root, game_dir, tree_root, manifest, *, appid: str, exe_name: str, steam_exe, load_order: str,
          load_order_name: str, modded: bool = True) -> dict:
    """The launch: recovery pass, refuse if the game is already running,
    then (modded) inject + Steam launch with the Doorstop arguments, or
    (vanilla) a plain Steam launch with nothing copied and no record.
    Returns {"argv", "pid", "record" (None for vanilla), "recovery"}.
    LaunchError for anything refused or failed (the folder is left as found)."""
    recovery = recover(app_root)
    if recovery["state"] == "running":
        raise LaunchError(f"{exe_name} is already running (started from a previous VOLT session) - quit it first.")
    if recovery["state"] == "incomplete":
        names = [n for n, _ in recovery["result"]["failed"]]
        raise LaunchError(
            f"Leftover loader files from the last run couldn't be removed from the game folder: {', '.join(names)}. "
            "Quit anything using them (the game, an antivirus scan) and try again."
        )
    pids = running_pids(exe_name)
    if pids:
        log(f"run: refused, {exe_name} is already running (pids {sorted(pids)})")
        raise LaunchError(f"{exe_name} is already running - quit it first.")
    if modded:
        missing = framework_missing(tree_root, manifest)
        if missing:
            raise LaunchError(
                f"The load order's BepInEx install is incomplete (missing {', '.join(missing)}). "
                "Rescan, or delete and recreate the load order."
            )
        argv = steam_argv(steam_exe, appid, doorstop_args(tree_root))
        record = inject(app_root, game_dir, tree_root, manifest, load_order=load_order, load_order_name=load_order_name,
                        exe_name=exe_name, argv=argv)
    else:
        argv, record = steam_argv(steam_exe, appid), None
    log(f"run: launching ({'modded' if modded else 'vanilla'}): {subprocess.list2cmdline(argv)}")
    try:
        pid = launch(argv)
    except OSError as err:
        log(f"run: launch failed: {err!r}")
        if record is not None:
            log(f"run: rollback after failed launch {clip(cleanup(app_root, retries=1))}")
        raise LaunchError(f"Couldn't start Steam ({err}).") from err
    log(f"run: started {argv[0]} (pid {pid}); waiting for {exe_name} (timeout {START_TIMEOUT_S}s)")
    return {"argv": argv, "pid": pid, "record": record, "recovery": recovery}
