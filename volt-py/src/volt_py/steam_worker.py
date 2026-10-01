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

The SDK is reached directly, through stdlib ctypes, via the flat C API that
Valve's redistributable client library exports (steam_api_flat.h: one
`SteamAPI_ISteamUGC_<Method>(self, ...)` per interface method, the versioned
accessors `SteamAPI_SteamUGC_v021()` / `SteamAPI_SteamUtils_v010()` for the
interface pointers, `SteamAPI_InitFlat` for init). No wrapper library, no
third-party binding (0.6.12; VOLT bundled philippj/SteamworksPy's native
wrapper DLL + Python package through 0.6.11). The library reads its runtime
files from the process's CURRENT WORKING DIRECTORY, which steam_client.py sets
to its native_dir(): the bundled <exe folder>/steamworks/ in a packaged build,
else <app_root>/steamworks/:
  steam_appid.txt      the app id (294100), written by steam_client.py itself
                       on every helper start (never shipped in a release)
  steam_api64.dll      Valve's redistributable from Steamworks SDK 1.64
                       (sdk/redistributable_bin/win64), bundled by
                       tools/release.py; SteamApi.FUNCTIONS names the exports
                       this file needs, and an older copy (RimWorld's own 2023
                       one, say) fails loud at load naming what it lacks.
steam_client.availability() checks all of this before a helper is ever started.

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
so a retry within the same operation tries again. SubscribeItem /
UnsubscribeItem / SendQueryUGCRequest are asynchronous in the SDK: each returns
a SteamAPICall_t handle whose result struct is fetched once
ISteamUtils::IsAPICallCompleted says so (polled in a bounded loop, TIMING,
pumping the SDK each pass - DISPATCH below says how). A status read
(GetItemState / GetItemInstallInfo / GetItemDownloadInfo) is synchronous.

