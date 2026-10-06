"""App-wide action log at <base>/logs/volt.log (idea ported from Electron's
src/electron/lib/log.js). On in every build, packaged included (user
directive 2026-09-30). <base> is app_root.resolve_base_root(): the folder of
VOLT.exe in a packaged build, volt-py/dev-app-root/ in dev. Since 0.6.45 one
log for the whole app (it was one per game, <base>/games/<slug>/volt.log,
started when that game's manager opened): volt_py.main calls init_log once
at start, before any window, so game select, the startup update check and
the updater are logged too.

Lines logged while a game's manager is open carry its slug ("[valheim] ...",
set_game, called by MainWindow when a manager opens and when it goes back to
game select); none otherwise.

One level of rotation, once per process: init_log moves the previous run's
volt.log to volt.log.prev (replacing any older one), then starts a fresh file.
A previous run that logged nothing but its own startup header is deleted
instead, so .prev keeps the last run that actually did something. Never
raises: a failed rotation just keeps appending, and a failed write is dropped
- logging must never break the app. When not even the startup header can be
written (a read-only folder), init_log returns None and the run has no log.

Also in <base>/logs/: volt-crash.log (+ .prev, _enable_crash_log) and the
updater's apply.log (+ .prev, update.py). Uncaught exceptions - the main
thread, Qt slots / timers / event handlers (PySide6 reports those through
PyErr_Print, i.e. sys.excepthook) and threads - are logged with their
traceback (_install_hooks).

Plain file appends, not the stdlib `logging` module: one file, one format,
every line on disk as soon as log() returns (so a crash still leaves it), and
no global logging config for a dependency to trip over.
"""

import atexit
import faulthandler
import json
import os
import re
import sys
import threading
import traceback
import zipfile
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

LOG_DIR = "logs"  # <base>/logs/: every log VOLT writes (0.6.45)
LOG_NAME = "volt.log"
CRASH_LOG_NAME = "volt-crash.log"
REPORT_CRASH_TAIL = 200_000  # write_report keeps only this much of any file (~200 KB)

_file: Path | None = None  # unset until init_log: log() is then a no-op
_game: str | None = None  # the open manager's slug (set_game): every line's tag
_crash_file = None  # the open volt-crash.log faulthandler writes to (must stay open)
_crash_path: Path | None = None
_hooked = False  # excepthooks + atexit installed (once per process)


