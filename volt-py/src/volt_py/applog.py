"""Dev-mode action log at <app_root>/volt.log (idea ported from Electron's
src/electron/lib/log.js).

Dev only: in a packaged build (app_root.is_packaged()) init_log does nothing
and log() stays a no-op - unlike the Electron app, which always logs.

One level of rotation: each init_log() moves the previous run's volt.log to
volt.log.prev (replacing any older one), then starts a fresh file. A previous
run that logged nothing but its own startup header (it exited or crashed right
away) is deleted instead, so .prev keeps the last run that actually did
something. Never raises: a failed rotation just keeps appending, and a failed
write is dropped - logging must never break the app.

Plain file appends, not the stdlib `logging` module: one file, one format,
every line on disk as soon as log() returns (so a crash still leaves it), and
no global logging config for a dependency to trip over.
"""

import json
import os
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from .app_root import is_packaged

LOG_NAME = "volt.log"

_file: Path | None = None  # unset until init_log: log() is then a no-op


def _now() -> str:
    # Same shape as Electron's toISOString(): 2026-09-26T16:44:00.123Z
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _append(line: str) -> None:
    # utf-8 explicitly: Windows' default code page can't encode "…", "—", etc.
    with open(_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log(message: str) -> None:
    """Appends one timestamped line. No-op before init_log / in packaged mode."""
    if _file is None:
        return
    try:
        _append(f"[{_now()}] {message}")
    except Exception:
        pass  # logging must never crash or block the app


def init_log(app_root: Path) -> Path | None:
    """Rotates the previous run's log and writes the startup header.

    Returns the log file path, or None in packaged mode (no logging at all).
    """
    global _file
    if is_packaged():
        _file = None
        return None
    _file = Path(app_root) / LOG_NAME
    prev = _file.with_name(LOG_NAME + ".prev")
    rotate_error = None
    try:
        _file.parent.mkdir(parents=True, exist_ok=True)
        if _file.exists():
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
        _append(f"=== VOLT (Python) started, v{v}, {_now()} ===")
    except Exception:
        pass  # see log()
    if rotate_error is not None:
        log(f"log rotation failed, appending to the existing log instead: {rotate_error}")
    return _file


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