Stdlib only; nothing here imports the rest of volt_py, so the helper stays
cheap to start and can't drag Qt in.
"""

import ctypes
import io
import json
import os
import re
import sys
import time
import types
from ctypes import POINTER, c_bool, c_char, c_float, c_int, c_int32, c_uint32, c_uint64, c_void_p

# Seconds. callback_timeout_s stays below steam_client.TIMING["job_timeout_s"]
# (30) so the specific message written here reaches the app before the
# client's generic "didn't answer" one. A dict, so a check harness can shrink it.
TIMING = {"callback_timeout_s": 25.0, "poll_s": 0.05}
# How the SDK is pumped while a call result is awaited (SteamApi.pump):
#   "callbacks"  SteamAPI_RunCallbacks() each pass (nothing is registered, so
#                it only services the pipe); the result is read through
#                ISteamUtils::IsAPICallCompleted / GetAPICallResult.
#   "manual"     the SDK's manual-dispatch mode for language bindings
#                (steam_api.h "Manual callback loop"): SteamAPI_ManualDispatch_
#                Init() before init, then RunFrame + GetNextCallback /
#                FreeLastCallback each pass, every message dropped (the result
#                is still read through ISteamUtils). Must not mix with
#                RunCallbacks.
# One-line switch, both paths typed and bound either way; real hardware decides.
DISPATCH = "callbacks"
# Check-harness seams: how the native library is loaded (the real thing is
# ctypes.CDLL on the file in cwd; the harness hands in a fake with the same
# exports) and what "cwd" is (the harness runs the Worker in-process).
env = types.SimpleNamespace(load_library=lambda path: ctypes.CDLL(path), cwd=os.getcwd)

# Valve's redistributable client library per platform (sdk/redistributable_bin/<os>).
# Windows (64-bit) is what VOLT targets; the others are the SDK's names, unverified here.
LIBRARY_FILES = {"win32": "steam_api64.dll", "linux": "libsteam_api.so", "darwin": "libsteam_api.dylib"}
# Callback structs are packed to 8 on Windows and 4 on Linux/macOS
# (steamclientpublic.h VALVE_CALLBACK_PACK_LARGE / _SMALL); a wrong value
# misreads every result struct, so this follows the platform, not a constant.
CALLBACK_PACK = 4 if sys.platform.startswith(("linux", "darwin", "freebsd")) else 8

# EItemState bit flags (isteamugc.h). Plain ints: item_status needs no enum.
ITEM_STATE = {
    "SUBSCRIBED": 1,
    "LEGACY_ITEM": 2,
    "INSTALLED": 4,
    "NEEDS_UPDATE": 8,
    "DOWNLOADING": 16,
    "DOWNLOAD_PENDING": 32,
}
RESULT_OK = 1  # EResult k_EResultOK
INVALID_API_CALL = 0  # k_uAPICallInvalid
INVALID_UGC_QUERY_HANDLE = 0xFFFFFFFFFFFFFFFF  # k_UGCQueryHandleInvalid
# Callback ids (steam_api_internal.h: k_iSteamRemoteStorageCallbacks = 1300,
# k_iSteamUGCCallbacks = 3400) of the result structs read below.
SUBSCRIBE_CALLBACK = 1300 + 13  # RemoteStorageSubscribePublishedFileResult_t
UNSUBSCRIBE_CALLBACK = 1300 + 15  # RemoteStorageUnsubscribePublishedFileResult_t
QUERY_CALLBACK = 3400 + 1  # SteamUGCQueryCompleted_t
# The EResult values a Workshop call realistically comes back with (steamclientpublic.h).
ERESULT_NAMES = {
    1: "k_EResultOK", 2: "k_EResultFail", 3: "k_EResultNoConnection", 8: "k_EResultInvalidParam",
    9: "k_EResultFileNotFound", 10: "k_EResultBusy", 15: "k_EResultAccessDenied", 16: "k_EResultTimeout",
    20: "k_EResultServiceUnavailable", 21: "k_EResultNotLoggedOn", 25: "k_EResultLimitExceeded",
}
# ESteamAPIInitResult (steam_api.h), SteamAPI_InitFlat's return.
INIT_RESULTS = {0: "OK", 1: "FailedGeneric", 2: "NoSteamClient", 3: "VersionMismatch"}
# ESteamAPICallFailure (isteamutils.h), why a call result couldn't be delivered.
CALL_FAILURES = {-1: "none", 0: "SteamGone", 1: "NetworkFailure", 2: "InvalidHandle", 3: "MismatchedCallback"}
INSTALL_FOLDER_CHARS = 4096  # pchFolder buffer for GetItemInstallInfo


# ---- result structs (the SDK's field order and sizes; see CALLBACK_PACK) ----
class SubscribeResult(ctypes.Structure):
    """RemoteStorageSubscribePublishedFileResult_t and the Unsubscribe twin (same shape)."""
    _pack_ = CALLBACK_PACK
    _fields_ = [("result", c_int32), ("published_file_id", c_uint64)]


class QueryCompleted(ctypes.Structure):
    """SteamUGCQueryCompleted_t."""
    _pack_ = CALLBACK_PACK
    _fields_ = [
        ("handle", c_uint64), ("result", c_int32), ("num_results", c_uint32), ("total_results", c_uint32),
        ("cached", c_bool), ("next_cursor", c_char * 256),  # k_cchPublishedFileURLMax
    ]


class UGCDetails(ctypes.Structure):
    """SteamUGCDetails_t (isteamugc.h); only title / visibility / banned / result are read."""
    _pack_ = CALLBACK_PACK
    _fields_ = [
        ("published_file_id", c_uint64), ("result", c_int32), ("file_type", c_int32),
        ("creator_app_id", c_uint32), ("consumer_app_id", c_uint32),
        ("title", c_char * 129),  # k_cchPublishedDocumentTitleMax
        ("description", c_char * 8000),  # k_cchPublishedDocumentDescriptionMax
        ("steam_id_owner", c_uint64), ("time_created", c_uint32), ("time_updated", c_uint32),
        ("time_added_to_user_list", c_uint32), ("visibility", c_int32),
        ("banned", c_bool), ("accepted_for_use", c_bool), ("tags_truncated", c_bool),
        ("tags", c_char * 1025),  # k_cchTagListMax
        ("file", c_uint64), ("preview_file", c_uint64),
        ("file_name", c_char * 260),  # k_cchFilenameMax
        ("file_size", c_int32), ("preview_file_size", c_int32),
        ("url", c_char * 256),  # k_cchPublishedFileURLMax
        ("votes_up", c_uint32), ("votes_down", c_uint32), ("score", c_float),
        ("num_children", c_uint32), ("total_files_size", c_uint64),
    ]


class CallbackMsg(ctypes.Structure):
    """CallbackMsg_t (steam_api_internal.h), the manual-dispatch message."""
    _pack_ = CALLBACK_PACK
    _fields_ = [("steam_user", c_int32), ("callback", c_int32), ("param", c_void_p), ("param_size", c_int32)]


class WorkerError(Exception):
    """A failure with a user-readable message (what handle() reports as `error`)."""


def eresult_text(result) -> str:
    name = ERESULT_NAMES.get(result)
    return f"{name} ({result})" if name else f"EResult {result}"


def to_item_id(id) -> int:
    """Workshop ids are unsigned 64-bit; the SDK takes a uint64. Re-checked
    here even though steam_client validated it (same regex as steam_cmd.to_workshop_id)."""
    s = ("" if id is None else str(id)).strip()
    if not re.fullmatch(r"\d{1,20}", s, re.ASCII):
        raise WorkerError(f"Not a Steam Workshop item id: {id}")
    return int(s)


def _text(x):
    """str out of a str / bytes (a ctypes c_char array field reads as bytes, NUL-cut)."""
    if x is None:
        return None
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    return str(x)


def library_name() -> str:
    """The SDK library file this platform's helper loads from cwd."""
    for prefix, name in LIBRARY_FILES.items():
        if sys.platform.startswith(prefix):
            return name
    raise WorkerError(f"Steam Workshop actions through the Steam client aren't supported on {sys.platform}.")


