"""Launching RimWorld: the Modded / Vanilla buttons (RIMWORLD.md PLAN item 10,
stage 1 - 0.6.15; Offline-mod hot-swap, stage 3 - 0.6.17). Qt-free; the screen (screens/rimworld_main_screen.py)
shows the dialogs and watches the game, everything touching disk or a
process lives here. Windows only for now, like bepinex_launch.py, whose
game-agnostic pieces are reused (platform_error, steam_argv, launch,
running_pids, LaunchError, the poll / start-timeout constants).

How a run starts (start):
  - Steam install (steam_appid.txt in the game folder, paths.has_steam_appid -
    the rule the rest of the RimWorld code uses): `steam.exe -applaunch
    294100 [args]`. Steam appends the user's own Steam launch options, so
    VOLT's argument coexists with them (hardware spike S2/S3, 2026-10-01).
  - Anything else (GOG / DRM-free): the game exe itself with the args, a
    detached subprocess (never os.startfile, which can't pass arguments).
  - Vanilla (0.6.18, user decision: "a completely clean install, only Core +
    DLCs, no mods of any kind"): `-savedatafolder=<APP-ROOT>/vanilla-data`,
    a persistent VOLT-owned data root shared by every Vanilla run (never a
    load order's, never the real data folder), whose Config/ModsConfig.xml
    is rewritten before each run to exactly the installed official ids
    (prepare_vanilla) - so its saves / settings are its own. Modded for a
    load order without own game data: no extra argument at all - the game
    uses its normal data folder and whatever ModsConfig.xml was last pushed.
  - Either data-folder run: a -savedatafolder in the user's own Steam launch
    options would compete with VOLT's (user_savedata_options; the screen
    asks before launching).
  - Modded with own game data (the manifest's opt-in own_data): first
    prepare_data writes <LO>/data/Config/ModsConfig.xml from the load
    order's SAVED active list (Push's id filtering, mods_config.push_mods_
    config), then `-savedatafolder=<LO>/data`. That folder becomes the
    game's whole data root (Config\\, Saves\\, Scenarios\\, mod data folders -
    spike S1-S3), so saves and settings are per load order; everything but
    ModsConfig.xml is left for the game to create (fresh defaults, user
    decision 2026-10-01: nothing is copied from the real folder).
The game is never VOLT's child (steam.exe hands off and exits), so the
screen polls running_pids(exe name) until it has been seen and is gone.

Offline mods at Modded Run (stage 3, 0.6.17; user decisions 2026-10-01):
  - Only for a load order with own game data ON and Offline entries, and only
    the entries whose packageId is in the SAVED active list (link_plan).
    Vanilla, and Modded with own data off, never link anything.
  - preflight() before any change: each copy <LO>/local-mods/<folder> a real
    folder with its .volt-pinned marker; Mods/<folder> not a link already;
    <APP-ROOT>/launch-backup/<folder> free.
  - swap(): a real folder already at <game>/Mods/<folder> (a SteamCMD / GOG /
    hand-made copy) is moved to <APP-ROOT>/launch-backup/<folder> - never
    left inside Mods, where the game would scan it (spike S4) - then
    Mods/<folder> becomes a junction to the copy (same folder name: the
    per-mod settings key, spike S4/S5; a Mods copy beats the Workshop one).
    Junction only (link_fn, injectable for the tests): a failing link rolls
    back everything done so far and refuses the launch, no copy fallback.
  - The launch record <APP-ROOT>/launch.json (RimWorld's own APP-ROOT, apart
    from Valheim's) is written before the first change and after every
    step; cleanup() removes ONLY recorded links whose target is still the
    recorded one (never through a link, never a real folder), then moves the
    backups back, retrying a locked path; the record goes only after a clean
    cleanup, else it stays and recover() retries. recover() (manager open,
    every start) re-attaches to a game still running, else cleans up.
"""

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from . import mods_config, offline_mods, paths
from .applog import clip, log
from .bepinex_launch import (  # noqa: F401  (re-exported for the screen)
    CLEANUP_RETRIES, POLL_INTERVAL_S, POLL_SLOW_S, START_TIMEOUT_S, LaunchError, _remove_link, _retry, backup_dir,
    launch, platform_error, query_pids, record_path, remove_record, running_pids, steam_argv, write_record,
)
from .fsutil import is_link, read_json, read_text
from .vdf import get_ci, parse_vdf

