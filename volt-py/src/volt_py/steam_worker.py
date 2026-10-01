"""Steamworks helper process (port of Electron's src/electron/lib/steamWorker.js).
Never imported by the GUI: steam_client.py runs it as a fresh subprocess, one
per Workshop operation, and ends it when the operation ends - in dev as
`python -m volt_py.steam_worker`; in a packaged (Nuitka) build as
`VOLT.exe --steam-worker`, where volt_py.main() calls main() below before any
Qt import (volt_py.STEAM_WORKER_FLAG), so the helper is the same exe with no
window and no Qt loaded.

Why a separate process: initializing the Steamworks SDK registers the calling
process with Steam as "RimWorld, running". Done in VOLT's own process, Steam's
"Stop" button would kill VOLT itself and the user would show as in-game for as
long as VOLT stayed open. Here only this short-lived helper is ever registered,
and a native crash inside the SDK takes down only the helper (reported to the
app as an ordinary error by steam_client.py).

The binding is philippj/SteamworksPy (`import steamworks`, MIT): a pure-Python
ctypes wrapper that loads a separately obtained native library at runtime. The
library reads its runtime files from the process's CURRENT WORKING DIRECTORY
first, which steam_client.py sets to its native_dir(): the bundled
<exe folder>/steamworks/ in a packaged build, else <app_root>/steamworks/:
  steam_appid.txt      the app id (294100), written by steam_client.py itself
                       on every helper start (never shipped in a release)
  SteamworksPy64.dll   built for Steamworks SDK 1.64: redist/windows in the
                       SteamworksPy repo (the old 1.6.5 release still loads, see below)
  steam_api64.dll      from THE SAME Steamworks SDK (sdk/redistributable_bin/win64).
                       The 1.64 DLL imports SteamInternal_SteamAPI_Init, which
                       RimWorld's own (2023) copy lacks - that copy only pairs
                       with the 1.6.5 release DLL. The two files go together.
The `steamworks/` package itself is found through the normal import path (the
venv; compiled into VOLT.exe in a packaged build), or - because that same cwd
is also on sys.path here - dropped into that folder as a plain source folder.
steam_client.availability() checks all of this before a helper is ever started.

The only prebuilt SteamworksPy64.dll anyone can download (release 1.6.5,
2021-11) is years older than the wrapper and lacks 26 of its exports, and the
stock loader binds every export unconditionally - so it crashes on the first
missing one. _patch_loader() makes the load tolerant and this file then fails
loud only for the exports VOLT's own actions call (REQUIRED_EXPORTS at load,
QUERY_EXPORTS per workshop_item call). See _patch_loader.

Protocol, one JSON object per line, stdin -> stdout:
  in:  {"seq": n, "action": a, "id": "<workshop id>"}
         a: subscribe | unsubscribe | install_info | is_subscribed | workshop_item | download
       {"action": "shutdown"}                     -> exits 0 (so does stdin EOF)
  out: {"seq": n, "ok": true, "value": ...} | {"seq": n, "ok": false, "error": "..."}
The protocol writes go to a private duplicate of the original stdout; the
process-level fd 1 is then pointed at stderr, so anything else that prints -
the native library's own "Setting breakpad minidump AppID" line, a stray
print() - can never corrupt a protocol line. stderr is relayed into volt.log by
steam_client.py.

The Steam client is initialized on the first job and kept for this process's
lifetime (every poll of one operation reuses it). A failed init isn't cached,
so a retry within the same operation tries again. SubscribeItem/UnsubscribeItem
and the UGC details query are asynchronous in the SDK: their results arrive
through callbacks that only fire while run_callbacks() is pumped, so each of
those actions pumps in a bounded loop (TIMING) until its callback lands. A
status read (GetItemState / GetItemInstallInfo / GetItemDownloadInfo) is
synchronous.

Stdlib only besides the binding; nothing here imports the rest of volt_py, so
the helper stays cheap to start and can't drag Qt in.
"""

import ctypes
import importlib
import io
import json
import os
import re
import sys
import time
import types

# Seconds. callback_timeout_s stays below steam_client.TIMING["job_timeout_s"]
# (30) so the specific message written here reaches the app before the
# client's generic "didn't answer" one. A dict, so a check harness can shrink it.
TIMING = {"callback_timeout_s": 25.0, "poll_s": 0.05}
# Check-harness seam: how the `steamworks` package is loaded.
env = types.SimpleNamespace(load_binding=lambda: importlib.import_module("steamworks"))

