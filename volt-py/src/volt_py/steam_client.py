"""Steam Workshop through the user's running, logged-in Steam client (port of
Electron's src/electron/lib/steam.js): subscribe / unsubscribe / status reads /
the client's own item listing. The third of VOLT's three Steam access paths,
next to steam_cmd.py (anonymous SteamCMD downloads) and steam_web_api.py (the
keyless Web API). Needs no login of its own: the Steamworks SDK talks to the
Steam client already signed in on this machine.

The SDK never runs in this process: every call goes to a short-lived helper,
steam_worker.py, started as `python -m volt_py.steam_worker` (why: that file's
docstring - Steam would otherwise register VOLT itself as "RimWorld, running").

One helper per operation, keyed by Workshop item id. The screen drives each
operation as a sequence of calls, so the boundaries are read from those calls
(as the Electron renderer's App.jsx did):
  Subscribe:    subscribe(id) starts a fresh helper; install_info(id) polls
                reuse it. Ends when a status comes back installed. Sync to
                Steam runs the same way per item (verify + polls in the
                subscribing helper: a fresh helper can't see an item another
                one just subscribed, real hardware 2026-09-30).
  Unsubscribe:  unsubscribe(id) starts a fresh helper; is_subscribed(id) checks
                reuse it. Ends when is_subscribed comes back False.
  Install wait: install_info(id) with no operation in flight for that id starts
                one; later polls reuse it.
  Any:          any error (SDK failure, helper crash, no answer) ends it, and so
                does release(id) (Sync, once an item is done, whatever the
                outcome). A caller's own give-up never reaches here, so an
                operation with no new call for TIMING idle_s ends too.
is_subscribed / workshop_item with no operation in flight for that id run in a
one-shot helper (started, asked once, stopped).

availability() never starts a helper: it checks the steam_appid.txt gate (a GOG
build has no Workshop), that the `steamworks` package is importable, and that
the two native library files are in <app_root>/steamworks/ - all plain file
checks. Whether Steam is running is reported by the first real action.

Runtime folder <app_root>/steamworks/ (the helper's cwd; SteamworksPy looks
there first for all three):
  steam_appid.txt      written here (ensure_runtime_dir), no user action
  SteamworksPy64.dll   the user's step: built for Steamworks SDK 1.64
                       (redist/windows in the SteamworksPy repo); the old 1.6.5
                       release still works but can't start downloads or look up titles
  steam_api64.dll      the user's step: from the SAME Steamworks SDK
                       (sdk/redistributable_bin/win64). RimWorld's own copy only
                       pairs with the 1.6.5 release (the 1.64 DLL needs
                       SteamInternal_SteamAPI_Init, which it lacks). VOLT never
                       copies either file itself.
  steamworks/          optional: the package's source folder, when it isn't
                       installed into volt-py's venv (cwd is on the helper's sys.path)

Blocking, stdlib only (subprocess + threading + json). Every public function
blocks the calling thread for the round trip (a status read is immediate; a
subscribe waits on Steam's confirmation) and returns a plain value or raises
SteamClientError with a user-readable message (ValueError for a bad id), the
same contract as steam_cmd.download_items - call them off the GUI thread. Safe
to call from several threads at once. Every call is logged: action, item id,
which kind of helper it ran in, and the real answer or error (CLAUDE.md §10).
"""

import importlib.util
import json
import os
import platform
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import Callable, NamedTuple

from .applog import clip, log
from .fsutil import exists
from .paths import STEAM_APPID, has_steam_appid
from .steam_cmd import to_workshop_id

WORKER_MODULE = "volt_py.steam_worker"
_SRC_DIR = Path(__file__).resolve().parents[1]  # volt-py/src, the folder holding the volt_py package
REPO_URL = "https://github.com/philippj/SteamworksPy"
RELEASES_URL = REPO_URL + "/releases"
INSTALL_HINT = 'uv add "steamworks @ git+https://github.com/philippj/SteamworksPy"'