DATA_DIR = "data"  # <LO>/data: the load order's own game data root
VANILLA_DIR = "vanilla-data"  # <APP-ROOT>/vanilla-data: Vanilla's own clean data root (0.6.18)
CONFIG_DIR = "Config"
SAVEDATA_ARG = "-savedatafolder="


def data_dir(lo_dir) -> Path:
    """The load order's own data root: <LO folder>/data."""
    return Path(lo_dir) / DATA_DIR


def vanilla_data_dir(app_root) -> Path:
    """Vanilla's own data root: <APP-ROOT>/vanilla-data."""
    return Path(app_root) / VANILLA_DIR


def user_savedata_options(steam_root) -> list[tuple[str, str]]:
    """(Steam user id, launch options) for every Steam user on this machine
    whose own RimWorld launch options (userdata/<id>/config/localconfig.vdf,
    UserLocalConfigStore > Software > Valve > Steam > apps > 294100 >
    LaunchOptions) contain -savedatafolder. A missing / unreadable /
    malformed file is skipped (no warning); no steam_root: []."""
    out: list[tuple[str, str]] = []
    if not steam_root:
        return out
    try:
        users = sorted(os.listdir(Path(steam_root) / "userdata"))
    except OSError:
        return out
    for uid in users:
        try:
            data = parse_vdf(read_text(Path(steam_root) / "userdata" / uid / "config" / "localconfig.vdf"))
        except (OSError, ValueError):
            continue
        node = data
        for key in ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps", paths.STEAM_APPID):
            node = get_ci(node, key)
        opts = get_ci(node, "LaunchOptions")
        if isinstance(opts, str) and "-savedatafolder" in opts.lower():
            out.append((uid, opts))
    return out


def savedata_arg(folder) -> str:
    """-savedatafolder=<folder> with forward slashes (the spike's form; the
    game logs it that way too). No quotes inside: argv goes to Popen as a
    list, and list2cmdline quotes the WHOLE argument when the path has a
    space - exactly what the game's readme asks for."""
    return SAVEDATA_ARG + str(folder).replace("\\", "/")


def run_args(lo_dir, *, modded: bool, own_data: bool) -> list[str]:
    """The game arguments VOLT adds: the data folder for a Modded run with
    own game data, nothing otherwise (Vanilla / own data off)."""
    return [savedata_arg(data_dir(lo_dir))] if modded and own_data and lo_dir is not None else []


def build_argv(game_dir, args=(), steam_exe=None) -> list[str]:
    """Steam install -> steam.exe -applaunch 294100 <args>; else the game exe
    with <args>. LaunchError when steam.exe / the exe can't be found."""
    if paths.has_steam_appid(game_dir):
        steam_exe = steam_exe or paths.find_steam_exe()
        if steam_exe is None:
            looked = ", ".join(str(p) for p in paths.steam_root_candidates()) or "(nowhere)"
            raise LaunchError(f"Couldn't find steam.exe - this RimWorld is a Steam install, started through Steam. "
                              f"Looked in: {looked}")
        return steam_argv(steam_exe, paths.STEAM_APPID, args)
    exe = paths.find_game_exe(game_dir)
    if exe is None:
        raise LaunchError(f"No RimWorld executable found in {game_dir or '(game folder not set)'}")
    return [str(exe), *map(str, args)]


