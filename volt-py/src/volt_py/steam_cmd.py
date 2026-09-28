"""SteamCMD downloads (port of Electron's src/electron/lib/steamCmd.js):
Workshop items are fetched with Valve's command-line client, logged in
anonymously, so no Steam client, no login and no "RimWorld is running" flash.
The marker-file half of that file was ported first (steamcmd_marker.py); this
is the download engine itself. Steamworks (subscribing on the user's own
account, Sync to Steam) lives in steam_client.py / steam_worker.py (the
engine) and steam_ops.py (the flows); Sync calls delete_item here to drop a
'steamcmd' copy once Steam's own download has landed.

SteamCMD works under APP-ROOT, never in the real Steam library:
  <app_root>/steamcmd/          steamcmd.exe (fetched from Valve on first use)
                                plus the files it self-updates beside it
  <app_root>/steamcmd-library/  force_install_dir, SteamCMD's own cache; items
                                land in steamapps/workshop/content/294100/<id>
Pointing force_install_dir at the real library would let SteamCMD rewrite the
desktop client's own bookkeeping (RimSort avoids it the same way).

RimWorld only loads Data, Mods and Steam-subscribed items, so each finished
item is then COPIED (the cache stays, so SteamCMD doesn't re-fetch it) into
<game>/Mods/<id> with the MARKER file inside (steamcmd_marker: mode
'steamcmd' = a temporary copy Sync to Steam later replaces, 'gog' = the
mod's permanent home); the scan tags the folder's source from it (mods.py).
Never into the real Workshop folder: Steam manages that one's contents.

download_items' per-item status is parsed from SteamCMD's output and is best
effort only; the caller rescans and treats "the mod is on disk now" as the
real answer (RimWorldMainScreen._on_steamcmd_download_done).

Blocking, stdlib only (subprocess + urllib + zipfile + threading). Callers
pick the thread: a download takes seconds to minutes, so the screen runs
download_items on a daemon threading.Thread and gets the result back on the
GUI thread through a queued Qt signal (the community-rules pattern). Every
failure is a SteamCmdError (or ValueError for a bad argument) carrying a
user-readable message.

delete_item (Unsubscribe / Remove of a SteamCMD copy, Sync to Steam's cleanup)
is the one delete this module does: best effort (fsutil.remove_tree_best_effort),
only ever a marked folder directly under <game>/Mods.
"""

import codecs
import io
import os
import platform
import re
import shutil
import stat
import subprocess
import threading
import time
import types
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, NamedTuple

from .applog import clip, log
from .fsutil import exists, is_dir, remove_tree_best_effort
from .paths import STEAM_APPID
from .steamcmd_marker import MARKER, MARKER_MODES, marker_text

STEAMCMD_ZIP_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
EXE = "steamcmd.exe"
SCRIPT_NAME = "volt-download.txt"

# Seconds (the JS's `timing`, in ms). A dict, so a check harness can shrink
# them (a 150 ms poll per fake line adds up).
TIMING = {
    "fetch_timeout_s": 60.0,
    # One SteamCMD run (a whole collection included). Past this it's killed;
    # the caller's rescan still picks up whatever finished.
    "run_timeout_s": 30 * 60.0,
    # How often a download run's console log is read for live lines
    # (create_log_tail); RimSort's interval.
    "log_poll_s": 0.15,
}
# Check-harness seams (no real Windows / SteamCMD / network in the sandbox).
env = types.SimpleNamespace(platform=platform.system(), popen=subprocess.Popen, urlopen=urllib.request.urlopen,
                            remove_tree=remove_tree_best_effort)  # remove_tree: delete_item's seam (a locked file can't be faked portably)


class SteamCmdError(RuntimeError):
    """A SteamCMD failure with a user-readable message (the JS's Error)."""


class RunResult(NamedTuple):
    code: int | None  # exit code
    killed: bool  # stopped by VOLT (run timeout or cancel_current), the JS's `signal`
    output: str  # stdout + stderr, \r stripped


def tool_dir(app_root) -> Path:
    return Path(app_root) / "steamcmd"


def library_dir(app_root) -> Path:
    return Path(app_root) / "steamcmd-library"


