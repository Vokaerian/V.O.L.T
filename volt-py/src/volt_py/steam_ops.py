"""Steam-client operation flows, pure Python - no Qt (the Steam half of
Electron's src/renderer/src/lists.js: usesSteamCmd / subscribeReady /
unsubscribeKind / runPool / steamSubscribeAndWait / syncSteamCmdMods, plus
App.jsx unsubscribeNow's unsubscribe-verify sequence and main.js's
steam:deleteItemFolder). steam_client.py is the per-call primitive (one
Steam helper process per operation); these are the sequences the screen
runs on a background thread: subscribe and wait for the download, unsubscribe
and verify it took, and Sync to Steam's per-item flow.

Every flow takes the Steam calls as a `steam` object (the JS passed a plain
object of functions) rather than calling steam_client directly, so the check
harness drives the real flow against fakes, exactly as lists.js's own tests
did: steam.subscribe(wid) / install_info(wid) / is_subscribed(wid) /
unsubscribe(wid) -> steam_client's return values; steam.delete_copy(path) ->
steam_cmd.delete_item's dict; steam.release(wid) (optional);
steam.sleep(seconds); steam.now() (optional, monotonic seconds); steam.log
(optional, else volt.log). The screen builds it in
RimWorldMainScreen._steam_ops. Failures raise steam_client.SteamClientError
(user-readable), or whatever the steam calls raised.

Blocking, stdlib only; every step is logged with its real answer
(CLAUDE.md §10).
"""

import json
import math
import os
import threading
import time

from .applog import log as _applog
from .fsutil import find_child_ci, is_dir, remove_tree_best_effort
from .mods import workshop_id
from .paths import has_steam_appid, workshop_dir_for
from .steam_client import SteamClientError
from .steam_cmd import to_workshop_id
from .steamcmd_marker import LEGACY_MARKER, MARKER


def uses_steam_cmd(acquire_via) -> bool:
    """Whether a mode downloads with SteamCMD into Mods (modes 'steamcmd', 'gog')."""
    return acquire_via in ("steamcmd", "gog")


def subscribe_ready(acquire_via, steam_available) -> bool:
    """Whether Subscribe can run at all for this mode: SteamCMD needs no Steam
    install, client or binding (so GOG works too); the Steam-client mode needs
    steam_client.availability() to be true. The row must also be a
    not_found_workshop_id entry."""
    return uses_steam_cmd(acquire_via) or bool(steam_available)


def fetch_label(acquire_via) -> str:
    """What fetching a pending / not-found Workshop row is called wherever
    the user sees it - the painted row button, the context-menu item, the
    import notices, the toast titles of that fetch, the help text - by the
    acquisition mode in effect (user decision 2026-10-01, 0.6.14, "rename
    all three together"): 'Download' in the SteamCMD modes ('steamcmd',
    'gog': a SteamCMD download into Mods, never a Steam subscription),
    'Subscribe' in the Steam-client mode, where that same button / path
    really subscribes on Steam. The one source for that word."""
    return "Download" if uses_steam_cmd(acquire_via) else "Subscribe"


def unsubscribe_kind(mod) -> str | None:
    """How Unsubscribe removes a scanned mod: 'steam' for a real Steam
    subscription (source 'workshop': unsubscribe, verify, then delete its
    folder), 'delete' for a SteamCMD download (source 'steamcmd' or 'gog':
    never subscribed, so only its files are deleted - an explicit user action,
    unlike Sync's automatic delete, which never touches a 'gog' copy), None
    for anything that isn't a Workshop mod - and for an Offline copy
    (source 'pinned'): it is the load order's own folder, never removed here."""
    if not workshop_id(mod) or mod["source"] == "pinned":
        return None
    return "delete" if mod["source"] in ("steamcmd", "gog") else "steam"