def _seed(real_config_dir, game_dir) -> tuple[str | None, list[str]]:
    """(version, knownExpansions) for a brand-new own ModsConfig.xml: from the
    real game's ModsConfig.xml (read only), the version falling back to the
    game's Version.txt. An unreadable real file just means no seed."""
    version, known = None, []
    if real_config_dir:
        try:
            real = mods_config.read_mods_config(real_config_dir)
            version, known = real["version"], real["known_expansions"]
        except (OSError, ValueError, ET.ParseError) as err:
            log(f"run: real ModsConfig.xml in {real_config_dir} unreadable ({err!r}); not seeding from it")
    if not version and game_dir:
        version = paths.read_game_version(game_dir)
    return version, known


def prepare_data(lo_dir, active_ids, real_config_dir=None, game_dir=None) -> dict:
    """Writes <LO>/data/Config/ModsConfig.xml from `active_ids` (the SAVED
    list) through push_mods_config - the same id filtering as Push, only
    <activeMods> replaced in an existing file (rolling .volt-backup beside
    it). A first run creates Config/ and seeds <version> / <knownExpansions>
    (_seed). Returns push_mods_config's result plus "seeded"."""
    return _write_mods_config(data_dir(lo_dir), active_ids, real_config_dir, game_dir)


def prepare_vanilla(app_root, official_ids, real_config_dir=None, game_dir=None) -> dict:
    """Vanilla's ModsConfig.xml (<APP-ROOT>/vanilla-data/Config): exactly
    `official_ids` (Core + the installed DLCs, release order), rewritten
    before every Vanilla run so nothing enabled in-game last time stays."""
    return _write_mods_config(vanilla_data_dir(app_root), official_ids, real_config_dir, game_dir)


def _write_mods_config(root, active_ids, real_config_dir=None, game_dir=None) -> dict:
    cfg = Path(root) / CONFIG_DIR
    seeded = not mods_config.mods_config_path(cfg).exists()
    version, known = _seed(real_config_dir, game_dir) if seeded else (None, [])
    cfg.mkdir(parents=True, exist_ok=True)
    result = mods_config.push_mods_config(cfg, active_ids, game_version=version, known_expansions=known)
    log(f"run: wrote {result['count']} mods to {result['path']} (skipped {result['skipped']}"
        + (f"; new file seeded with version {version!r}, {len(known)} known expansions)" if seeded else ")"))
    return {**result, "seeded": seeded}


# ---- Offline mods: the plan, preflight, swap, cleanup, recover ----
SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_junction(link, target) -> None:
    """The real link layer: a Windows directory junction at `link` pointing
    to `target` (no admin rights needed; spike S4). OSError on failure."""
    import _winapi  # Windows only; the tests inject their own link_fn

    _winapi.CreateJunction(str(target), str(link))


def _norm(p) -> str:
    s = str(p)
    if s.startswith("\\\\?\\"):  # os.readlink on a junction: the \\?\ device-path form
        s = s[4:]
    return os.path.normcase(os.path.normpath(os.path.abspath(s)))


def link_points_to(link, target) -> bool:
    """`link` is a symlink / junction whose target is `target`."""
    try:
        return is_link(link) and _norm(os.readlink(link)) == _norm(target)
    except (OSError, ValueError):
        return False


def link_plan(lo_dir, entries: dict, active_ids, *, own_data: bool) -> list[dict]:
    """What a Modded run links: the Offline entries whose packageId is in the
    SAVED active list (`active_ids`, in its order), only with own game data
    on. [{"id", "folder", "target": <LO>/local-mods/<folder>}]; entries with
    a bad folder name are left to preflight via their id."""
    if not own_data or not entries or lo_dir is None:
        return []
    out = []
    for mod_id in dict.fromkeys(str(i).lower() for i in active_ids or ()):
        e = entries.get(mod_id)
        if e is not None:
            out.append({"id": mod_id, "folder": e.get("folder"), "target": offline_mods.local_mods_dir(lo_dir) / str(e.get("folder"))})
    return out