def content_dir(app_root) -> Path:
    return library_dir(app_root) / "steamapps" / "workshop" / "content" / STEAM_APPID


def console_log(app_root) -> Path:
    """SteamCMD's own console log: it writes this by itself, no flag needed."""
    return tool_dir(app_root) / "logs" / "console_log.txt"


def to_workshop_id(id) -> str:
    s = ("" if id is None else str(id)).strip()
    if not re.fullmatch(r"\d{1,20}", s, re.ASCII):
        raise ValueError(f"Not a Steam Workshop item id: {id}")
    return s


def unzip_to(data: bytes, dest_dir) -> None:
    """Unpacks a zip's bytes into dest_dir (stdlib zipfile, where the JS had
    to hand-roll a reader). Refuses any entry that would land outside dest_dir
    (a ../-crafted or absolute name): zipfile itself doesn't guard against
    that on extract, so each target is resolved and checked, as the JS does."""
    root = Path(dest_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as err:
        raise SteamCmdError(f"not a zip file ({err})") from err
    with zf:
        for info in zf.infolist():
            name = info.filename
            target = (root / name).resolve()
            if target != root and root not in target.parents:
                raise SteamCmdError(f"unsafe path in zip: {name}")
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def create_log_tail(file, on_line: Callable[[str], None]) -> Callable[..., None]:
    """Live lines for a download run, tailed from SteamCMD's own console log
    (console_log(): <app_root>/steamcmd/logs/console_log.txt) rather than its
    stdout. Why - don't "simplify" this back to reading the pipe: on Windows
    SteamCMD fully buffers its stdout when it's a pipe rather than a real
    console, so its "Update state ... progress" and "Success. Downloaded item
    N" lines only reach the pipe when the process exits (seen on real hardware
    with the Electron app, v0.4.0: the status-bar row sat at 0% until the
    whole run ended). The log file is written to disk as SteamCMD goes,
    however its stdout is buffered. The approach is RimSort's (it tails the
    same file on a 150 ms timer on Windows).
    SteamCMD appends to this file across runs and never truncates it, so the
    tail starts at the file's size when it's created (right before the
    spawn): an earlier run's lines are never re-read. No file yet (first run,
    before SteamCMD has created logs/) = nothing to read this time, not an
    error. A file that shrank or was replaced under us is read from its start.
    Returns poll(final=False): passes each complete line appended since the
    last poll to on_line, split on \\r as well as \\n (SteamCMD redraws its
    progress line with a bare \\r); a trailing partial line waits for the next
    poll, and poll(True) - the last one, after the process exits - passes it
    too.
    ponytail: console_log.txt grows forever over the app's lifetime - SteamCMD
    never rotates it and neither does this (RimSort accepts the same). Rotate
    or truncate it before a run, like volt.log's one-level rotation, if its
    size is ever reported as a real problem."""
    file = Path(file)

    def size_now() -> int:
        try:
            return file.stat().st_size
        except OSError:
            return 0  # not there yet

    state = {"offset": size_now(), "rest": "", "warned": False}
    decoder = codecs.getincrementaldecoder("utf-8")("replace")  # a character split across two reads stays whole

    def poll(final: bool = False) -> None:
        text = ""
        try:
            end = size_now()
            if end < state["offset"]:
                state["offset"] = 0  # replaced or emptied under us: read the new file from its start
            if end > state["offset"]:
                with open(file, "rb") as f:
                    f.seek(state["offset"])
                    buf = f.read(end - state["offset"])
                state["offset"] += len(buf)
                text = decoder.decode(buf)
        except FileNotFoundError:
            pass
        except OSError as err:
            if not state["warned"]:
                state["warned"] = True
                log(f"[steamcmd] couldn't read {file} for live progress ({err}); retrying on every poll "
                    "(the run's result doesn't depend on it)")
        if final:
            text += decoder.decode(b"", final=True)
        parts = re.split(r"[\r\n]+", state["rest"] + text)
        state["rest"] = "" if final else parts.pop()
        for line in parts:
            if line:
                on_line(line)

    return poll


# The running download's steamcmd.exe (run_steamcmd cancellable=True), for
# cancel_current(); never the first-launch self-update, which a kill could
# leave half-applied. Children VOLT killed itself (timeout / cancel) are noted
# in _killed: on Windows a TerminateProcess'd child just reports exit code 1,
# so the process alone can't tell us (the JS gets `signal` from Node).
_current_child = None
_killed: set = set()
_state_lock = threading.Lock()  # _current_child, _killed, _cancel_epoch, _in_flight


def _kill(child, why: str) -> bool:
    """Kills `child` and notes it in _killed. False if it had already exited
    (a cancel racing the run's own end): nothing to kill, nothing noted."""
    with _state_lock:
        if child.poll() is not None:
            return False
        _killed.add(child)
    try:
        child.kill()
        return True
    except OSError as err:  # gone between the check and the kill
        log(f"[steamcmd] kill ({why}) of pid {getattr(child, 'pid', '?')} failed: {err}")
        return False


def run_steamcmd(exe, args: list[str], *, on_line=None, log_file=None, cancellable: bool = False) -> RunResult:
    """Runs steamcmd.exe to completion; RunResult(code, killed, output) with
    output = stdout + stderr; raises SteamCmdError only if it can't be
    started. stdin is /dev/null, so a prompt can never hang it. `output` is
    the run's ground truth (parse_download_output): by the time the process
    has exited, every byte of its pipes has arrived (a reader thread drains
    them meanwhile, so a chatty run can't fill the pipe and stall).
    on_line (optional, with log_file): gets each line live, from log_file
    tailed every TIMING log_poll_s plus once more at exit (create_log_tail;
    why not the pipes: its comment). The pipes only ever fill `output`.
    Past TIMING run_timeout_s the process is killed (killed=True).
    cancellable: this is the run cancel_current() kills.
    Blocks for the whole run: call it off the GUI thread."""
    global _current_child
    exe = Path(exe)
    # Created before the spawn, so its start offset is the log's size now.
    poll = create_log_tail(log_file, on_line) if on_line and log_file else None
    kwargs = {}
    if env.platform == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # the JS's windowsHide
    try:
        child = env.popen(
            [str(exe), *args], cwd=str(exe.parent), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, **kwargs,
        )
    except (OSError, ValueError) as err:
        raise SteamCmdError(f"Couldn't start SteamCMD ({err}).") from err
    if cancellable:
        with _state_lock:
            _current_child = child
    chunks: list[bytes] = []
    reader = threading.Thread(target=lambda: chunks.append(child.stdout.read()), name="steamcmd-stdout", daemon=True)
    reader.start()
    deadline = time.monotonic() + TIMING["run_timeout_s"]
    timed_out = False
    try:
        while child.poll() is None:
            if not timed_out and time.monotonic() >= deadline:
                timed_out = True
                log(f"[steamcmd] run timeout ({TIMING['run_timeout_s'] / 60:g} min) reached, killing pid {child.pid}")
                _kill(child, "timeout")
            if poll:
                poll()
            time.sleep(TIMING["log_poll_s"])
        reader.join()
        if poll:
            poll(True)  # whatever SteamCMD wrote after the last tick
    finally:
        with _state_lock:
            if _current_child is child:
                _current_child = None
            killed = child in _killed
            _killed.discard(child)
    output = b"".join(chunks).decode("utf-8", errors="replace").replace("\r", "")
    return RunResult(child.returncode, killed, output)


_DONE_RE = re.compile(r"Success\. Downloaded item (\d+)")
_FAIL_RE = re.compile(r"ERROR! Download item (\d+) failed \(([^)]*)\)")
_PROGRESS_RE = re.compile(r"Update state \(0x[0-9a-f]+\) downloading, progress: ([\d.]+) \((\d+) / (\d+)\)")


def create_progress_parser(wids: list[str], on_event: Callable[[dict], None], now=time.monotonic) -> Callable[[str], None]:
    """Live per-line parser for a download run (the status-bar row, once one
    exists), fed the console log's lines (create_log_tail).
    Emits on_event({"type": "progress", "id", "percent", "bytes_downloaded",
    "bytes_total", "speed_bytes_per_sec"}) and on_event({"type": "item-done",
    "id", "ok", "message"}). Only a live tap: parse_download_output on the
    full output stays the source of truth for the run's result.
    The progress line carries no item id. INFERRED mapping (not reported by
    SteamCMD, unconfirmed on real hardware): the runscript's
    workshop_download_item commands run strictly in order, one at a time, so
    the item downloading now is the first id in `wids` not yet resolved by a
    Success/ERROR line. `ptr` tracks it.
    Speed = byte delta / time delta (`now` in seconds) between the item's two
    latest samples (no smoothing); None for an item's first sample."""
    state = {"ptr": 0, "last": None}  # last: (bytes, t) of the latest sample for wids[ptr]

    def on_line(line: str) -> None:
        done = _DONE_RE.search(line)
        fail = None if done else _FAIL_RE.search(line)
        if done or fail:
            id = (done or fail)[1]
            try:
                i = wids.index(id, state["ptr"])
            except ValueError:
                i = -1
            if i >= 0:
                state["ptr"] = i + 1
                state["last"] = None
            on_event({"type": "item-done", "id": id, "ok": bool(done), "message": fail[2] if fail else None})
            return
        p = _PROGRESS_RE.search(line)
        if not p or state["ptr"] >= len(wids):
            return
        bytes_now = int(p[2])
        t = now()
        last = state["last"]
        speed = (bytes_now - last[0]) / (t - last[1]) if last and t > last[1] and bytes_now >= last[0] else None
        state["last"] = (bytes_now, t)
        on_event({
            "type": "progress", "id": wids[state["ptr"]], "percent": float(p[1]), "bytes_downloaded": bytes_now,
            "bytes_total": int(p[3]), "speed_bytes_per_sec": speed,
        })

    return on_line


def ensure_steamcmd(app_root) -> Path:
    """<app_root>/steamcmd/steamcmd.exe, fetched from Valve's CDN and unpacked
    on first use. Unpacked into a side folder and renamed into place, so a
    failed fetch never leaves a half-installed copy that the exists check
    would trust. Windows only for now."""
    if env.platform != "Windows":
        raise SteamCmdError(
            "Downloading mods with SteamCMD is only supported on Windows for now, and subscribing through the "
            "Steam client directly isn't available in this version of VOLT yet."
        )
    dir = tool_dir(app_root)
    exe = dir / EXE
    if exists(exe):
        return exe
    log(f"[steamcmd] {exe} not found, fetching {STEAMCMD_ZIP_URL} (timeout {TIMING['fetch_timeout_s']:g}s)")
    try:
        with env.urlopen(STEAMCMD_ZIP_URL, timeout=TIMING["fetch_timeout_s"]) as res:
            status = getattr(res, "status", None)  # None for a file:// URL (the check harness)
            if status is not None and not 200 <= status < 300:
                raise OSError(f"HTTP {status}")
            data = res.read()
    except Exception as err:  # URLError, HTTPError, timeout, dropped connection
        log(f"[steamcmd] fetch failed: {err!r}")
        raise SteamCmdError(f"Couldn't download SteamCMD from Valve ({err}). Check your internet connection.") from err
    log(f"[steamcmd] fetched {len(data)} bytes")
    partial = dir.with_name(dir.name + ".partial")
    try:
        shutil.rmtree(partial, ignore_errors=True)
        unzip_to(data, partial)
        if not exists(partial / EXE):
            raise SteamCmdError(f"no {EXE} inside")
        shutil.rmtree(dir, ignore_errors=True)
        os.rename(partial, dir)
    except Exception as err:
        shutil.rmtree(partial, ignore_errors=True)
        log(f"[steamcmd] unpack failed: {err!r}")
        raise SteamCmdError(f"Couldn't unpack SteamCMD into {dir} ({err}).") from err
    # First launch: SteamCMD updates itself (tens of MB) before it will do
    # anything. Its exit code here is often non-zero, so it isn't checked; the
    # real download run reports any failure.
    log(f"[steamcmd] installed into {dir}; first-run self-update: {exe} +quit")
    first = run_steamcmd(exe, ["+quit"])
    log(f"[steamcmd] self-update exited (code {first.code}, killed {first.killed}); output tail:\n{_tail(first.output)}")
    return exe


def parse_download_output(output: str, ids: list[str]) -> dict:
    """Best-effort per-item status from SteamCMD's output: {"results": [{"id",
    "ok": True/False when it printed a line for the item, None when it didn't,
    "message"}], "error": the last error-looking line (login failure etc.),
    else None}."""
    status: dict[str, dict] = {}
    for m in _DONE_RE.finditer(output):
        status[m[1]] = {"ok": True, "message": None}
    for m in _FAIL_RE.finditer(output):
        status[m[1]] = {"ok": False, "message": m[2]}
    errors = [l for l in output.split("\n") if re.search(r"\b(error|failed)\b", l, re.IGNORECASE | re.ASCII)]
    return {
        "results": [{"id": i, **status.get(i, {"ok": None, "message": None})} for i in ids],
        "error": errors[-1].strip() if errors else None,
    }


def _rmtree(path) -> None:
    """shutil.rmtree, retried once after clearing read-only bits: Windows
    refuses to delete a read-only file, which Node's fs.rm({force}) clears
    by itself. (onexc/onerror differ across the Python versions in play.)"""
    try:
        shutil.rmtree(path)
    except OSError:
        for dirpath, dirnames, filenames in os.walk(path):
            for name in dirnames + filenames:
                try:
                    os.chmod(os.path.join(dirpath, name), stat.S_IRWXU)
                except OSError:
                    pass
        shutil.rmtree(path)


def install_into_mods(src, mods_dir, id: str, mode: str) -> Path:
    """Copies one downloaded item into <mods_dir>/<id>, marker first
    (recording `mode`, MARKER_MODES) so even a half-finished copy is
    recognisably ours and can be replaced next time. An existing folder
    without the marker is someone's own mod: left alone (raises). A marked
    one is replaced, marker included, so a re-download in another mode takes
    that mode."""
    dest = Path(mods_dir) / id
    if exists(dest):
        if not exists(dest / MARKER):
            raise SteamCmdError(f"{dest} already exists and wasn't downloaded by VOLT, so it was left alone")
        _rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / MARKER).write_text(marker_text(mode), encoding="utf-8")
    shutil.copytree(src, dest, dirs_exist_ok=True)
    return dest