def _now() -> str:
    # Same shape as Electron's toISOString(): 2026-09-26T16:44:00.123Z
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _append(line: str) -> None:
    # utf-8 explicitly: Windows' default code page can't encode "…", "—", etc.
    with open(_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log(message: str) -> None:
    """Appends one timestamped line, tagged with the open game's slug. No-op
    before init_log / with no log file."""
    if _file is None:
        return
    try:
        game = _thread_game()
        _append(f"[{_now()}] {f'[{game}] ' if game else ''}{message}")
    except Exception:
        pass  # logging must never crash or block the app


def log_file() -> Path | None:
    """This run's volt.log, None when there is none (Settings / Help use it)."""
    return _file


def _thread_game() -> str | None:
    """The tag for a line logged on this thread: the main thread's is the open
    game (_game); a worker thread's is the one it was created under (0.6.46:
    _install_hooks stamps every threading.Thread with its creator's tag), so a
    job that finishes after its manager closed - or after another game opened -
    still logs under its own game."""
    ident = threading.get_ident()
    if ident == threading.main_thread().ident:
        return _game
    # Not current_thread(): for a thread Python didn't start it makes a _DummyThread, whose
    # __init__ (the wrapped one below) would land here again.
    t = next((t for t in threading.enumerate() if t.ident == ident), None)
    return getattr(t, "_volt_game", _game)


def set_game(slug: str | None, app_root=None) -> None:
    """A game's manager opened (slug, its per-game app root) or closed (None).
    Logs "left game" / "game opened" and tags every later main-thread line with
    the slug (worker threads keep the tag they were started under, _thread_game).
    ponytail: a QTimer / queued-signal callback of a closed screen runs on the
    main thread and gets the current tag; tag those explicitly if one misleads."""
    global _game
    if _game is not None:
        log(f"left game {_game}")
    _game = None
    if slug:
        _game = slug
        log(f"game opened: {slug} (app root {app_root})")


def init_log(base_root: Path) -> Path | None:
    """Once per process, at app start: creates <base>/logs/, rotates the
    previous run's log, writes the startup header (version, base root), then
    the crash log and the exception hooks. A second call returns the same file.

    Returns the log file path, or None when it couldn't be written (no log
    this run; log() is then a no-op).
    """
    global _file
    if _file is not None:
        return _file
    folder = Path(base_root) / LOG_DIR
    path = folder / LOG_NAME
    rotate_error = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            if sum(1 for line in text.splitlines() if line.strip()) > 1:
                os.replace(path, path.with_name(LOG_NAME + ".prev"))  # overwrites an existing .prev, Windows included
            else:
                path.unlink()  # header-only (or empty): leave .prev alone
    except Exception as err:
        rotate_error = err
    _file = path
    try:
        try:
            v = version("volt-py")
        except Exception:
            v = "unknown"
        _append(f"=== VOLT (Python) started, v{v}, {_now()}, base {Path(base_root)} ===")
    except Exception:
        pass  # see log()
    if not path.is_file():  # header write failed (read-only folder): no log
        _file = None
        return None
    if rotate_error is not None:
        log(f"log rotation failed, appending to the existing log instead: {rotate_error}")
    _enable_crash_log(folder / CRASH_LOG_NAME)
    _install_hooks()
    return _file


def _enable_crash_log(path: Path) -> None:
    """A hard crash (a segfault in Qt, say) never reaches log(): faulthandler
    dumps every thread's Python stack into <base>/logs/volt-crash.log instead.
    The file exists only while VOLT runs (empty: faulthandler writes nothing
    until a fatal error) and after a crash: shutdown() deletes it on a clean
    exit. At start, a non-empty one is the last run's crash -> volt-crash.log.prev
    (replacing an older one); an empty one (a hard kill, no crash) is deleted.
    So at most two files, no header, no growth."""
    global _crash_file, _crash_path
    prev = path.with_name(CRASH_LOG_NAME + ".prev")
    try:
        if path.exists():
            if path.stat().st_size:
                os.replace(path, prev)
                log(f"previous run crashed: its stack is saved in {prev}")
            else:
                path.unlink()
        f = open(path, "w", encoding="utf-8")
        faulthandler.enable(file=f, all_threads=True)
    except Exception as err:
        log(f"crash log {path} couldn't be enabled: {err!r}")
        return
    _crash_file, _crash_path = f, path


def shutdown() -> None:
    """Clean exit (atexit; the app's quit paths all end in sys.exit): logs it,
    closes volt-crash.log and deletes it. Anything faulthandler wrote while
    the process still exited normally (Windows reports some handled
    exceptions) isn't a crash: it is copied into volt.log first. Never raises."""
    global _crash_file
    if _game is not None:
        set_game(None)
    log("VOLT exiting normally")
    f, _crash_file = _crash_file, None
    if f is None:
        return
    try:
        faulthandler.disable()
        f.close()
        text = _crash_path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            log(f"faulthandler recorded this during a run that still exited normally (not a crash):\n{text.rstrip()}")
        _crash_path.unlink()
    except Exception as err:
        log(f"crash log {_crash_path} couldn't be closed/removed: {err!r}")


def _install_hooks() -> None:
    """sys.excepthook (the main thread and, via PyErr_Print, exceptions in Qt
    slots / timers / overridden event handlers) and threading.excepthook log
    the full traceback, then chain to the previous hook (stderr as before).
    Also stamps new threads with their creator's game tag (_thread_game)."""
    global _hooked
    if _hooked:
        return
    _hooked = True
    prev_sys, prev_thread = sys.excepthook, threading.excepthook

    def sys_hook(exc_type, exc, tb):
        log("UNCAUGHT EXCEPTION:\n" + "".join(traceback.format_exception(exc_type, exc, tb)).rstrip())
        prev_sys(exc_type, exc, tb)

    def thread_hook(args):
        if args.exc_type is not SystemExit:  # the default hook ignores it silently too
            name = args.thread.name if args.thread is not None else "?"
            log(f"UNCAUGHT EXCEPTION in thread {name}:\n"
                + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)).rstrip())
        prev_thread(args)

    sys.excepthook, threading.excepthook = sys_hook, thread_hook
    atexit.register(shutdown)

    # Every thread carries the game tag of the thread that created it (no
    # contextvars: threads don't inherit them before 3.14's opt-in flag).
    # One stdlib wrap here instead of a tag argument at each of the ~20 job starts.
    thread_init = threading.Thread.__init__

    def init(self, *args, **kwargs):
        thread_init(self, *args, **kwargs)
        self._volt_game = _thread_game()

    threading.Thread.__init__ = init