def menu_pair(acquire_via, mod) -> tuple[str | None, str | None]:
    """The mod right-click menu's acquisition items, after Rules... (RIMWORLD.md
    #52 as re-decided by the user 2026-09-30): the GOG mode ('gog': permanent
    SteamCMD copies, no Steam) shows Fetch / Delete; the SteamCMD-then-sync
    ('steamcmd') and Steam-client ('steamworks') modes share Subscribe plus a
    label that follows the row's real state: 'Delete' for a SteamCMD / GOG
    copy (unsubscribe_kind 'delete' - never a Steam subscription), else
    'Unsubscribe' (a real subscription, or greyed for anything that isn't a
    Workshop mod). What Subscribe DOES differs by mode (user decision
    2026-10-01, 0.6.13): in 'steamworks' it subscribes a pending row on the
    Steam client; in 'steamcmd' it is Sync to Steam for one installed
    SteamCMD copy, and the SteamCMD fetch of a pending row moved to a
    'Download' item right below it (menu_download). A None means the item
    is left out of the menu (user decision 2026-10-01, 0.6.14): on a row
    that isn't an installed mod (`mod` None: pending / not found) the
    entries that could never apply are hidden rather than greyed - the
    second item in every mode (nothing to unsubscribe or delete), and in
    'steamcmd' the first too (nothing installed to sync; Download is the
    row's item). Labels only; the screen decides what's enabled."""
    if mod is None:
        return ("Fetch" if acquire_via == "gog" else None if acquire_via == "steamcmd" else "Subscribe"), None
    if acquire_via == "gog":
        return "Fetch", "Delete"
    return "Subscribe", "Delete" if unsubscribe_kind(mod) == "delete" else "Unsubscribe"


def menu_download(acquire_via) -> str | None:
    """The 'Download' item under Subscribe in the SteamCMD-then-sync mode
    (what Subscribe used to do there: fetch a pending / not-found row with
    SteamCMD into Mods). None in the other modes: 'gog' has Fetch for that,
    and in 'steamworks' Subscribe itself is the download."""
    return "Download" if acquire_via == "steamcmd" else None

def workshop_page(wid) -> str:
    """App.jsx workshopPage: the item's Workshop page, opened by the Steam client."""
    return f"steam://url/CommunityFilePage/{wid}"


_END = object()


def run_pool(items, concurrency, fn) -> None:
    """Runs fn(item) for every item, at most `concurrency` at once: a worker
    pool of daemon threads, each runner pulling the next item off one shared
    iterator (so items start in order and a slow one never holds up the
    rest). fn must handle its own errors - a runner whose fn raises stops
    pulling (the others carry on), and the first error is re-raised once every
    runner has finished. Returns once every fn has."""
    items = list(items)
    queue = iter(items)
    lock = threading.Lock()
    errors: list[BaseException] = []

    def pull():
        with lock:
            return next(queue, _END)

    def runner() -> None:
        while (item := pull()) is not _END:
            try:
                fn(item)
            except BaseException as err:  # noqa: BLE001 - re-raised below, the pool itself never dies silently
                errors.append(err)
                return

    threads = [
        threading.Thread(target=runner, name=f"steam-pool-{i + 1}", daemon=True)
        for i in range(max(1, min(int(concurrency), len(items))))
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]


def _log_of(steam):
    return getattr(steam, "log", None) or _applog


def _text(err: BaseException) -> str:
    return str(err) or repr(err)


def _flag(status, key: str) -> bool:
    return bool(isinstance(status, dict) and status.get(key))


def _progress(status) -> bool:
    """Whether Steam is doing anything at all with the item: a nonzero item
    state (subscribed / installed / needs update / downloading / pending), or
    download bytes reported. Real hardware 2026-10-01: for an item new to the
    client, GetItemState read 0 (not subscribed) for ~5 s after a confirmed
    subscribe while GetItemDownloadInfo already reported bytes_total, then
    bytes_downloaded - the client lags its own subscription; the Workshop
    page showed it subscribed all along."""
    if not isinstance(status, dict):
        return False
    return bool(status.get("state")) or _flag(status, "downloading") or bool(status.get("bytes_total")) or bool(status.get("bytes_downloaded"))