def preflight(app_root, game_dir, lo_dir, plan: list[dict], names: dict | None = None) -> list[str]:
    """Problems that refuse the run before anything changes (one line each,
    naming the mod): the Offline copy missing / not a real folder / without
    its marker; Mods/<folder> already a link (not ours - recover() has just
    removed ours); <APP-ROOT>/launch-backup/<folder> already taken."""
    names = names or {}
    mods_dir = Path(game_dir) / "Mods"
    problems = []
    for item in plan:
        label = names.get(item["id"]) or item["id"]
        try:
            target = offline_mods.copy_path(lo_dir, item["folder"])
        except offline_mods.OfflineError as err:
            problems.append(f"{label}: {err}")
            continue
        if is_link(target) or not target.is_dir() or not (target / offline_mods.MARKER).is_file():
            problems.append(f"{label}: its Offline copy is missing or unreadable ({target}) - see Scan issues")
            continue
        link = mods_dir / item["folder"]
        if is_link(link):
            problems.append(f"{label}: {link} is already a link VOLT didn't make - remove it first")
        elif os.path.lexists(link) and os.path.lexists(backup_dir(app_root) / item["folder"]):
            problems.append(f"{label}: {link} would be moved aside, but {backup_dir(app_root) / item['folder']} "
                            "already exists (left from an earlier run?) - move it away first")
    return problems


def read_record(app_root) -> dict | None:
    """RimWorld's launch record, or None (absent / unreadable / not ours)."""
    p = record_path(app_root)
    try:
        rec = read_json(p)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        log(f"run: launch record {p} is unreadable ({err!r}); treating it as absent")
        return None
    if not isinstance(rec, dict) or not isinstance(rec.get("game_dir"), str):
        log(f"run: launch record {p} has no game_dir; treating it as absent")
        return None
    rec["linked"] = [x for x in rec.get("linked") or [] if isinstance(x, dict) and x.get("path") and x.get("target")]
    rec["moved"] = [x for x in rec.get("moved") or [] if isinstance(x, dict) and x.get("from") and x.get("to")]
    return rec


def swap(app_root, game_dir, plan: list[dict], *, load_order: str, exe_name: str, link_fn=None) -> dict:
    """Links each planned copy into <game>/Mods/<folder>, moving a real folder
    already there to <APP-ROOT>/launch-backup/<folder> first. The record is
    written before the first change and after every step. Any failure: what
    was done is undone (cleanup) and LaunchError raised - no copy fallback."""
    link_fn = link_fn or make_junction
    mods_dir = Path(game_dir) / "Mods"
    record = {"schema_version": SCHEMA_VERSION, "game": "rimworld", "game_dir": str(game_dir),
              "load_order": load_order, "exe_name": exe_name, "modded": True, "started_at": _now(),
              "linked": [], "moved": []}
    current = None
    try:
        write_record(app_root, record)
        for item in plan:
            current = item
            link = mods_dir / item["folder"]
            if os.path.lexists(link):  # a real folder (preflight refused links): aside, outside Mods
                aside = backup_dir(app_root) / item["folder"]
                aside.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(link), str(aside))
                record["moved"].append({"from": str(link), "to": str(aside)})
                write_record(app_root, record)
                log(f"run: moved {link} aside -> {aside}")
            link_fn(link, Path(item["target"]).resolve())
            record["linked"].append({"path": str(link), "target": str(Path(item["target"]).resolve())})
            write_record(app_root, record)
        log(f"run: linked {len(record['linked'])} Offline mods into {mods_dir} (moved aside {len(record['moved'])}): "
            f"{clip([x['path'] for x in record['linked']])}")
    except OSError as err:
        log(f"run: linking failed at {current and current['folder']}: {err!r}; rolling back")
        res = cleanup(app_root, retries=1)
        log(f"run: rollback {clip(res)}")
        left = "" if not (res["failed"] or res["left"]) else (
            " Some of it couldn't be undone - VOLT retries at the next start: "
            + ", ".join(x[0] for x in res["failed"] + res["left"]) + ".")
        raise LaunchError(
            f"Couldn't link the Offline mod {current and current['folder']} into the game's Mods folder ({err}). "
            "Nothing was launched." + left) from err
    return record