# EItemState bit flags (Steamworks SDK isteamugc.h; steamworks.EItemState has the
# same values). Kept as plain ints so item_status doesn't depend on the binding's enum.
ITEM_STATE = {
    "SUBSCRIBED": 1,
    "LEGACY_ITEM": 2,
    "INSTALLED": 4,
    "NEEDS_UPDATE": 8,
    "DOWNLOADING": 16,
    "DOWNLOAD_PENDING": 32,
}
RESULT_OK = 1  # EResult k_EResultOK

# Native exports VOLT's actions go through, checked against what the DLL really
# has once it's loaded (_patch_loader records the misses). Present in every
# prebuilt release (1.6.5 verified from its PE export table, 2026-09-28):
REQUIRED_EXPORTS = (  # subscribe / unsubscribe / install_info / is_subscribed
    "Workshop_GetNumSubscribedItems",  # SteamWorkshop.__init__ calls it eagerly (upstream #58)
    "Workshop_GetItemState", "Workshop_GetItemInstallInfo", "Workshop_GetItemDownloadInfo",
    "Workshop_SubscribeItem", "Workshop_UnsubscribeItem",
    "Workshop_SetItemSubscribedCallback", "Workshop_SetItemUnsubscribedCallback",
)
# NOT in 1.6.5 (added to the C++ shim after it): the whole UGC details query, so
# workshop_item refuses per call, and the post-subscribe priority bump, skipped.
QUERY_EXPORTS = (  # workshop_item only
    "Workshop_CreateQueryUGCDetailsRequest", "Workshop_SetQueryCompletedCallback",
    "Workshop_SendQueryUGCRequest", "Workshop_GetQueryUGCResult",
)
DOWNLOAD_EXPORTS = ("Workshop_SetDownloadItemCallback", "Workshop_DownloadItem")
# The EResult values a Workshop call realistically comes back with (steamclientpublic.h).
ERESULT_NAMES = {
    1: "k_EResultOK", 2: "k_EResultFail", 3: "k_EResultNoConnection", 8: "k_EResultInvalidParam",
    9: "k_EResultFileNotFound", 10: "k_EResultBusy", 15: "k_EResultAccessDenied", 16: "k_EResultTimeout",
    20: "k_EResultServiceUnavailable", 21: "k_EResultNotLoggedOn", 25: "k_EResultLimitExceeded",
}


class WorkerError(Exception):
    """A failure with a user-readable message (what handle() reports as `error`)."""


def eresult_text(result) -> str:
    name = ERESULT_NAMES.get(result)
    return f"{name} ({result})" if name else f"EResult {result}"


def to_item_id(id) -> int:
    """Workshop ids are unsigned 64-bit; the SDK takes a Python int. Re-checked
    here even though steam_client validated it (same regex as steam_cmd.to_workshop_id)."""
    s = ("" if id is None else str(id)).strip()
    if not re.fullmatch(r"\d{1,20}", s, re.ASCII):
        raise WorkerError(f"Not a Steam Workshop item id: {id}")
    return int(s)


def _int(x):
    """A plain int out of whatever the binding hands back: an int/IntFlag, a
    ctypes scalar (.value), or a ctypes POINTER - GetItemInstallInfo's
    'disk_size' is returned as the raw pointer, undereferenced (a known bug in
    the library's current source; .contents.value is the number). None when
    there's no number in it."""
    if x is None:
        return None
    if isinstance(x, ctypes._Pointer):
        try:
            x = x.contents
        except ValueError:  # NULL pointer
            return None
    if isinstance(x, ctypes._SimpleCData):
        x = x.value
    try:
        return int(x)
    except (TypeError, ValueError):
        pass
    try:
        return int(x.value)  # some other wrapper with a .value
    except (AttributeError, TypeError, ValueError):
        return None


def _text(x):
    """str out of a str / bytes (a ctypes c_char array field reads as bytes)."""
    if x is None:
        return None
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    return str(x)