def steam_subscribe_and_wait(wid: str, steam, *, poll_s: float = 2.0, timeout_s: float = 120.0,
                             not_subscribed_polls: int = 3) -> dict:
    """Steam-client-mode subscribe for one Workshop item, as Subscribe has
    always done it (lists.js steamSubscribeAndWait): subscribe (Steam also
    starts a high-priority download), then poll install_info every `poll_s`
    until installed. Raises SteamClientError when it can't finish: Steam
    reports it not subscribed for `not_subscribed_polls` polls in a row
    (missing / private / removed item), or `timeout_s` passes (Steam may still
    finish in the background). Returns the final (installed) status."""
    log = _log_of(steam)
    now = getattr(steam, "now", None) or time.monotonic
    st = steam.subscribe(wid)
    last = json.dumps(st)
    log(f"subscribe {wid}: status {last}")
    deadline = now() + timeout_s
    not_subscribed = 0
    while not _flag(st, "installed"):
        not_subscribed = 0 if _flag(st, "subscribed") or _flag(st, "downloading") else not_subscribed + 1
        if not_subscribed >= not_subscribed_polls:
            raise SteamClientError("Steam doesn't list it as subscribed (the item may not exist, or may be private or removed)")
        if now() >= deadline:
            raise SteamClientError(
                f"Steam hadn't finished downloading it after {timeout_s:g} seconds "
                "(it may still finish in the background - rescan later)"
            )
        steam.sleep(poll_s)
        st = steam.install_info(wid)
        cur = json.dumps(st)
        if cur != last:
            log(f"subscribe {wid}: status changed to {cur}")
        last = cur
    log(f"subscribe {wid}: done, installed")
    return st


def unsubscribe_verified(wid: str, name: str, steam, *, tries: int = 5, wait_s: float = 1.0) -> None:
    """Unsubscribe, then verify Steam really dropped it (App.jsx unsubscribeNow;
    RimSort's silent-failure bug): re-check is_subscribed up to `tries` times,
    `wait_s` apart. Raises SteamClientError while Steam still lists it, so the
    caller never touches the item's files then. `name`: the mod's name, for
    the message."""
    log = _log_of(steam)
    log(f"unsubscribe {wid} ({name}): starting")
    steam.unsubscribe(wid)
    still = True
    for i in range(tries):
        if not still:
            break
        if i:
            steam.sleep(wait_s)
        still = bool(steam.is_subscribed(wid))
        log(f"unsubscribe {wid}: isSubscribed check {i + 1}/{tries} -> {still}")
    if still:
        log(f"unsubscribe {wid}: FAILED - still subscribed, files left alone")
        raise SteamClientError(
            f"Steam still lists you as subscribed to {name} after unsubscribing, so its files were left alone. "
            f"Try again, or unsubscribe from its Workshop page in Steam: {workshop_page(wid)}"
        )


def delete_workshop_folder(game_dir, wid) -> dict:
    """Unsubscribe's cleanup (main.js steam:deleteItemFolder): best-effort
    delete of <Workshop content>/<id> (a locked file is skipped, not fatal;
    fsutil.remove_tree_best_effort). Takes an id, never a path, so it can't
    be pointed anywhere else. Returns {"path", "removed", "skipped", "gone"}."""
    if not game_dir or not has_steam_appid(game_dir):
        raise SteamClientError("This isn't a Steam install, so there's no Workshop folder to clean up.")
    dir = workshop_dir_for(game_dir) / to_workshop_id(wid)
    return {"path": dir, **remove_tree_best_effort(dir)}


def _tree_size(root) -> tuple[int, int]:
    """(files, bytes) under `root`, VOLT's SteamCMD marker files not counted;
    an unreadable entry is skipped."""
    files = size = 0
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            if name in (MARKER, LEGACY_MARKER):
                continue
            try:
                size += os.path.getsize(os.path.join(dirpath, name))
                files += 1
            except OSError:
                pass
    return files, size


def steam_copy_problem(folder, copy_path, min_ratio: float = 0.9) -> str | None:
    """Why Steam's install `folder` (install_info's) can't replace the SteamCMD
    copy at `copy_path` yet, or None when it can: it exists, has
    About/About.xml (case-insensitive, as the scan finds it) and holds at
    least `min_ratio` of the copy's bytes. Real hardware 2026-09-30: Steam
    reported an item installed (state 4, its manifest's disk_size) over a
    folder with no About.xml, and Sync deleted the only good copy.
    ponytail: a byte ratio, not a per-file compare; an author shrinking the
    mod by >10% between the SteamCMD and the Steam download reads as
    incomplete (the copy is kept, never lost)."""
    if not folder:
        return "Steam reported no install folder"
    if not is_dir(folder):
        return f"Steam's folder {folder} doesn't exist"
    about = find_child_ci(folder, "About")
    if not (about and find_child_ci(about, "About.xml")):
        return f"Steam's folder {folder} has no About/About.xml"
    steam_files, steam_bytes = _tree_size(folder)
    copy_files, copy_bytes = _tree_size(copy_path)
    if steam_bytes < copy_bytes * min_ratio:
        return (f"Steam's folder {folder} holds {steam_files} file(s), {steam_bytes} bytes; the SteamCMD copy "
                f"{copy_path} holds {copy_files} file(s), {copy_bytes} bytes")
    return None