# One SteamCMD run at a time: two instances sharing the same install dir would
# fight over its lock. ponytail: single global queue; fine for one app window.
_run_lock = threading.Lock()
# Pause (a later status-bar dispatch): cancel_current() kills the running
# download and cancels every download_items call already waiting on
# _run_lock. Each call remembers _cancel_epoch when it's made; a bump since
# then means "cancelled by the user" (a kill by the run timeout doesn't bump
# it, so that stays an error).
_cancel_epoch = 0
_in_flight = 0  # download_items calls queued or running


def cancel_current() -> bool:
    """Kills the running download (if any) and cancels the queued ones. True
    if there was anything in flight. Nothing calls it yet (no Pause UI in
    this port); built with the engine so the status-bar dispatch doesn't
    have to reopen it."""
    global _cancel_epoch
    with _state_lock:
        if not _in_flight:
            log("[steamcmd] cancel requested: no download running, nothing to do")
            return False
        _cancel_epoch += 1
        child, in_flight = _current_child, _in_flight
    killed = _kill(child, "cancel") if child is not None else False
    log(f"[steamcmd] cancel requested by user: {in_flight} download call(s) in flight; " + (
        f"killing steamcmd.exe (pid {child.pid}) -> kill returned {killed}" if child is not None
        else "no steamcmd.exe running yet (fetch/self-update/queue), cancelled before it starts"
    ))
    return True