# Seconds (the JS's `timing`, in ms). A dict, so a check harness can shrink them.
TIMING = {
    # One call's answer from the helper. subscribe/unsubscribe wait on a Steam
    # callback (the helper gives up at 25 s itself); a status check is
    # immediate. Past this the operation is ended.
    "job_timeout_s": 30.0,
    # No call for this long ends the operation. The screen polls every 1-2 s
    # while it's still interested.
    "idle_s": 10.0,
    # Wait this long for the helper to exit after 'shutdown', then kill() it.
    "shutdown_grace_s": 2.0,
}
# Check-harness seams (no real Windows / Steam / native library in the sandbox).
env = types.SimpleNamespace(
    platform=platform.system(), popen=subprocess.Popen, python=sys.executable, find_spec=importlib.util.find_spec,
)
# The two native files SteamworksPy loads, per platform: its own bridge library,
# then Valve's steam_api the bridge links against. Windows (64-bit) is what
# VOLT targets; the Linux/macOS names are the library's, unverified here.
NATIVE_FILES = {
    "Windows": ("SteamworksPy64.dll", "steam_api64.dll"),
    "Linux": ("SteamworksPy.so", "libsteam_api.so"),
    "Darwin": ("SteamworksPy.dylib", "libsteam_api.dylib"),
}


class SteamClientError(RuntimeError):
    """A Steam client failure with a user-readable message (the JS's Error)."""


class AvailabilityResult(NamedTuple):
    available: bool
    reason: str | None  # why not, user-readable, when not available


def runtime_dir(app_root) -> Path:
    return Path(app_root) / "steamworks"


def ensure_runtime_dir(app_root) -> Path:
    """<app_root>/steamworks/ with steam_appid.txt in it (the SDK reads the app
    id from the helper's cwd). Only ever writes that one file."""
    dir = runtime_dir(app_root)
    dir.mkdir(parents=True, exist_ok=True)
    appid = dir / "steam_appid.txt"
    try:
        current = appid.read_text(encoding="utf-8").strip()
    except OSError:
        current = None
    if current != STEAM_APPID:
        appid.write_text(STEAM_APPID + "\n", encoding="utf-8")
    return dir


def binding_installed(app_root) -> bool:
    """Whether `import steamworks` would resolve in the helper: installed into
    the venv (the same interpreter runs the helper), or dropped into the runtime
    folder as a source folder. Loads nothing."""
    if exists(runtime_dir(app_root) / "steamworks" / "__init__.py"):
        return True
    try:
        return env.find_spec("steamworks") is not None
    except (ImportError, ValueError):
        return False


def availability(app_root, game_dir) -> AvailabilityResult:
    """Whether Steam Workshop actions through the Steam client can be offered
    for this install. Starts no helper, loads no native code, writes nothing."""
    if not game_dir:
        return AvailabilityResult(False, "The RimWorld install folder is not set.")
    if not has_steam_appid(game_dir):
        return AvailabilityResult(
            False, "This RimWorld install isn't a Steam build (no steam_appid.txt), so Steam Workshop actions are unavailable."
        )
    names = NATIVE_FILES.get(env.platform)
    if names is None:
        return AvailabilityResult(False, f"Steam Workshop actions through the Steam client aren't supported on {env.platform} yet.")
    dir = runtime_dir(app_root)
    if not binding_installed(app_root):
        return AvailabilityResult(
            False,
            "The SteamworksPy Python package isn't installed, so Steam Workshop actions are unavailable. Install it into "
            f"volt-py's environment ({INSTALL_HINT}), or copy its steamworks/ source folder into {dir}.",
        )
    missing = [n for n in names if not exists(dir / n)]
    if missing:
        bridge, api = names
        where = {
            bridge: f"built for Steamworks SDK 1.64: redist/windows in {REPO_URL}; the old 1.6.5 release "
            f"({RELEASES_URL}) works but can't start downloads or look up titles",
            api: "from the same Steamworks SDK: redistributable_bin/win64; RimWorld's copy only fits the 1.6.5 release",
        }
        what = "these files" if len(missing) > 1 else "this file"
        return AvailabilityResult(
            False,
            f"The Steamworks native library isn't set up, so Steam Workshop actions are unavailable. Put {what} in {dir}: "
            + "; ".join(f"{n} ({where[n]})" for n in missing)
            + ".",
        )
    return AvailabilityResult(True, None)