def cleanup(app_root, retries: int = CLEANUP_RETRIES, delay: float = 1.0) -> dict:
    """Undoes the record: each recorded link is removed only while it still
    points to its recorded target (a real folder or another link there now
    is left alone and reported in `left`); then each moved-aside folder is
    moved back, unless something else took its place (then it stays in
    launch-backup, reported in `left`). A locked path is retried; one still
    failing stays in the record (`failed`) for the next recover().
    {"unlinked", "restored", "failed": [(path, error)], "left": [(path, why)]}."""
    record = read_record(app_root)
    result: dict = {"unlinked": [], "restored": [], "failed": [], "left": []}
    if record is None:
        return result
    for x in list(record["linked"]):
        path = Path(x["path"])
        if not os.path.lexists(path):
            record["linked"].remove(x)  # already gone
            continue
        if not link_points_to(path, x["target"]):
            why = "is a real folder now" if not is_link(path) else "is a link to somewhere else now"
            result["left"].append((str(path), f"{why}; left as it is"))
            record["linked"].remove(x)
            continue
        err = _retry(lambda: _remove_link(path), f"remove link {path}", retries, delay)
        if err is None and not os.path.lexists(path):
            result["unlinked"].append(str(path))
            record["linked"].remove(x)
        else:
            result["failed"].append((str(path), str(err or "still there")))
    still_linked = {x["path"] for x in record["linked"]}
    for x in list(record["moved"]):
        src, dest = Path(x["to"]), Path(x["from"])
        if x["from"] in still_linked:
            continue  # our link is still stuck there: restoring over it would fail too
        if not os.path.lexists(src):
            record["moved"].remove(x)
            result["left"].append((str(src), "the moved-aside folder is gone; nothing to restore"))
            continue
        if os.path.lexists(dest):
            record["moved"].remove(x)
            result["left"].append((str(src), f"not moved back: {dest} exists now; kept in launch-backup"))
            continue
        err = _retry(lambda: shutil.move(str(src), str(dest)), f"restore {src}", retries, delay)
        if err is None and os.path.lexists(dest):
            result["restored"].append(str(dest))
            record["moved"].remove(x)
        else:
            result["failed"].append((str(src), str(err or "not restored")))
    if record["linked"] or record["moved"]:
        write_record(app_root, record)
        log(f"run: cleanup incomplete: {clip(result)}; record kept for the next recovery pass")
    else:
        remove_record(app_root)
        try:
            backup_dir(app_root).rmdir()  # only when empty
        except OSError:
            pass
        log(f"run: cleanup done: unlinked {len(result['unlinked'])}, restored {len(result['restored'])}"
            + (f", left {clip(result['left'])}" if result["left"] else ""))
    return result


def recover(app_root, retries: int = CLEANUP_RETRIES, delay: float = 1.0) -> dict:
    """{"state": "none"} without a record; "running" (the record's game is
    still running - VOLT was restarted mid-run: re-attach, clean up when it
    exits) with the record; else the stale record is cleaned up: "cleaned"
    / "incomplete" with cleanup()'s result."""
    record = read_record(app_root)
    if record is None:
        return {"state": "none"}
    pids = running_pids(record.get("exe_name") or "")
    if pids:
        log(f"run: launch record from {record.get('started_at')} and {record.get('exe_name')} is running "
            f"(pids {sorted(pids)}): re-attaching")
        return {"state": "running", "record": record, "pids": pids}
    log(f"run: stale launch record from {record.get('started_at')}: cleaning up {len(record['linked'])} links, "
        f"{len(record['moved'])} moved-aside folders")
    result = cleanup(app_root, retries, delay)
    return {"state": "incomplete" if result["failed"] else "cleaned", "record": record, "result": result}