class SteamApi:
    """The flat C API of Valve's client library, typed once at load, reduced to
    the calls VOLT's actions make. Load (constructor) and init() are separate
    so a failed init isn't cached with the library. Every method returns plain
    Python values; nothing ctypes leaves this class."""

    SELF = c_void_p  # the ISteam* interface pointer every flat method takes first
    # export name: (restype, argtypes). All must exist in the library (checked at
    # load); SteamAPI_SteamUGC_v021 ties the code to SDK 1.64's ISteamUGC.
    FUNCTIONS = {
        "SteamAPI_IsSteamRunning": (c_bool, []),
        "SteamAPI_InitFlat": (c_int, [POINTER(c_char)]),  # SteamErrMsg* (char[1024])
        "SteamAPI_Shutdown": (None, []),
        "SteamAPI_RunCallbacks": (None, []),
        "SteamAPI_GetHSteamPipe": (c_int32, []),
        "SteamAPI_ManualDispatch_Init": (None, []),
        "SteamAPI_ManualDispatch_RunFrame": (None, [c_int32]),
        "SteamAPI_ManualDispatch_GetNextCallback": (c_bool, [c_int32, POINTER(CallbackMsg)]),
        "SteamAPI_ManualDispatch_FreeLastCallback": (None, [c_int32]),
        "SteamAPI_SteamUGC_v021": (c_void_p, []),
        "SteamAPI_SteamUtils_v010": (c_void_p, []),
        "SteamAPI_ISteamUtils_IsAPICallCompleted": (c_bool, [SELF, c_uint64, POINTER(c_bool)]),
        "SteamAPI_ISteamUtils_GetAPICallResult": (c_bool, [SELF, c_uint64, c_void_p, c_int, c_int, POINTER(c_bool)]),
        "SteamAPI_ISteamUtils_GetAPICallFailureReason": (c_int, [SELF, c_uint64]),
        "SteamAPI_ISteamUGC_SubscribeItem": (c_uint64, [SELF, c_uint64]),
        "SteamAPI_ISteamUGC_UnsubscribeItem": (c_uint64, [SELF, c_uint64]),
        "SteamAPI_ISteamUGC_GetItemState": (c_uint32, [SELF, c_uint64]),
        "SteamAPI_ISteamUGC_GetItemInstallInfo": (c_bool, [SELF, c_uint64, POINTER(c_uint64), POINTER(c_char), c_uint32, POINTER(c_uint32)]),
        "SteamAPI_ISteamUGC_GetItemDownloadInfo": (c_bool, [SELF, c_uint64, POINTER(c_uint64), POINTER(c_uint64)]),
        "SteamAPI_ISteamUGC_DownloadItem": (c_bool, [SELF, c_uint64, c_bool]),
        "SteamAPI_ISteamUGC_CreateQueryUGCDetailsRequest": (c_uint64, [SELF, POINTER(c_uint64), c_uint32]),
        "SteamAPI_ISteamUGC_SendQueryUGCRequest": (c_uint64, [SELF, c_uint64]),
        "SteamAPI_ISteamUGC_GetQueryUGCResult": (c_bool, [SELF, c_uint64, c_uint32, POINTER(UGCDetails)]),
        "SteamAPI_ISteamUGC_ReleaseQueryUGCRequest": (c_bool, [SELF, c_uint64]),
    }

    def __init__(self, path: str):
        """Loads the library at `path` and binds FUNCTIONS. Raises WorkerError
        (the loader's error, or the exports an older copy lacks)."""
        try:
            lib = env.load_library(path)
        except Exception as err:
            raise WorkerError(f"{err!s}" or err.__class__.__name__) from err
        self.f = types.SimpleNamespace()
        missing = []
        for name, (restype, argtypes) in self.FUNCTIONS.items():
            try:
                fn = getattr(lib, name)
            except AttributeError:  # ctypes: "function 'X' not found"
                missing.append(name)
                continue
            fn.restype = restype
            fn.argtypes = argtypes
            setattr(self.f, name, fn)
        if missing:
            raise WorkerError(
                f"{os.path.basename(path)} doesn't export {', '.join(missing)}, so it isn't the Steamworks SDK 1.64 "
                "library VOLT's Steam helper is written against (RimWorld's own copy, for one, is older)."
            )
        self._lib = lib
        self.ugc = None  # ISteamUGC* once initialized
        self.utils = None  # ISteamUtils*
        self._pipe = 0  # HSteamPipe, manual dispatch only
        self.initialized = False

    # ---- lifecycle ----
    def init(self) -> None:
        """SteamAPI_InitFlat: connects to the running, logged-in Steam client
        under the app id in cwd/steam_appid.txt. Raises WorkerError naming the
        SDK's own reason."""
        if not self.f.SteamAPI_IsSteamRunning():
            raise WorkerError("Steam is not running")
        if DISPATCH == "manual":
            self.f.SteamAPI_ManualDispatch_Init()
        err = ctypes.create_string_buffer(1024)  # k_cchMaxSteamErrMsg
        rc = int(self.f.SteamAPI_InitFlat(err))
        if rc != 0:
            detail = _text(err.value).strip() or "no detail from the SDK"
            raise WorkerError(f"{INIT_RESULTS.get(rc, f'ESteamAPIInitResult {rc}')}: {detail}")
        self.initialized = True
        self.ugc = self.f.SteamAPI_SteamUGC_v021()
        self.utils = self.f.SteamAPI_SteamUtils_v010()
        if not self.ugc or not self.utils:
            self.shutdown()
            raise WorkerError(
                "this Steam client doesn't provide the Workshop interface version VOLT uses (ISteamUGC 021 / "
                "SteamUtils 010) - update Steam (Steam > Check for Steam Client Updates) and try again"
            )
        if DISPATCH == "manual":
            self._pipe = int(self.f.SteamAPI_GetHSteamPipe())

    def shutdown(self) -> None:
        if self.initialized:
            self.initialized = False
            self.ugc = self.utils = None
            self.f.SteamAPI_Shutdown()

    def pump(self) -> None:
        """One pass of SDK message servicing (DISPATCH above)."""
        if DISPATCH == "manual":
            self.f.SteamAPI_ManualDispatch_RunFrame(self._pipe)
            msg = CallbackMsg()
            while self.f.SteamAPI_ManualDispatch_GetNextCallback(self._pipe, ctypes.pointer(msg)):
                self.f.SteamAPI_ManualDispatch_FreeLastCallback(self._pipe)  # nothing registered: dropped
        else:
            self.f.SteamAPI_RunCallbacks()

    # ---- call results ----
    def call_completed(self, call: int) -> bool:
        failed = c_bool(False)
        return bool(self.f.SteamAPI_ISteamUtils_IsAPICallCompleted(self.utils, call, ctypes.pointer(failed)))

    def call_result(self, call: int, result: ctypes.Structure, callback_id: int) -> bool:
        """Copies the completed call's result struct into `result`; False (with
        the reason in call_failure) when the SDK has none for it."""
        failed = c_bool(False)
        ok = self.f.SteamAPI_ISteamUtils_GetAPICallResult(
            self.utils, call, ctypes.addressof(result), ctypes.sizeof(result), callback_id, ctypes.pointer(failed)
        )
        return bool(ok) and not failed.value

    def call_failure(self, call: int) -> str:
        reason = int(self.f.SteamAPI_ISteamUtils_GetAPICallFailureReason(self.utils, call))
        return CALL_FAILURES.get(reason, f"ESteamAPICallFailure {reason}")

    # ---- ISteamUGC ----
    def subscribe_item(self, item: int) -> int:
        return int(self.f.SteamAPI_ISteamUGC_SubscribeItem(self.ugc, item))

    def unsubscribe_item(self, item: int) -> int:
        return int(self.f.SteamAPI_ISteamUGC_UnsubscribeItem(self.ugc, item))

    def item_state(self, item: int) -> int:
        return int(self.f.SteamAPI_ISteamUGC_GetItemState(self.ugc, item))

    def install_info(self, item: int) -> dict:
        """{folder, disk_size, timestamp} for an installed item, else {}."""
        size, stamp = c_uint64(0), c_uint32(0)
        folder = ctypes.create_string_buffer(INSTALL_FOLDER_CHARS)
        ok = self.f.SteamAPI_ISteamUGC_GetItemInstallInfo(
            self.ugc, item, ctypes.pointer(size), folder, INSTALL_FOLDER_CHARS, ctypes.pointer(stamp)
        )
        if not ok:
            return {}
        return {"folder": _text(folder.value), "disk_size": int(size.value), "timestamp": int(stamp.value)}

    def download_info(self, item: int) -> dict:
        """{downloaded, total} while a download is in progress, else {}."""
        done, total = c_uint64(0), c_uint64(0)
        ok = self.f.SteamAPI_ISteamUGC_GetItemDownloadInfo(self.ugc, item, ctypes.pointer(done), ctypes.pointer(total))
        if not ok:
            return {}
        return {"downloaded": int(done.value), "total": int(total.value)}

    def download_item(self, item: int, high_priority: bool) -> bool:
        return bool(self.f.SteamAPI_ISteamUGC_DownloadItem(self.ugc, item, bool(high_priority)))

    def create_query_details(self, items: list) -> int:
        ids = (c_uint64 * len(items))(*items)
        return int(self.f.SteamAPI_ISteamUGC_CreateQueryUGCDetailsRequest(self.ugc, ids, len(items)))

    def send_query(self, handle: int) -> int:
        return int(self.f.SteamAPI_ISteamUGC_SendQueryUGCRequest(self.ugc, handle))

    def query_result(self, handle: int, index: int, details: UGCDetails) -> bool:
        return bool(self.f.SteamAPI_ISteamUGC_GetQueryUGCResult(self.ugc, handle, index, ctypes.pointer(details)))

    def release_query(self, handle: int) -> bool:
        return bool(self.f.SteamAPI_ISteamUGC_ReleaseQueryUGCRequest(self.ugc, handle))