def sync_steamcmd_mods(mods: dict, steam, *, tries: int = 5, wait_s: float = 1.0, poll_s: float = 2.0,
                       timeout_s: float = 120.0, concurrency: int = 5, redownload_after_s: float = 10.0,
                       redownload_every_s: float = 15.0, redownloads: int = 3, never_started_s: float = 60.0,
                       verify_grace_s: float = 30.0, copy_problem=steam_copy_problem, on_progress=None) -> dict:
    """"Sync to Steam" (lists.js syncSteamCmdMods): every SteamCMD-downloaded
    mod in the scan (source 'steamcmd': a <game>/Mods/<id> folder whose marker
    records the temporary 'steamcmd' mode; a 'gog'-mode copy is permanent and
    never touched) becomes a real Steam subscription, then its copy is deleted
    once Steam's own download is on disk (it takes over in the Workshop scan
    root).

    One flow per item, up to `concurrency` items at once, all of it in the
    ONE Steam helper that did the subscribe (steam_client keys the operation
    by id: subscribe starts it, every install_info joins it). Real hardware
    2026-09-30: a FRESH helper can't see an item another helper just
    subscribed - state 0, not subscribed, for well over 30 s, restarting it
    doesn't help - while the subscribing helper always sees it. So:
     1. subscribe; verify it took: the subscribe's own status, else re-read
        install_info up to `tries` times, `wait_s` apart (install_info, not
        is_subscribed: a False is_subscribed ends the operation, losing the
        helper). Not subscribed after that AND no sign of progress in any of
        those reads (_progress: state 0, no download bytes) = failed, final
        for this run. Not subscribed but progressing (real hardware
        2026-10-01: state 40 from the subscribe, then state 0 with
        bytes_total / bytes_downloaded growing - the client lags its own
        subscription for a few seconds) = carry on into step 2 unverified;
        the subscribed bit is then expected to appear during the polls, and
        an unbroken no-progress streak of `never_started_s` before it ever
        does is the "Steam doesn't list it as subscribed" failure instead of
        step 2's pending-not-downloaded outcome.
     2. poll install_info every `poll_s` until installed (up to `timeout_s`),
        then delete_copy(mod["path"]). Real hardware 2026-09-30: Steam
        sometimes registers the subscribe but never starts the download - the
        subscribing helper itself then reads state 0 (not subscribed, not
        downloading) for good. So once a poll streak of state 0 reaches
        `redownload_after_s`, steam.download(wid) re-requests a high-priority
        download in the same helper, every `redownload_every_s`, at most
        `redownloads` times; a streak reaching `never_started_s` stops the
        wait early (pending, not downloaded). Only an unbroken state-0 streak
        counts: an item whose state moves (or reports download bytes,
        _progress) keeps the full `timeout_s`.
        Installed isn't enough to delete the copy: `copy_problem(folder,
        mod["path"])` (steam_copy_problem) must pass too. While it fails the
        copy is kept, the download re-requested once, and the folder
        re-checked every `poll_s` for up to `verify_grace_s`; still failing =
        pending, listed in `incomplete`. The copy is what the game loads, so it's
        never deleted before Steam's is on disk: a download not confirmed
        (timeout or install_info error) keeps the copy and is pending. So is
        an item whose delete didn't finish: delete_copy (steam_cmd.delete_item)
        is best effort and reports a locked file as gone False rather than
        raising - only gone True counts as synced. The next sync picks every
        pending item up again (subscribing is idempotent).
     3. steam.release(wid), on every exit path (an installed status already
        ended the operation; release is then a logged no-op). App quit ends
        whatever is left (steam_client.stop_all).
    A failed item is left untouched for the next sync; no retries within a
    run. on_progress(done, total), if given, runs once per item as its final
    outcome lands. Returns {"total", "synced", "pending", "not_downloaded",
    "incomplete": [{"wid", "name"}], "failed": [{"wid", "error"}]}, each list
    in completion order; not_downloaded and incomplete are the parts of
    pending whose Steam download wasn't confirmed / whose Steam copy wasn't a
    complete mod (the rest of pending is a copy that couldn't be deleted), so
    the summary can say which. On real hardware a subscribed item's download
    sometimes didn't start until Steam was restarted (2026-09-30)."""
    log = _log_of(steam)
    by_wid: dict[str, dict] = {}
    for m in mods.values():
        wid = workshop_id(m) if m.get("source") == "steamcmd" else None
        if wid and wid not in by_wid:
            by_wid[wid] = m
    total = len(by_wid)
    synced: list[str] = []
    pending: list[str] = []
    not_downloaded: list[str] = []
    incomplete: list[dict] = []  # {"wid", "name"}: Steam says installed, its folder isn't a complete mod
    failed: list[dict] = []
    lock = threading.Lock()
    done = 0  # items whose final outcome has landed

    def finish() -> None:
        nonlocal done
        with lock:
            done += 1
            d = done
        if on_progress is not None:
            on_progress(d, total)

    log(
        f"sync: {total} SteamCMD mod(s) to sync: {', '.join(by_wid)}"
        + (f"; up to {max(1, min(concurrency, total))} at once, each in one Steam helper from subscribe to install"
           if total else "")
    )

    def sync_item(item) -> None:
        wid, mod = item
        try:
            try:
                st = steam.subscribe(wid)
                log(f"sync {wid} ({mod['id']}): subscribe returned {json.dumps(st)}")
                ok = _flag(st, "subscribed")
                progressing = _progress(st)
                for i in range(tries if not ok else 0):
                    if i:
                        steam.sleep(wait_s)
                    st = steam.install_info(wid)
                    ok = _flag(st, "subscribed")
                    progressing = progressing or _progress(st)
                    log(f"sync {wid}: subscribed check {i + 1}/{tries} -> {ok}")
                    if ok:
                        break
                if not ok and not progressing:
                    raise SteamClientError("Steam doesn't list it as subscribed")
            except Exception as err:  # noqa: BLE001 - one item's failure never ends the run
                error = _text(err)
                log(f"sync {wid}: FAILED - {error}")
                failed.append({"wid": wid, "error": error})
                return
            if ok:
                log(f"sync {wid}: verified subscribed; waiting for Steam's download in the same Steam helper")
            else:
                log(f"sync {wid}: not listed as subscribed yet, but Steam is working on it ({json.dumps(st)}); waiting in "
                    f"the same Steam helper for the subscription to show (the client lags a fresh subscription) - "
                    f"{never_started_s:g}s of nothing happening fails it")
            installed = _flag(st, "installed")
            last = json.dumps(st)
            dl = {"fn": getattr(steam, "download", None)}

            def request_download() -> None:
                try:
                    r = dl["fn"](wid)
                except Exception as err:  # noqa: BLE001 - the polls go on
                    r = {"requested": False, "reason": _text(err)}
                requested = r.get("requested") if isinstance(r, dict) else r
                reason = r.get("reason") if isinstance(r, dict) else None
                log(f"sync {wid}: download request -> requested {requested}" + (f" ({reason})" if reason else ""))
                if reason and "doesn't export" in reason:
                    dl["fn"] = None  # the old 1.6.5 DLL: no DownloadItem, nothing more to ask
            zero = 0.0  # seconds of unbroken state 0 (nothing subscribed / downloading / installed)
            asked, asked_at = 0, 0.0
            try:
                for _ in range(math.ceil(timeout_s / poll_s)):
                    if installed:
                        break
                    steam.sleep(poll_s)
                    st = steam.install_info(wid)
                    installed = _flag(st, "installed")
                    now = json.dumps(st)
                    if now != last:
                        log(f"sync {wid}: install status {now}")
                    last = now
                    if not ok and _flag(st, "subscribed"):
                        ok = True
                        log(f"sync {wid}: now listed as subscribed (after {zero:g}s of state 0)")
                    moving = installed or _flag(st, "subscribed") or _progress(st)
                    zero = 0.0 if moving else zero + poll_s
                    if zero >= never_started_s:
                        break
                    if (dl["fn"] is not None and asked < redownloads and zero >= redownload_after_s
                            and (not asked or zero - asked_at >= redownload_every_s)):
                        asked += 1
                        asked_at = zero
                        log(f"sync {wid}: state 0 for {zero:g}s after a verified subscribe; re-requesting the download "
                            f"({asked}/{redownloads})")
                        request_download()
            except Exception as err:  # noqa: BLE001 - can't confirm the download: keep the copy, like a timeout
                log(f"sync {wid}: install status check failed: {_text(err)}")
            if not installed and zero >= never_started_s and not ok:
                raise SteamClientError("Steam doesn't list it as subscribed")  # never did, and nothing moved for never_started_s
            if not installed and zero >= never_started_s:
                log(f"sync {wid}: PENDING - subscribed on Steam, but Steam hasn't started the download after "
                    f"{zero:g}s (state 0 since); stopped waiting, SteamCMD copy kept")
                pending.append(wid)
                not_downloaded.append(wid)
                return
            if not installed:
                log(f"sync {wid}: PENDING - {'subscribed' if ok else 'in progress on Steam (never listed as subscribed)'} "
                    "but download not confirmed, SteamCMD copy kept")
                pending.append(wid)
                not_downloaded.append(wid)
                return
            folder = st.get("folder") if isinstance(st, dict) else None
            problem = copy_problem(folder, mod["path"])
            if problem:
                log(f"sync {wid}: Steam reports it installed, but its copy isn't complete: {problem}; SteamCMD copy kept, "
                    f"re-checking for up to {verify_grace_s:g}s")
                if dl["fn"] is not None:
                    log(f"sync {wid}: re-requesting the download (Steam's copy incomplete)")
                    request_download()
                waited = 0.0
                while problem and waited < verify_grace_s:
                    steam.sleep(poll_s)
                    waited += poll_s
                    problem = copy_problem(folder, mod["path"])
                if problem:
                    log(f"sync {wid}: PENDING - Steam's copy is incomplete ({problem}); SteamCMD copy kept - restart "
                        "Steam or verify RimWorld's files in Steam, then Sync again")
                    pending.append(wid)
                    incomplete.append({"wid": wid, "name": mod.get("name") or mod["id"]})
                    return
                log(f"sync {wid}: Steam's copy is complete now (after {waited:g}s)")
            r = None
            why = ""
            try:
                r = steam.delete_copy(mod["path"])
            except Exception as err:  # noqa: BLE001
                why = _text(err)
            if isinstance(r, dict) and r.get("gone") is True:
                synced.append(wid)
                log(f"sync {wid}: SUBSCRIBED and installed; deleted SteamCMD copy {mod['path']}")
                return
            if not why:
                skipped = r.get("skipped") if isinstance(r, dict) and isinstance(r.get("skipped"), list) else []
                why = f"folder still on disk, {len(skipped)} item(s) couldn't be removed (locked or in use?)"
                if skipped:
                    shown = "; ".join(f"{s['path']} ({s['error']})" for s in skipped[:5])
                    more = f"; +{len(skipped) - 5} more" if len(skipped) > 5 else ""
                    why += f": {shown}{more}"
            log(f"sync {wid}: PENDING - subscribed and installed on Steam, but its SteamCMD copy {mod['path']} was NOT "
                f"deleted ({why}); the next sync retries the delete")
            pending.append(wid)
        except Exception as err:  # noqa: BLE001
            error = _text(err)
            log(f"sync {wid}: FAILED - {error}")
            failed.append({"wid": wid, "error": error})
        finally:
            release = getattr(steam, "release", None)
            if release is not None:
                try:
                    release(wid)
                except Exception as err:  # noqa: BLE001
                    log(f"sync {wid}: couldn't release its Steam helper ({_text(err)}); it ends on its own idle timeout")
            finish()

    run_pool(by_wid.items(), concurrency, sync_item)
    log(f"sync done: {len(synced)} synced, {len(pending)} pending, {len(failed)} failed of {total}")
    return {"total": total, "synced": synced, "pending": pending, "not_downloaded": not_downloaded,
            "incomplete": incomplete, "failed": failed}