def item_status(sw, item: int) -> dict:
    """Plain-dict status for an item (JSON-safe, so it crosses the pipe as-is;
    the JS itemStatus, snake_case). installed: on disk AND not mid-download/
    update (INSTALLED set, DOWNLOADING / DOWNLOAD_PENDING / NEEDS_UPDATE all
    clear). folder/disk_size from GetItemInstallInfo ({} when not installed),
    bytes_* from GetItemDownloadInfo ({} when not downloading)."""
    ws = sw.Workshop
    state = _int(ws.GetItemState(item)) or 0
    info = ws.GetItemInstallInfo(item) or {}
    dl = ws.GetItemDownloadInfo(item) or {}

    def has(flag: str) -> bool:
        return bool(state & ITEM_STATE[flag])

    busy = has("DOWNLOADING") or has("DOWNLOAD_PENDING")
    folder = _text(info.get("folder"))
    return {
        "id": str(item),
        "state": state,
        "subscribed": has("SUBSCRIBED"),
        "installed": has("INSTALLED") and not busy and not has("NEEDS_UPDATE"),
        "downloading": busy,
        "needs_update": has("NEEDS_UPDATE"),
        "folder": folder or None,
        "disk_size": _int(info.get("disk_size")),
        "bytes_downloaded": _int(dl.get("downloaded")),
        "bytes_total": _int(dl.get("total")),
    }


def _eprint(message: str) -> None:
    """Diagnostics -> stderr (steam_client.py logs every line)."""
    try:
        print(f"[steam worker] {message}", file=sys.stderr, flush=True)
    except Exception:
        pass


def _patch_loader(binding) -> bool:
    """Replaces STEAMWORKS._load_steamworks_api with a copy that tolerates a
    native library missing some exports. Returns whether the patch is in place.

    ponytail: workaround for a known, still-open upstream problem in
    philippj/SteamworksPy - the stock loader does an unguarded
    `getattr(self._cdll, name)` for every entry of STEAMWORKS_METHODS (the whole
    package surface, Apps..Workshop..Input), so one missing export kills the
    load; and the newest prebuilt DLL (release 1.6.5, 2021-11-14, the last of 10
    releases ever cut) predates 26 of the current wrapper's names: the SteamInput
    block (PR #89, merged 2025-02-18 - `SetInputActionManifestFilePath` is the
    one the user hits first), the UGC details query, DownloadItem, the
    dependency / key-value-tag / content-descriptor calls. Upstream issues #87
    (GetAnalogActionData, same shape, open since 2023), #37, #49, #1. Building
    the DLL needs a Steamworks Partner SDK download + MSVC, for SteamInput
    support VOLT never uses. This copy skips a missing export (one stderr line
    naming them all), records the set on the instance as `_volt_missing`, and
    raises WorkerError before the interfaces are built if a REQUIRED_EXPORTS
    name is gone. Ceiling: mirrors the upstream method body as read in the
    installed 2.0.0 package; if that shape changes (no STEAMWORKS_METHODS dict,
    no _reload_steamworks_interfaces) this steps aside and the stock loader
    runs. Upgrade path: a release built from current source makes this
    unnecessary (and harmless)."""
    cls = getattr(binding, "STEAMWORKS", None)
    methods = getattr(binding, "STEAMWORKS_METHODS", None)
    if cls is None or not isinstance(methods, dict) or not hasattr(cls, "_reload_steamworks_interfaces"):
        return False
    if getattr(getattr(cls, "_load_steamworks_api", None), "_volt_patch", False):
        return True

    def _load_steamworks_api(self):
        if not self._loaded:
            raise binding.SteamNotLoadedException("STEAMWORKS not yet loaded")
        missing = []
        for name, attrs in methods.items():
            try:
                f = getattr(self._cdll, name)
            except AttributeError:  # ctypes: "function 'X' not found"
                missing.append(name)
                continue
            if "restype" in attrs:
                f.restype = attrs["restype"]
            if "argtypes" in attrs:
                f.argtypes = attrs["argtypes"]
            setattr(self, name, f)
        self._volt_missing = frozenset(missing)
        if missing:
            _eprint(
                f"native library is missing {len(missing)} export(s) the SteamworksPy wrapper knows "
                f"(older DLL build; those interface methods are unavailable) - skipping: {', '.join(missing)}"
            )
        need = [n for n in REQUIRED_EXPORTS if n in self._volt_missing]
        if need:
            raise WorkerError(
                f"This SteamworksPy64.dll build doesn't export {', '.join(need)}, so Steam Workshop actions "
                "can't work with it. Use a newer build of philippj/SteamworksPy's native library."
            )
        self._reload_steamworks_interfaces()

    _load_steamworks_api._volt_patch = True
    cls._load_steamworks_api = _load_steamworks_api
    return True