def item_status(api: SteamApi, item: int) -> dict:
    """Plain-dict status for an item (JSON-safe, so it crosses the pipe as-is;
    the JS itemStatus, snake_case). installed: on disk AND not mid-download/
    update (INSTALLED set, DOWNLOADING / DOWNLOAD_PENDING / NEEDS_UPDATE all
    clear). folder/disk_size from GetItemInstallInfo ({} when not installed),
    bytes_* from GetItemDownloadInfo ({} when not downloading)."""
    state = api.item_state(item)
    info = api.install_info(item)
    dl = api.download_info(item)

    def has(flag: str) -> bool:
        return bool(state & ITEM_STATE[flag])

    busy = has("DOWNLOADING") or has("DOWNLOAD_PENDING")
    return {
        "id": str(item),
        "state": state,
        "subscribed": has("SUBSCRIBED"),
        "installed": has("INSTALLED") and not busy and not has("NEEDS_UPDATE"),
        "downloading": busy,
        "needs_update": has("NEEDS_UPDATE"),
        "folder": info.get("folder") or None,
        "disk_size": info.get("disk_size"),
        "bytes_downloaded": dl.get("downloaded"),
        "bytes_total": dl.get("total"),
    }


def _eprint(message: str) -> None:
    """Diagnostics -> stderr (steam_client.py logs every line)."""
    try:
        print(f"[steam worker] {message}", file=sys.stderr, flush=True)
    except Exception:
        pass


