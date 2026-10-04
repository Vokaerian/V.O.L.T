"""Action log at <app_root>/volt.log (idea ported from Electron's
src/electron/lib/log.js). On in every build, packaged included (user
directive 2026-09-30; it was dev-only before 0.6.6), as the Electron app
always logged. A packaged build's app root is <exe folder>/games/<slug>.

One level of rotation: each init_log() moves the previous run's volt.log to
volt.log.prev (replacing any older one), then starts a fresh file. A previous
run that logged nothing but its own startup header (it exited or crashed right
away) is deleted instead, so .prev keeps the last run that actually did
something. Never raises: a failed rotation just keeps appending, and a failed
write is dropped - logging must never break the app. When not even the startup
header can be written (a read-only app root), init_log returns None and the
run has no log, as if logging were off.

Rotation is once per app root per process: re-opening a game's manager in the
same run (the "Games" button, then its tile again - 0.6.8) keeps appending to
that run's volt.log under a "re-opened" header, so going back and forth never
rotates this run's log away or pushes the previous run's out of .prev.

Plain file appends, not the stdlib `logging` module: one file, one format,
every line on disk as soon as log() returns (so a crash still leaves it), and
no global logging config for a dependency to trip over.
"""

import faulthandler
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

LOG_NAME = "volt.log"
CRASH_LOG_NAME = "volt-crash.log"
REPORT_CRASH_TAIL = 200_000  # write_report keeps only this much of a file (~200 KB)

_file: Path | None = None  # unset until init_log: log() is then a no-op
_started: set[Path] = set()  # log files already rotated + started this process
_crash_file = None  # the open volt-crash.log faulthandler writes to (must stay open)


def _now() -> str:
    # Same shape as Electron's toISOString(): 2026-09-26T16:44:00.123Z
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _append(line: str) -> None:
    # utf-8 explicitly: Windows' default code page can't encode "…", "—", etc.
    with open(_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log(message: str) -> None:
    """Appends one timestamped line. No-op before init_log / with no log file."""
    if _file is None:
        return
    try:
        _append(f"[{_now()}] {message}")
    except Exception:
        pass  # logging must never crash or block the app


def init_log(app_root: Path) -> Path | None:
    """Rotates the previous run's log and writes the startup header (a
    re-opened game this run: no rotation, a "re-opened" header, see above).

    Returns the log file path, or None when it couldn't be written (no log
    this run; log() is then a no-op).
    """
    global _file
    _file = Path(app_root) / LOG_NAME
    prev = _file.with_name(LOG_NAME + ".prev")
    reopened = _file in _started
    _started.add(_file)
    rotate_error = None
    try:
        _file.parent.mkdir(parents=True, exist_ok=True)
        if _file.exists() and not reopened:
            text = _file.read_text(encoding="utf-8", errors="replace")
            if sum(1 for line in text.splitlines() if line.strip()) > 1:
                os.replace(_file, prev)  # overwrites an existing .prev, Windows included
            else:
                _file.unlink()  # header-only (or empty): leave .prev alone
    except Exception as err:
        rotate_error = err
    try:
        try:
            v = version("volt-py")
        except Exception:
            v = "unknown"
        _append(f"=== VOLT (Python) {'manager re-opened' if reopened else 'started'}, v{v}, {_now()} ===")
    except Exception:
        pass  # see log()
    if rotate_error is not None:
        log(f"log rotation failed, appending to the existing log instead: {rotate_error}")
    if not _file.is_file():  # header write failed (read-only folder): no log
        _file = None
    else:
        _enable_crash_log(_file.with_name(CRASH_LOG_NAME))
    return _file


def _enable_crash_log(path: Path) -> None:
    """A hard crash (a segfault in Qt, say) never reaches log(): faulthandler
    dumps every thread's Python stack into <app_root>/volt-crash.log instead,
    under a per-run header. Appended, never rotated, so the crashed run's
    stack survives the next launch.
    ponytail: unbounded append - crashes are rare; trim it if it ever grows."""
    global _crash_file
    try:
        f = open(path, "a", encoding="utf-8")
        f.write(f"=== VOLT (Python) run started {_now()} (a stack below this line = that run crashed) ===\n")
        f.flush()
        faulthandler.enable(file=f, all_threads=True)
    except Exception as err:
        log(f"crash log {path} couldn't be enabled: {err!r}")
        return
    old, _crash_file = _crash_file, f
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    # No success line in volt.log: a run that logged only its header must still count as empty (rotation, above).


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
    "Key: value" line per (key, value) in `fields`) and this game's volt.log,
    volt.log.prev and volt-crash.log (its last REPORT_CRASH_TAIL characters) when they exist, every text with the home folder
    scrubbed (scrub_home). Stdlib only, nothing leaves the computer.
    Returns the names written into the zip. OSError on a failed write."""
    note = "VOLT problem report\n\n" + "".join(f"{k}: {'(none)' if v in (None, '') else v}\n" for k, v in fields)
    names = [REPORT_NOTE_NAME]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(REPORT_NOTE_NAME, scrub_home(note, home))
        if log_path is not None:
            log_path = Path(log_path)
            for path in (log_path, log_path.with_name(log_path.name + ".prev"), log_path.with_name(CRASH_LOG_NAME)):
                if path.is_file():
                    text = path.read_text(encoding="utf-8", errors="replace")
                    if len(text) > REPORT_CRASH_TAIL:  # only volt-crash.log grows unbounded (append-only)
                        text = f"[truncated: last {REPORT_CRASH_TAIL} of {len(text)} characters]\n" + text[-REPORT_CRASH_TAIL:]
                    z.writestr(path.name, scrub_home(text, home))
                    names.append(path.name)
    return names