class Worker:
    """One helper's job handler (the JS createWorker). handle() never raises."""

    def __init__(self):
        self._binding = None  # the `steamworks` module once loaded
        self._binding_error = None  # str once loading failed (cached: it won't get better)
        self._sw = None  # the initialized STEAMWORKS instance
        # Callback results keyed by item id / query handle, filled while pumping.
        self._subscribed: dict = {}
        self._unsubscribed: dict = {}
        self._queries: dict = {}
        self._missing = frozenset()  # exports the loaded DLL lacks (see _patch_loader)

    # ---- Steam client ----
    def client(self):
        """The initialized STEAMWORKS instance, created on first use. Raises
        WorkerError with the reason (binding not loadable, native library /
        steam_appid.txt missing from cwd, Steam not running or not logged in)."""
        if self._sw is not None:
            return self._sw
        if self._binding is None:
            if self._binding_error is None:
                try:
                    self._binding = env.load_binding()
                except Exception as err:
                    self._binding_error = f"{err!s}" or err.__class__.__name__
            if self._binding is None:
                raise WorkerError(
                    "The SteamworksPy library couldn't be loaded, so Steam Workshop actions are unavailable: "
                    f"{self._binding_error}"
                )
        _patch_loader(self._binding)
        try:
            sw = self._binding.STEAMWORKS()  # loads the native library; steam_appid.txt + the .dll from cwd
        except WorkerError:
            raise  # the patched loader's own message (a required export is missing)
        except Exception as err:
            raise WorkerError(
                f"The Steamworks native library couldn't be loaded from {os.getcwd()} ({err!s}). "
                "steam_appid.txt, SteamworksPy64.dll and steam_api64.dll must all be in that folder, and "
                "steam_api64.dll must come from the same Steamworks SDK as SteamworksPy64.dll "
                "(RimWorld's copy only fits the old 1.6.5 release)."
            ) from err
        try:
            sw.initialize()  # SteamAPI_Init: SteamNotRunningException / SteamConnectionException / GenericSteamException
        except Exception as err:
            raise WorkerError(f"Couldn't connect to Steam - is it running and logged in? ({err!s})") from err
        ws = sw.Workshop
        self._missing = getattr(sw, "_volt_missing", frozenset())
        # Registered once: SubscribeItem/UnsubscribeItem/SendQueryUGCRequest
        # raise SetupRequired without a callback in place, and the results have
        # nowhere else to land.
        ws.SetItemSubscribedCallback(self._on_subscribed)
        ws.SetItemUnsubscribedCallback(self._on_unsubscribed)
        if not self._missing.intersection(QUERY_EXPORTS):
            ws.SetQueryUGCRequestCallback(self._on_query_completed)
        self._sw = sw
        return sw

    def _require(self, names, what: str) -> None:
        """WorkerError naming the exports `what` needs that this DLL build lacks."""
        gone = [n for n in names if n in self._missing]
        if gone:
            raise WorkerError(
                f"Steam {what} isn't available with this SteamworksPy64.dll build "
                f"(it doesn't export {', '.join(gone)})."
            )

    # ---- callbacks (fire inside run_callbacks(), on this thread) ----
    def _on_subscribed(self, result) -> None:  # SubscriptionResult: result (EResult), publishedFileId
        self._subscribed[_int(result.publishedFileId)] = _int(result.result)

    def _on_unsubscribed(self, result) -> None:
        self._unsubscribed[_int(result.publishedFileId)] = _int(result.result)

    def _on_query_completed(self, result) -> None:  # SteamUGCQueryCompleted_t: handle, result, numResultsReturned, ...
        self._queries[_int(result.handle)] = (_int(result.result), _int(result.numResultsReturned) or 0)

    def _on_download(self, result) -> None:  # DownloadItemResult_t; fires for any app's downloads - nothing to do
        pass

    def _pump(self, poll, what: str):
        """Pumps run_callbacks() until poll() returns something other than None
        (the awaited callback landed), or TIMING callback_timeout_s passes ->
        WorkerError. The binding never pumps by itself (no event loop here)."""
        timeout = TIMING["callback_timeout_s"]
        deadline = time.monotonic() + timeout
        while True:
            self._sw.run_callbacks()
            value = poll()
            if value is not None:
                return value
            if time.monotonic() >= deadline:
                raise WorkerError(f"Steam didn't confirm {what} within {round(timeout)} seconds.")
            time.sleep(TIMING["poll_s"])

    @staticmethod
    def _sdk(what: str, fn):
        """Calls one SDK step, rewording an SDK failure so it names the action.
        A WorkerError (already user-readable) passes through unchanged."""
        try:
            return fn()
        except WorkerError:
            raise
        except Exception as err:
            raise WorkerError(f"Steam {what} failed: {err!s}") from err

    # ---- actions ----
    def subscribe(self, item: int) -> dict:
        """Subscribe, wait for Steam's confirmation, then ask for a high-priority
        download. The download itself is async: the caller polls install_info
        until installed."""
        sw = self.client()
        ws = sw.Workshop
        self._subscribed.pop(item, None)
        self._sdk("subscribe", lambda: ws.SubscribeItem(item))
        result = self._sdk("subscribe", lambda: self._pump(lambda: self._subscribed.pop(item, None), "the subscription"))
        if result != RESULT_OK:
            raise WorkerError(f"Steam subscribe failed: {eresult_text(result)}")
        if not self._missing.intersection(DOWNLOAD_EXPORTS):  # not in the 1.6.5 DLL: then no bump, no noise
            try:
                # Subscribing queues it anyway; this only bumps priority. The wrapper requires a callback.
                ws.DownloadItem(item, True, callback=self._on_download)
            except Exception as err:
                _eprint(f"download request for {item} failed (subscribe still stands): {err!s}")
        return self._sdk("status check", lambda: item_status(sw, item))

    def unsubscribe(self, item: int) -> dict:
        """A confirmed unsubscribe still isn't proof it took (RimSort has an open
        bug where it silently doesn't): the caller verifies with is_subscribed."""
        sw = self.client()
        ws = sw.Workshop
        self._unsubscribed.pop(item, None)
        self._sdk("unsubscribe", lambda: ws.UnsubscribeItem(item))
        result = self._sdk("unsubscribe", lambda: self._pump(lambda: self._unsubscribed.pop(item, None), "the unsubscribe"))
        if result != RESULT_OK:
            raise WorkerError(f"Steam unsubscribe failed: {eresult_text(result)}")
        return self._sdk("status check", lambda: item_status(sw, item))

    def install_info(self, item: int) -> dict:
        sw = self.client()
        return self._sdk("status check", lambda: item_status(sw, item))

    def download(self, item: int) -> dict:
        """(Re-)requests a high-priority download of an item, the same call
        subscribe's priority bump makes (Sync re-asks when Steam never starts
        a subscribed item's download). Never raises for a missing export or a
        refused call - an error would end the caller's operation, and its
        helper is the one that can see the item: {"requested": bool,
        "reason": str | None, "status": item_status}."""
        sw = self.client()
        gone = [n for n in DOWNLOAD_EXPORTS if n in self._missing]
        requested, reason = False, None
        if gone:
            reason = f"this SteamworksPy64.dll build doesn't export {', '.join(gone)}"
        else:
            try:
                requested = bool(sw.Workshop.DownloadItem(item, True, callback=self._on_download))
            except Exception as err:
                reason = f"Steam download request failed: {err!s}"
        return {"requested": requested, "reason": reason, "status": self._sdk("status check", lambda: item_status(sw, item))}

    def is_subscribed(self, item: int) -> bool:
        return self.install_info(item)["subscribed"]

    def workshop_item(self, item: int) -> dict:
        """The item's listing as the logged-in client sees it (Scan Issues' title
        fallback when the keyless Web API says not found): {found, title,
        visibility, banned}. One UGC details query: create -> send -> pump until
        SteamUGCQueryCompleted_t for our handle -> read result 0 -> release."""
        sw = self.client()
        self._require(QUERY_EXPORTS, "workshop item lookup")
        ws = sw.Workshop
        handle = self._sdk("workshop item lookup", lambda: _int(ws.CreateQueryUGCDetailsRequest([item])))
        if handle is None:
            raise WorkerError("Steam workshop item lookup failed: no query handle")
        try:
            self._queries.pop(handle, None)
            self._sdk("workshop item lookup", lambda: ws.SendQueryUGCRequest(handle))
            result, count = self._sdk(
                "workshop item lookup", lambda: self._pump(lambda: self._queries.pop(handle, None), "the Workshop item lookup")
            )
            if result != RESULT_OK:
                raise WorkerError(f"Steam workshop item lookup failed: {eresult_text(result)}")
            if count < 1:
                return {"found": False, "title": None}
            details = self._sdk("workshop item lookup", lambda: ws.GetQueryUGCResult(handle, 0))  # SteamUGCDetails_t
            if _int(details.result) != RESULT_OK:  # per-item result: k_EResultFileNotFound for an unknown id
                return {"found": False, "title": None}
            return {
                "found": True,
                "title": _text(details.title),
                "visibility": _int(details.visibility),
                "banned": bool(details.banned),
            }
        finally:
            release = getattr(ws, "ReleaseQueryUGCRequest", None)
            if release is not None:
                try:
                    release(handle)
                except Exception as err:
                    _eprint(f"releasing UGC query {handle} failed: {err!s}")

    ACTIONS = {
        "subscribe": subscribe,
        "unsubscribe": unsubscribe,
        "install_info": install_info,
        "is_subscribed": is_subscribed,
        "workshop_item": workshop_item,
        "download": download,
    }

    def handle(self, msg) -> dict:
        """{action, id} -> {"ok": True, "value"} | {"ok": False, "error"}. Never raises."""
        try:
            action = msg.get("action") if isinstance(msg, dict) else None
            fn = self.ACTIONS.get(action) if isinstance(action, str) else None
            if fn is None:
                raise WorkerError(f"Unknown Steam helper action: {action}")
            item = to_item_id(msg.get("id"))
            return {"ok": True, "value": fn(self, item)}
        except Exception as err:
            return {"ok": False, "error": f"{err!s}" or err.__class__.__name__}

    def close(self) -> None:
        """SteamAPI_Shutdown if the client was ever initialized (exiting would
        unregister us with Steam anyway; this just makes it tidy)."""
        sw, self._sw = self._sw, None
        unload = getattr(sw, "unload", None)
        if unload is not None:
            try:
                unload()
            except Exception as err:
                _eprint(f"unload failed: {err!s}")