def _tail(output: str, n: int = 4000) -> str:
    """The end of a run's output: the per-item lines and any error are near it."""
    return (f"…[{len(output) - n} earlier chars omitted]{output[-n:]}" if len(output) > n else output).strip()


def download_items(app_root, ids, mods_dir, on_event: Callable[[dict], None] | None = None, mode: str = "steamcmd") -> dict:
    """Downloads Workshop items (ids: decimal strings) in ONE SteamCMD session
    via a runscript, so a whole collection is one process. The script file
    (not +command args) keeps a big collection clear of Windows' command-line
    length limit. Every item SteamCMD explicitly reported as downloaded
    ("Success. Downloaded item N") and that is in its cache is then copied
    into mods_dir (<game>/Mods); a failed copy turns that item's ok to False
    with the reason. An unreported item is never copied: SteamCMD creates its
    content folder early, so a run killed mid-item (cancel, timeout) can
    leave a half-download there. on_event (optional) gets live progress:
    create_progress_parser over the lines create_log_tail reads from
    SteamCMD's console log while it runs (why not its stdout: create_log_tail's
    docstring) - called on THIS thread, so a GUI caller must hand the event
    over to its own thread itself.
    Returns {"content_dir", "exit_code", "results": [{"id", "ok", "message",
    "path"?}], "error", "cancelled"}: cancelled True when cancel_current()
    stopped it (results = what finished before the kill). mode (MARKER_MODES,
    default 'steamcmd'): what each copy's marker records - the screen passes
    its acquisition setting, so a GOG-mode download is tagged permanent.
    Raises ValueError for a bad argument, SteamCmdError when the run failed
    outright (couldn't fetch/start SteamCMD, exited nonzero or timed out
    with nothing reported). Blocks: call it off the GUI thread."""
    global _in_flight
    if not ids:
        raise ValueError("No Workshop items to download.")
    if not mods_dir:
        raise ValueError("RimWorld install folder is not set.")
    if mode not in MARKER_MODES:
        raise ValueError(f"Unknown download mode: {mode}")
    wids = list(dict.fromkeys(to_workshop_id(i) for i in ids))
    mods_dir = Path(mods_dir)
    with _state_lock:
        epoch = _cancel_epoch
        _in_flight += 1

    def cancelled() -> bool:
        with _state_lock:
            return epoch != _cancel_epoch

    def cancelled_result(when: str) -> dict:
        log(f"[steamcmd] download of {len(wids)} item(s) cancelled by the user before {when}")
        return {"content_dir": content_dir(app_root), "exit_code": None, **parse_download_output("", wids), "cancelled": True}

    try:
        with _run_lock:
            if cancelled():
                return cancelled_result("it started")
            exe = ensure_steamcmd(app_root)
            if cancelled():
                return cancelled_result("SteamCMD ran")
            library_dir(app_root).mkdir(parents=True, exist_ok=True)
            script = tool_dir(app_root) / SCRIPT_NAME
            script_text = "\n".join([
                f'force_install_dir "{library_dir(app_root)}"',
                "login anonymous",
                *(f"workshop_download_item {STEAM_APPID} {i}" for i in wids),
                "quit",
                "",
            ])
            with open(script, "w", encoding="utf-8", newline="") as f:
                f.write(script_text)
            log(
                f'[steamcmd] running: "{exe}" +runscript "{script}" ({len(wids)} item(s), mode \'{mode}\': copies marked '
                f"{'permanent' if mode == 'gog' else 'temporary, for Sync to Steam'}); live progress tailed from "
                f"{console_log(app_root)} every {TIMING['log_poll_s'] * 1000:g} ms; script:\n{clip(script_text)}"
            )
            # Live events: every item-done logged; progress logged once per
            # item (first sample, with its size) - per-sample lines would
            # flood the log.
            logged: set[str] = set()

            def emit(ev: dict) -> None:
                if ev["type"] == "item-done":
                    outcome = "downloaded" if ev["ok"] else f"FAILED ({ev['message']})"
                    log(f"[steamcmd] live: item {ev['id']} {outcome}")
                elif ev["id"] not in logged:
                    logged.add(ev["id"])
                    log(f"[steamcmd] live: first progress line, attributed to item {ev['id']} (inferred: next unresolved "
                        f"id in order): {ev['percent']}% ({ev['bytes_downloaded']} / {ev['bytes_total']} bytes)")
                if on_event is not None:
                    try:
                        on_event(ev)
                    except Exception as err:
                        log(f"[steamcmd] live progress callback threw: {err!r}")

            run = run_steamcmd(
                exe, ["+runscript", str(script)], on_line=create_progress_parser(wids, emit),
                log_file=console_log(app_root), cancellable=True,
            )
            log(f"[steamcmd] exited (code {run.code}, killed {run.killed}); output:\n{_tail(run.output)}")
            parsed = parse_download_output(run.output, wids)
            results = parsed["results"]
            user_cancelled = run.killed and cancelled()
            any_reported = any(r["ok"] is not None for r in results)
            if user_cancelled:
                log(f"[steamcmd] run stopped by the user (pause); {sum(1 for r in results if r['ok'] is True)} of "
                    f"{len(wids)} item(s) had finished")
            elif run.killed and not any_reported:
                raise SteamCmdError(f"SteamCMD didn't finish within {TIMING['run_timeout_s'] / 60:g} minutes and was stopped.")
            elif run.code != 0 and not any_reported:
                why = f": {parsed['error']}" if parsed["error"] else ""
                raise SteamCmdError(f"SteamCMD failed (exit code {run.code}){why}.")
            mods_dir.mkdir(parents=True, exist_ok=True)
            for r in results:
                src = content_dir(app_root) / r["id"]
                if r["ok"] is not True or not is_dir(src):
                    continue
                try:
                    r["path"] = install_into_mods(src, mods_dir, r["id"], mode)
                except Exception as err:
                    r["ok"] = False
                    r["message"] = f"couldn't copy it into {mods_dir}: {err}"
            for r in results:
                outcome = "ok" if r["ok"] is True else "FAILED" if r["ok"] is False else "not reported (not copied)"
                detail = f" ({r['message']})" if r["message"] else ""
                dest = f" -> {r['path']}" if r.get("path") else ""
                log(f"[steamcmd] item {r['id']}: {outcome}{detail}{dest}")
            if parsed["error"]:
                log(f"[steamcmd] last error line in output: {parsed['error']}")
            return {"content_dir": content_dir(app_root), "exit_code": run.code, **parsed, "cancelled": user_cancelled}
    finally:
        with _state_lock:
            _in_flight -= 1