def start(game_dir, *, modded: bool, lo_dir=None, own_data: bool = False, active_ids=(), real_config_dir=None,
          steam_exe=None, app_root=None, offline_entries=None, load_order: str | None = None, names=None,
          link_fn=None, official_ids=None) -> dict:
    """The launch: recovery pass (app_root given: a game still running from
    an earlier VOLT session, or leftovers that can't be cleaned, refuse),
    refuse if the game is already running, build the command line
    (preflight: exe / steam.exe), Modded + own_data: preflight the Offline
    links (link_plan of `offline_entries` over the SAVED `active_ids`),
    write the own data, swap the links in; then start it detached (a failed
    start undoes the swap). {"argv", "pid", "exe_name", "data_dir" (None
    without own data), "linked": count, "recovery"}. LaunchError for
    anything refused or failed (the Mods folder left as found)."""
    recovery = recover(app_root) if app_root is not None else {"state": "none"}
    if recovery["state"] == "running":
        raise LaunchError(f"{recovery['record'].get('exe_name')} is already running (started from a previous VOLT "
                          "session) - quit it first.")
    if recovery["state"] == "incomplete":
        raise LaunchError("Offline mods from the last run couldn't be removed from the game's Mods folder: "
                          + ", ".join(p for p, _ in recovery["result"]["failed"])
                          + ". Close anything using them (the game, Explorer, an antivirus scan) and try again.")
    exe = paths.find_game_exe(game_dir)
    if exe is None:
        raise LaunchError(f"No RimWorld executable found in {game_dir or '(game folder not set)'}")
    pids = running_pids(exe.name)
    if pids:
        log(f"run: refused, {exe.name} is already running (pids {sorted(pids)})")
        raise LaunchError(f"{exe.name} is already running - quit it first.")
    vanilla = not modded and app_root is not None  # the clean Vanilla (0.6.18); without app_root: the old plain launch
    args = [savedata_arg(vanilla_data_dir(app_root))] if vanilla else run_args(lo_dir, modded=modded, own_data=own_data)
    argv = build_argv(game_dir, args, steam_exe)
    data = vanilla_data_dir(app_root) if vanilla else data_dir(lo_dir) if args else None
    plan = link_plan(lo_dir, offline_entries or {}, active_ids, own_data=own_data) if modded and app_root else []
    if plan:
        problems = preflight(app_root, game_dir, lo_dir, plan, names)
        if problems:
            log(f"run: Offline preflight refused: {clip(problems)}")
            raise LaunchError("Can't link this load order's Offline mods into the game's Mods folder:\n"
                              + "\n".join(problems))
    if vanilla:
        try:
            prepare_vanilla(app_root, official_ids or [], real_config_dir, game_dir)
        except (OSError, ValueError) as err:
            log(f"run: preparing {data} failed: {err!r}")
            raise LaunchError(f"Couldn't write the clean Vanilla mod list into {data} ({err}).") from err
    elif data is not None:
        try:
            prepare_data(lo_dir, active_ids, real_config_dir, game_dir)
        except (OSError, ValueError) as err:
            log(f"run: preparing {data} failed: {err!r}")
            raise LaunchError(f"Couldn't write this load order's mod list into {data} ({err}).") from err
    if plan:
        swap(app_root, game_dir, plan, load_order=load_order or "", exe_name=exe.name, link_fn=link_fn)
    log(f"run: launching ({'modded' if modded else 'vanilla'}{', own data ' + str(data) if data else ''}"
        f"{f', {len(plan)} Offline mods linked' if plan else ''}): {subprocess.list2cmdline(argv)}")
    try:
        pid = launch(argv)
    except OSError as err:
        log(f"run: launch failed: {err!r}")
        if plan:
            log(f"run: rollback after failed launch {clip(cleanup(app_root, retries=1))}")
        raise LaunchError(f"Couldn't start {Path(argv[0]).name} ({err}).") from err
    log(f"run: started {argv[0]} (pid {pid}); waiting for {exe.name} (timeout {START_TIMEOUT_S}s)")
    return {"argv": argv, "pid": pid, "exe_name": exe.name, "data_dir": data, "linked": len(plan),
            "recovery": recovery}