class Worker:
    """One helper's job handler (the JS createWorker). handle() never raises."""

    def __init__(self):
        self._api = None  # the initialized SteamApi

    # ---- Steam client ----
    def client(self) -> SteamApi:
        """The initialized SteamApi, created on first use. Raises WorkerError
        with the reason (library / steam_appid.txt missing from cwd, an old
        library, Steam not running or not logged in). Nothing is cached on
        failure: a retry within the same operation loads and connects again."""
        if self._api is not None:
            return self._api
        cwd = env.cwd()
        name = library_name()
        path = os.path.join(cwd, name)
        if not os.path.isfile(os.path.join(cwd, "steam_appid.txt")):
            raise WorkerError(
                f"steam_appid.txt is missing from {cwd}, so the Steamworks library can't tell Steam which game "
                "to act for. VOLT writes it there before every helper start; check that the folder is writable."
            )
        if not os.path.isfile(path):
            raise WorkerError(
                f"The Steamworks library {name} is missing from {cwd}, so Steam Workshop actions are unavailable. "
                "It ships with VOLT (re-extract the release zip to restore it), or put the Steamworks SDK 1.64 "
                "copy of it there yourself."
            )
        try:
            api = SteamApi(path)
        except WorkerError as err:
            raise WorkerError(f"The Steamworks library couldn't be loaded from {cwd}: {err!s}") from err
        try:
            api.init()
        except WorkerError as err:
            raise WorkerError(f"Couldn't connect to Steam - is it running and logged in? ({err!s})") from err
        self._api = api
        return api

    def _await(self, call: int, struct_type, callback_id: int, what: str):
        """Pumps the SDK until the call result for `call` is in, then returns it
        as a `struct_type` instance; WorkerError when TIMING callback_timeout_s
        passes first, or the SDK reports the call failed."""
        api = self._api
        if call == INVALID_API_CALL:
            raise WorkerError(f"Steam refused to start {what} (no API call handle).")
        timeout = TIMING["callback_timeout_s"]
        deadline = time.monotonic() + timeout
        while True:
            api.pump()
            if api.call_completed(call):
                result = struct_type()
                if not api.call_result(call, result, callback_id):
                    raise WorkerError(f"Steam didn't deliver the result of {what}: {api.call_failure(call)}.")
                return result
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
        api = self.client()
        call = self._sdk("subscribe", lambda: api.subscribe_item(item))
        result = self._sdk("subscribe", lambda: self._await(call, SubscribeResult, SUBSCRIBE_CALLBACK, "the subscription"))
        if result.result != RESULT_OK:
            raise WorkerError(f"Steam subscribe failed: {eresult_text(result.result)}")
        try:
            # Subscribing queues it anyway; this only bumps priority.
            if not api.download_item(item, True):
                _eprint(f"download request for {item} refused by Steam (subscribe still stands)")
        except Exception as err:
            _eprint(f"download request for {item} failed (subscribe still stands): {err!s}")
        return self._sdk("status check", lambda: item_status(api, item))

    def unsubscribe(self, item: int) -> dict:
        """A confirmed unsubscribe still isn't proof it took (RimSort has an open
        bug where it silently doesn't): the caller verifies with is_subscribed."""
        api = self.client()
        call = self._sdk("unsubscribe", lambda: api.unsubscribe_item(item))
        result = self._sdk("unsubscribe", lambda: self._await(call, SubscribeResult, UNSUBSCRIBE_CALLBACK, "the unsubscribe"))
        if result.result != RESULT_OK:
            raise WorkerError(f"Steam unsubscribe failed: {eresult_text(result.result)}")
        return self._sdk("status check", lambda: item_status(api, item))

    def install_info(self, item: int) -> dict:
        api = self.client()
        return self._sdk("status check", lambda: item_status(api, item))

    def download(self, item: int) -> dict:
        """(Re-)requests a high-priority download of an item, the same call
        subscribe's priority bump makes (Sync re-asks when Steam never starts
        a subscribed item's download). Never raises for a refused call - an
        error would end the caller's operation, and its helper is the one that
        can see the item: {"requested": bool, "reason": str | None, "status": item_status}."""
        api = self.client()
        requested, reason = False, None
        try:
            requested = api.download_item(item, True)
            if not requested:
                reason = "Steam refused the download request"
        except Exception as err:
            reason = f"Steam download request failed: {err!s}"
        return {"requested": requested, "reason": reason, "status": self._sdk("status check", lambda: item_status(api, item))}

    def is_subscribed(self, item: int) -> bool:
        return self.install_info(item)["subscribed"]

    def workshop_item(self, item: int) -> dict:
        """The item's listing as the logged-in client sees it (Scan Issues' title
        fallback when the keyless Web API says not found): {found, title,
        visibility, banned}. One UGC details query: create -> send -> await
        SteamUGCQueryCompleted_t -> read result 0 -> release."""
        api = self.client()
        what = "workshop item lookup"
        handle = self._sdk(what, lambda: api.create_query_details([item]))
        if handle == INVALID_UGC_QUERY_HANDLE:
            raise WorkerError(f"Steam {what} failed: no query handle")
        try:
            call = self._sdk(what, lambda: api.send_query(handle))
            done = self._sdk(what, lambda: self._await(call, QueryCompleted, QUERY_CALLBACK, "the Workshop item lookup"))
            if done.handle != handle:
                _eprint(f"UGC query result handle {done.handle} != {handle} (read anyway)")
            if done.result != RESULT_OK:
                raise WorkerError(f"Steam {what} failed: {eresult_text(done.result)}")
            if done.num_results < 1:
                return {"found": False, "title": None}
            details = UGCDetails()
            if not self._sdk(what, lambda: api.query_result(handle, 0, details)):
                raise WorkerError(f"Steam {what} failed: no result details")
            if details.result != RESULT_OK:  # per-item result: k_EResultFileNotFound for an unknown id
                return {"found": False, "title": None}
            return {
                "found": True,
                "title": _text(details.title),
                "visibility": int(details.visibility),
                "banned": bool(details.banned),
            }
        finally:
            try:
                if not api.release_query(handle):
                    _eprint(f"releasing UGC query {handle} refused")
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
        api, self._api = self._api, None
        if api is not None:
            try:
                api.shutdown()
            except Exception as err:
                _eprint(f"shutdown failed: {err!s}")


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
    inp = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    return serve(inp, proto)


if __name__ == "__main__":
    sys.exit(main())
