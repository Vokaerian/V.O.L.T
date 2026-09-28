"""Steam-client operation flows, pure Python - no Qt (the Steam half of
Electron's src/renderer/src/lists.js: usesSteamCmd / subscribeReady /
unsubscribeKind / runPool / steamSubscribeAndWait / syncSteamCmdMods, plus
App.jsx unsubscribeNow's unsubscribe-verify sequence and main.js's
steam:deleteItemFolder). steam_client.py is the per-call primitive (one
Steam helper process per operation); these are the sequences the screen
runs on a background thread: subscribe and wait for the download, unsubscribe
and verify it took, and Sync to Steam's two passes.

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
import threading
import time

from .applog import log as _applog
from .fsutil import remove_tree_best_effort
from .mods import workshop_id
from .paths import has_steam_appid, workshop_dir_for
from .steam_client import SteamClientError
from .steam_cmd import to_workshop_id


def uses_steam_cmd(acquire_via) -> bool:
    """Whether a mode downloads with SteamCMD into Mods (modes 'steamcmd', 'gog')."""
    return acquire_via in ("steamcmd", "gog")


def subscribe_ready(acquire_via, steam_available) -> bool:
    """Whether Subscribe can run at all for this mode: SteamCMD needs no Steam
    install, client or binding (so GOG works too); the Steam-client mode needs
    steam_client.availability() to be true. The row must also be a
    not_found_workshop_id entry."""
    return uses_steam_cmd(acquire_via) or bool(steam_available)


def unsubscribe_kind(mod) -> str | None:
    """How Unsubscribe removes a scanned mod: 'steam' for a real Steam
    subscription (source 'workshop': unsubscribe, verify, then delete its
    folder), 'delete' for a SteamCMD download (source 'steamcmd' or 'gog':
    never subscribed, so only its files are deleted - an explicit user action,
    unlike Sync's automatic delete, which never touches a 'gog' copy), None
    for anything that isn't a Workshop mod."""
    if not workshop_id(mod):
        return None
    return "delete" if mod["source"] in ("steamcmd", "gog") else "steam"


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


def sync_steamcmd_mods(mods: dict, steam, *, tries: int = 5, wait_s: float = 1.0, poll_s: float = 2.0,
                       timeout_s: float = 120.0, concurrency: int = 5, subscribe_concurrency: int | None = None,
                       on_progress=None) -> dict:
    """"Sync to Steam" (lists.js syncSteamCmdMods): every SteamCMD-downloaded
    mod in the scan (source 'steamcmd': a <game>/Mods/<id> folder whose marker
    records the temporary 'steamcmd' mode; a 'gog'-mode copy is permanent and
    never touched) becomes a real Steam subscription, then its copy is deleted
    once Steam's own download is on disk (it takes over in the Workshop scan
    root).

    Two passes, because registering a subscription is fast while waiting for
    Steam's download is slow and serialized by Steam itself:
     1. Subscribe pass, up to `subscribe_concurrency` (default `concurrency`)
        at once: subscribe, then verify it took the way Unsubscribe does
        (re-check is_subscribed up to `tries` times, `wait_s` apart), then
        steam.release(wid) the item's Steam helper so a long list doesn't
        pile them up. A failure here is final for this run (failed).
     2. Install pass, over the items pass 1 verified, up to `concurrency` at
        once: poll install_info every `poll_s` until installed (up to
        `timeout_s`), then delete_copy(mod["path"]). The copy is what the game
        loads, so it's never deleted before Steam's is on disk: a download not
        confirmed (timeout or install_info error) keeps the copy and is
        pending. So is an item whose delete didn't finish: delete_copy
        (steam_cmd.delete_item) is best effort and reports a locked file as
        gone False rather than raising - only gone True counts as synced. The
        next sync picks every pending item up again (subscribing is
        idempotent).
    A failed item is left untouched for the next sync; no retries within a
    run. on_progress(done, total), if given, runs once per item as its FINAL
    outcome lands (failed in pass 1, or synced / pending / failed in pass 2),
    never for the subscribe step alone. Returns {"total", "synced", "pending",
    "failed": [{"wid", "error"}]}, each list in completion order."""
    log = _log_of(steam)
    by_wid: dict[str, dict] = {}
    for m in mods.values():
        wid = workshop_id(m) if m.get("source") == "steamcmd" else None
        if wid and wid not in by_wid:
            by_wid[wid] = m
    if subscribe_concurrency is None:
        subscribe_concurrency = concurrency
    total = len(by_wid)
    synced: list[str] = []
    pending: list[str] = []
    failed: list[dict] = []
    verified: set[str] = set()
    lock = threading.Lock()
    done = 0  # items whose final outcome has landed

    def finish() -> None:
        nonlocal done
        with lock:
            done += 1
            d = done
        if on_progress is not None:
            on_progress(d, total)

    def fail(wid: str, err: BaseException) -> None:
        error = _text(err)
        log(f"sync {wid}: FAILED - {error}")
        failed.append({"wid": wid, "error": error})

    log(
        f"sync: {total} SteamCMD mod(s) to sync: {', '.join(by_wid)}"
        + (f"; subscribe pass up to {max(1, min(subscribe_concurrency, total))} at once, then install pass up to "
           f"{max(1, min(concurrency, total))} at once" if total else "")
    )

    # Pass 1: register every subscription.
    def subscribe_pass(item) -> None:
        wid, mod = item
        try:
            steam.subscribe(wid)
            log(f"sync {wid} ({mod['id']}): subscribe call returned, verifying")
            ok = False
            for i in range(tries):
                if ok:
                    break
                if i:
                    steam.sleep(wait_s)
                ok = bool(steam.is_subscribed(wid))
                log(f"sync {wid}: isSubscribed check {i + 1}/{tries} -> {ok}")
            if not ok:
                raise SteamClientError("Steam doesn't list it as subscribed")
            verified.add(wid)
            log(f"sync {wid}: verified subscribed (subscribe pass); its download is waited on in the install pass")
        except Exception as err:  # noqa: BLE001 - one item's failure never ends the run
            fail(wid, err)
            finish()
        finally:
            release = getattr(steam, "release", None)
            if release is not None:
                try:
                    release(wid)
                except Exception as err:  # noqa: BLE001
                    log(f"sync {wid}: couldn't release its Steam helper ({_text(err)}); it ends on its own idle timeout")

    run_pool(by_wid.items(), subscribe_concurrency, subscribe_pass)
    log(f"sync: subscribe pass done: {len(verified)} of {total} subscribed, {len(failed)} failed; "
        "waiting for Steam's downloads")

    # Pass 2: wait for Steam's download, then delete the copy. Original order
    # (Steam downloads roughly in the order it was subscribed).
    def install_pass(item) -> None:
        wid, mod = item
        try:
            installed = False
            last = ""
            try:
                for i in range(math.ceil(timeout_s / poll_s)):
                    if installed:
                        break
                    if i:
                        steam.sleep(poll_s)
                    st = steam.install_info(wid)
                    installed = _flag(st, "installed")
                    now = json.dumps(st)
                    if now != last:
                        log(f"sync {wid}: install status {now}")
                    last = now
            except Exception as err:  # noqa: BLE001 - can't confirm the download: keep the copy, like a timeout
                log(f"sync {wid}: install status check failed: {_text(err)}")
            if not installed:
                log(f"sync {wid}: PENDING - subscribed but download not confirmed, SteamCMD copy kept")
                pending.append(wid)
                return
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
            fail(wid, err)
        finally:
            finish()

    run_pool([(w, m) for w, m in by_wid.items() if w in verified], concurrency, install_pass)
    log(f"sync done: {len(synced)} synced, {len(pending)} pending, {len(failed)} failed of {total}")
    return {"total": total, "synced": synced, "pending": pending, "failed": failed}