def serve(inp, out, worker=None) -> int:
    """The message loop: one request per line of `inp`, one reply per line to
    `out` (flushed). Ends on {"action": "shutdown"} or EOF (the app is gone).
    A line that isn't a JSON object is reported to stderr and skipped."""
    worker = worker if worker is not None else Worker()
    try:
        for raw in inp:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                _eprint(f"ignoring a non-JSON line on stdin: {raw[:200]!r}")
                continue
            if not isinstance(msg, dict):
                _eprint(f"ignoring a non-object line on stdin: {raw[:200]!r}")
                continue
            if msg.get("action") == "shutdown":
                return 0
            reply = {"seq": msg.get("seq"), **worker.handle(msg)}
            out.write(json.dumps(reply, ensure_ascii=False, default=str) + "\n")
            out.flush()
        return 0
    finally:
        worker.close()


EXIT_NO_STDIO = 3  # a windowed exe started without the three pipes: nothing to talk over


def main() -> int:
    # A windowed (packaged) exe gets sys.stdin/stdout None when it was started
    # without standard handles (pythonw.exe behaviour). steam_client always
    # passes three pipes, so this only fires for a hand-started exe - exit with
    # a distinct code rather than a traceback nobody can see.
    if sys.stdin is None or sys.stdout is None or sys.stderr is None:
        _eprint("no standard input/output to speak the protocol over; this process must be started by steam_client.py")
        return EXIT_NO_STDIO
    # Protocol writes get their own handle on the original stdout; fd 1 itself
    # then points at stderr so nothing else can write into the protocol stream.
    proto = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n")
    try:
        sys.stdout.flush()
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    except OSError as err:
        _eprint(f"couldn't redirect fd 1 to stderr ({err!s}); stray prints could corrupt the protocol")
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.append(cwd)  # `python -m` already puts it first; explicit so the entry point doesn't matter
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:  # Windows: steam_api64.dll next to SteamworksPy64.dll resolves for sure
        try:
            add_dll_directory(cwd)
        except OSError as err:
            _eprint(f"add_dll_directory({cwd}) failed: {err!s}")
    inp = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    return serve(inp, proto)


if __name__ == "__main__":
    sys.exit(main())