def clip(value, max_chars: int = 4000) -> str:
    """`value` as text (str as-is, else JSON, else str()), capped at max_chars
    so one huge value (a mod list, a manifest) can't make a line enormous."""
    if isinstance(value, str):
        s = value
    else:
        try:
            s = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            s = str(value)
    if len(s) > max_chars:
        return f"{s[:max_chars]}…[truncated, {len(s)} chars total]"
    return s


def read_tail(path, max_bytes: int) -> str:
    """The last `max_bytes` of a UTF-8 text file (the whole file when it's
    smaller), starting at a line boundary when cut. OSError if unreadable."""
    with open(path, "rb") as f:
        size = f.seek(0, os.SEEK_END)
        f.seek(max(0, size - max_bytes))
        data = f.read()
    if size > max_bytes:
        data = data.split(b"\n", 1)[1] if b"\n" in data else data
    return data.decode("utf-8", errors="replace")


def troubleshooting_text(fields, log_path=None, lines: int = 50) -> str:
    """Settings > Troubleshooting's "Copy troubleshooting info": one
    "Key: value" line per (key, value) in `fields`, then the last `lines`
    lines of the log (or why there are none). Plain text, no markdown."""
    out = [f"{k}: {'(none)' if v in (None, '') else v}" for k, v in fields]
    if log_path is None:
        out += ["", "Log: none (no log file for this run)"]
    else:
        try:
            tail = read_tail(log_path, 64 * 1024).splitlines()[-lines:]
        except OSError as err:
            out += ["", f"Log: couldn't read {log_path}: {err}"]
        else:
            out += ["", f"Last {len(tail)} lines of {log_path}:", *tail]
    return "\n".join(out) + "\n"


# ---- Help > Report a problem (0.6.24, PLAN.md §10 (i)) ----
REPORT_NOTE_NAME = "report.txt"
# Every file in <base>/logs/ (apply.log*: update.APPLY_LOG / APPLY_LOG_PREV).
REPORT_FILES = (LOG_NAME, LOG_NAME + ".prev", CRASH_LOG_NAME, CRASH_LOG_NAME + ".prev", "apply.log", "apply.log.prev")


def scrub_home(text: str, home=None) -> str:
    """`text` with the user's home folder (C:\\Users\\<name>) replaced by "~",
    whatever the slashes (\\, /, or JSON's doubled \\\\) and letter case, so a
    report doesn't carry the Windows user name. Other paths (the game, a
    Steam library) are kept: they're what a helper needs. `home`: for tests."""
    home = str(home if home is not None else Path.home())
    parts = [p for p in re.split(r"[\\/]+", home) if p]
    if len(parts) < 2:  # no real home folder (a bare drive or root): nothing to scrub
        return text
    lead = r"[\\/]+" if home[:1] in "\\/" else ""  # /home/<name> keeps its root slash in the match
    pattern = lead + r"[\\/]+".join(re.escape(p) for p in parts) + r"(?![^\\/\s\"'])"
    return re.sub(pattern, "~", text, flags=re.IGNORECASE)


def write_report(dest, fields, log_path=None, home=None) -> list[str]:
    """Help > Report a problem: a zip at `dest` holding report.txt (one
    "Key: value" line per (key, value) in `fields`) and, from log_path's
    folder (<base>/logs/), REPORT_FILES that exist and aren't empty (the last
    REPORT_CRASH_TAIL characters of a bigger one), every text with the home
    folder scrubbed (scrub_home). Stdlib only, nothing leaves the computer.
    Returns the names written into the zip. OSError on a failed write."""
    note = "VOLT problem report\n\n" + "".join(f"{k}: {'(none)' if v in (None, '') else v}\n" for k, v in fields)
    names = [REPORT_NOTE_NAME]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(REPORT_NOTE_NAME, scrub_home(note, home))
        if log_path is not None:
            folder = Path(log_path).parent
            for name in REPORT_FILES:
                path = folder / name
                if path.is_file() and path.stat().st_size:  # this run's volt-crash.log is open and empty
                    text = path.read_text(encoding="utf-8", errors="replace")
                    if len(text) > REPORT_CRASH_TAIL:
                        text = f"[truncated: last {REPORT_CRASH_TAIL} of {len(text)} characters]\n" + text[-REPORT_CRASH_TAIL:]
                    z.writestr(path.name, scrub_home(text, home))
                    names.append(path.name)
    return names