def delete_item(mods_dir, mod_path) -> dict:
    """Best-effort delete of a SteamCMD mod's folder (its scanned mod["path"]):
    Unsubscribe / Remove on a SteamCMD-downloaded mod (either marker mode -
    the user asked), and a 'steamcmd' copy once Sync to Steam has really
    subscribed it (Sync never passes a 'gog' one: steam_ops.sync_steamcmd_mods
    only picks source 'steamcmd'). The path comes from the UI, so it must be
    a direct child of `mods_dir` holding our MARKER - nothing else can be
    deleted (ValueError otherwise). SteamCMD's own cache copy is left alone.
    Returns {"path", "removed", "skipped", "gone"} (fsutil.remove_tree_best_effort)
    and never raises for a locked file: CALLERS MUST CHECK "gone" - False means
    the folder is still on disk (skipped lists what couldn't be removed), i.e.
    NOT deleted, whatever else happened. On a partial delete the marker is put
    back if it was among the files removed (it sorts first, so it usually is):
    the leftover then still scans as ours, so the next Sync / Remove finds it
    and this function still accepts it."""
    dir = os.path.abspath(str(mod_path)) if isinstance(mod_path, (str, os.PathLike)) and str(mod_path) else ""
    if (not mods_dir or not dir or os.path.dirname(dir) != os.path.abspath(str(mods_dir))
            or not exists(os.path.join(dir, MARKER))):
        raise ValueError(f"Not a SteamCMD-downloaded mod folder: {mod_path}")
    marker = os.path.join(dir, MARKER)
    try:
        marker_body = Path(marker).read_bytes()
    except OSError:
        marker_body = None  # vanished since the check above: nothing to restore
    r = env.remove_tree(dir)
    restored = ""
    if not r["gone"] and marker_body is not None and is_dir(dir) and not exists(marker):
        try:
            Path(marker).write_bytes(marker_body)
            restored = "; marker restored so the leftover stays recognisably VOLT's (retried by the next Sync / Remove)"
        except OSError as err:
            restored = f"; couldn't restore the marker ({err}) - the leftover will scan as a hand-installed mod"
    if r["gone"]:
        log(f"[steamcmd] deleted {dir} ({r['removed']} file(s) removed)")
    else:
        log(f"[steamcmd] delete of {dir} INCOMPLETE - folder still on disk: {r['removed']} file(s) removed, "
            f"{len(r['skipped'])} couldn't be (locked or in use?): {clip(r['skipped'])}{restored}")
    return {"path": Path(dir), **r}