# ---- helper process ----
_lock = threading.RLock()  # _ops, _live
_live: set = set()  # every _Helper not yet exited
_ops: dict = {}  # item id string -> _Op


class _Pending:
    __slots__ = ("event", "value", "error")

    def __init__(self):
        self.event = threading.Event()
        self.value = None
        self.error = None


class _Helper:
    """One helper process (the JS startWorker's handle): send(action, id) ->
    value (blocking, TIMING job_timeout_s), stop() -> exited Event. Once the
    helper is gone (stopped or crashed), every pending and later send raises."""

    def __init__(self, app_root):
        cwd = ensure_runtime_dir(app_root)
        kwargs = {}
        if env.platform == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash behind the GUI
        # The helper imports volt_py.steam_worker: normally from the venv (uv
        # installs the project editable), but the source tree goes on its
        # PYTHONPATH too so the spawn doesn't depend on that install.
        child_env = dict(os.environ)
        child_env["PYTHONPATH"] = os.pathsep.join(p for p in (str(_SRC_DIR), child_env.get("PYTHONPATH")) if p)
        try:
            self.proc = env.popen(
                [env.python, "-m", WORKER_MODULE], cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, encoding="utf-8", errors="replace", env=child_env, **kwargs,
            )
        except (OSError, ValueError) as err:
            e = SteamClientError(f"Couldn't start the Steam helper process: {err}")
            log(f"[steam] {e}")
            raise e from err
        self.pid = getattr(self.proc, "pid", "?")
        log(f"[steam] helper process spawned (pid {self.pid}, cwd {cwd})")
        self._lock = threading.Lock()  # _pending, _seq, dead, _stopping, gone, _kill_timer, stdin writes
        self._pending: dict = {}  # seq -> _Pending
        self._seq = 0
        self.dead: SteamClientError | None = None  # every send raises this once the helper is gone
        self._stopping = False
        self.gone = False  # exit seen
        self._kill_timer = None
        self.exited = threading.Event()
        with _lock:
            _live.add(self)
        threading.Thread(target=self._read_stdout, name=f"steam-helper-{self.pid}-stdout", daemon=True).start()
        threading.Thread(target=self._read_stderr, name=f"steam-helper-{self.pid}-stderr", daemon=True).start()

    def _read_stdout(self) -> None:
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    log(f"[steam] helper (pid {self.pid}) wrote a non-JSON line, ignored: {clip(line, 300)}")
                    continue
                if not isinstance(msg, dict):
                    log(f"[steam] helper (pid {self.pid}) wrote a non-object line, ignored: {clip(line, 300)}")
                    continue
                with self._lock:
                    p = self._pending.pop(msg.get("seq"), None)
                if p is None:
                    continue  # timed out already, or a stray reply
                if msg.get("ok"):
                    p.value = msg.get("value")
                else:
                    p.error = SteamClientError(msg.get("error") or "The Steam helper reported an unknown error.")
                p.event.set()
        except (OSError, ValueError) as err:
            log(f"[steam] helper (pid {self.pid}) stdout read failed: {err}")
        code = self.proc.wait()
        with self._lock:
            if self.dead is None:
                self.dead = SteamClientError(
                    f"The Steam helper process stopped unexpectedly (exit code {code}) - Steam may have closed it, "
                    "or the Steamworks library crashed."
                )
            dead = self.dead
            self.gone = True
            timer, self._kill_timer = self._kill_timer, None
        log(f"[steam] helper process exited (pid {self.pid}, code {code}): {dead}")
        self._fail_all(dead)
        if timer is not None:
            timer.cancel()
        with _lock:
            _live.discard(self)
        self.exited.set()

    def _read_stderr(self) -> None:
        try:
            for line in self.proc.stderr:
                line = line.rstrip()
                if line:
                    log(f"[steam] helper (pid {self.pid}) stderr: {clip(line, 1000)}")
        except (OSError, ValueError):
            pass

    def _fail_all(self, err: SteamClientError) -> None:
        with self._lock:
            pending, self._pending = list(self._pending.values()), {}
        for p in pending:
            p.error = err
            p.event.set()

    def send(self, action: str, key: str):
        """Runs one action for item `key` in the helper; its value, or raises
        SteamClientError (helper's error / gone / no answer in time)."""
        with self._lock:
            if self.dead is not None:
                raise self.dead
            self._seq += 1
            seq = self._seq
            p = _Pending()
            self._pending[seq] = p
            try:
                self.proc.stdin.write(json.dumps({"seq": seq, "action": action, "id": key}) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as err:
                self._pending.pop(seq, None)
                raise SteamClientError(f"Couldn't reach the Steam helper process: {err}") from err
        if not p.event.wait(TIMING["job_timeout_s"]):
            with self._lock:
                self._pending.pop(seq, None)
            raise SteamClientError(f"Steam didn't answer within {round(TIMING['job_timeout_s'])} seconds.")
        if p.error is not None:
            raise p.error
        return p.value

    def stop(self) -> threading.Event:
        """Asks the helper to exit; kill()s it if it hasn't within TIMING
        shutdown_grace_s. Doesn't wait: returns the exited Event. An
        already-exited helper (e.g. crashed) is left alone."""
        with self._lock:
            if self._stopping:
                return self.exited
            self._stopping = True
            if self.dead is None:
                self.dead = SteamClientError("The Steam operation was ended.")
            dead, gone = self.dead, self.gone
        self._fail_all(dead)
        if gone:
            return self.exited
        try:
            with self._lock:
                self.proc.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
                self.proc.stdin.flush()
                self.proc.stdin.close()  # EOF ends the helper too, should the message not
        except (OSError, ValueError):
            pass  # already gone or unreachable: the kill below covers it
        timer = threading.Timer(TIMING["shutdown_grace_s"], self._kill)
        timer.daemon = True
        with self._lock:
            if self.gone:
                return self.exited
            self._kill_timer = timer
        timer.start()
        return self.exited

    def _kill(self) -> None:
        with self._lock:
            if self.gone:
                return
        log(f"[steam] helper (pid {self.pid}) didn't exit within {TIMING['shutdown_grace_s']:g} s of shutdown, killing it")
        try:
            self.proc.kill()
        except OSError:
            pass  # already exited


# ---- operations ----
class _Op:
    __slots__ = ("helper", "idle", "busy")

    def __init__(self, helper: _Helper):
        self.helper = helper
        self.idle = None  # threading.Timer ending the operation after idle_s
        self.busy = 0  # calls awaiting an answer


def _end_op(key: str, op: _Op) -> threading.Event:
    with _lock:
        if op.idle is not None:
            op.idle.cancel()
            op.idle = None
        if _ops.get(key) is op:
            del _ops[key]
    return op.helper.stop()


def _begin_op(key: str, app_root) -> _Op:
    """A new operation on this id: any earlier one still around is ended first."""
    with _lock:
        prev = _ops.get(key)
        if prev is not None:
            _end_op(key, prev)
        op = _Op(_Helper(app_root))
        _ops[key] = op
        return op


def _idle_end(key: str, op: _Op) -> None:
    with _lock:
        # A Timer is a Thread: op.idle is this very timer unless a call came in
        # meanwhile (cancel() can't stop a timer that has already started running).
        if _ops.get(key) is not op or op.busy or op.idle is not threading.current_thread():
            return  # ended, replaced, or a call came in meanwhile
        log(f"[steam] operation on {key} ended: no call for {TIMING['idle_s']:g} s")
        _end_op(key, op)


def _job(app_root, game_dir, id, action: str, *, fresh: bool = False, begin: bool = False,
         done: Callable = lambda value: False):
    """Runs one action in a helper for `id`. fresh: starts a new operation;
    otherwise joins the operation in flight for that id, or when there's none
    starts one (begin) or uses a one-shot helper (the default). done(value):
    True when this answer completes the operation."""
    key = to_workshop_id(id)
    a = availability(app_root, game_dir)
    if not a.available:
        log(f"[steam] {action} {key} refused: {a.reason}")
        raise SteamClientError(a.reason)

    with _lock:
        in_flight = key in _ops
    if not fresh and not in_flight and not begin:
        log(f"[steam] {action} {key} (one-shot helper)...")
        helper = _Helper(app_root)
        try:
            value = helper.send(action, key)
            log(f"[steam] {action} {key} -> {clip(value)}")
            return value
        except Exception as err:
            log(f"[steam] {action} {key} failed: {err}")
            raise
        finally:
            helper.stop()

    with _lock:
        starts = fresh or key not in _ops
        log(f"[steam] {action} {key} ({'new operation' if starts else 'operation in flight'})...")
        op = _begin_op(key, app_root) if starts else _ops[key]
        if op.idle is not None:
            op.idle.cancel()
            op.idle = None
        op.busy += 1
    try:
        value = op.helper.send(action, key)
    except Exception as err:
        with _lock:
            op.busy -= 1
        log(f"[steam] {action} {key} failed, operation ended: {err}")
        _end_op(key, op)
        raise
    with _lock:
        op.busy -= 1
        finished = bool(done(value))
        log(f"[steam] {action} {key} -> {clip(value)}{' (operation complete)' if finished else ''}")
        if finished:
            _end_op(key, op)
        elif not op.busy and _ops.get(key) is op:
            timer = threading.Timer(TIMING["idle_s"], _idle_end, args=(key, op))
            timer.daemon = True
            op.idle = timer
            timer.start()
    return value


def _installed(status) -> bool:
    return bool(isinstance(status, dict) and status.get("installed"))


def subscribe(app_root, game_dir, id) -> dict:
    """Subscribe and ask Steam to download it (high priority). Returns the item
    status (steam_worker.item_status's dict); poll install_info() until
    status["installed"]."""
    return _job(app_root, game_dir, id, "subscribe", fresh=True, done=_installed)


def install_info(app_root, game_dir, id) -> dict:
    return _job(app_root, game_dir, id, "install_info", begin=True, done=_installed)


def download_item(app_root, game_dir, id) -> dict:
    """Re-requests a high-priority download in the operation in flight on
    `id` (Sync, for a subscribed item whose download Steam never started):
    steam_worker.Worker.download's {"requested", "reason", "status"}."""
    return _job(app_root, game_dir, id, "download", begin=True)


def unsubscribe(app_root, game_dir, id) -> dict:
    """Unsubscribe. A returned status isn't proof it took: callers verify with
    is_subscribed(), which ends the operation once it reports False."""
    return _job(app_root, game_dir, id, "unsubscribe", fresh=True)


def is_subscribed(app_root, game_dir, id) -> bool:
    return _job(app_root, game_dir, id, "is_subscribed", done=lambda sub: not sub)


def workshop_item(app_root, game_dir, id) -> dict:
    """The item's listing via the logged-in Steam client: {found, title,
    visibility, banned}. Scan Issues' fallback when the keyless Web API returns
    not found (that wiring is a later slice)."""
    return _job(app_root, game_dir, id, "workshop_item")


def release(id) -> bool:
    """Ends the operation in flight on `id`, if any, without waiting for its
    helper to exit. Sync to Steam calls it once an item is done, whatever
    the outcome, so a timed-out or failed item's helper doesn't linger for the
    idle timeout. An operation with a call still awaiting an answer is left
    alone.
    Returns whether one was ended."""
    key = to_workshop_id(id)
    with _lock:
        op = _ops.get(key)
        if op is None or op.busy:
            log(f"[steam] release {key}: {'a call is still in flight, operation kept' if op else 'no operation in flight'}")
            return False
        log(f"[steam] release {key}: operation ended by the caller")
        _end_op(key, op)
        return True


def stop_all(wait: bool = True) -> None:
    """Ends every operation and stops every helper (app quit). wait: block
    until each has exited (or been killed after the grace period)."""
    with _lock:
        items = list(_ops.items())
    for key, op in items:
        _end_op(key, op)
    with _lock:
        helpers = list(_live)
    events = [h.stop() for h in helpers]
    if wait:
        deadline = time.monotonic() + TIMING["shutdown_grace_s"] + 1.0
        for e in events:
            e.wait(max(0.0, deadline - time.monotonic()))
