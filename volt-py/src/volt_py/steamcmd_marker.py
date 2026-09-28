"""SteamCMD copy marker file (port of the marker section of Electron's
src/electron/lib/steamCmd.js; the download engine itself is steam_cmd.py).

A mod folder VOLT copied into <game>/Mods from a SteamCMD download carries a
MARKER file recording which acquisition mode made the copy: 'steamcmd' (a
temporary copy Sync to Steam later replaces) or 'gog' (the mod's permanent
home). The payload is {"mode": ..., "copiedAt": "<ISO time>"}; before the
mode field existed (v0.3.9-v0.4.1) it held just an ISO timestamp line or
nothing, which reads as 'steamcmd'.
"""

import json
import os
import sys
from datetime import datetime, timezone

from .fsutil import exists

MARKER = ".volt-steamcmd"
# Pre-0.4.10 name of MARKER. Only read_marker_mode knows it: it renames a
# leftover one to MARKER in place, so nothing else needs to check both names.
LEGACY_MARKER = ".rwjsc-steamcmd"
# 'pinned' is reserved for future per-load-order pinning with its own marker
# file (SCOPE.md §2a) - deliberately not one of these.
MARKER_MODES = ("steamcmd", "gog")


def marker_text(mode: str) -> str:
    # "copiedAt" stays camelCase on purpose: it's an on-disk file format that
    # real markers written by the Electron build already use.
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return json.dumps({"mode": mode, "copiedAt": now}, separators=(",", ":")) + "\n"


def parse_marker_mode(text) -> str:
    """'gog' only when the JSON payload says so; anything else (older marker,
    unparseable text, unknown mode) is 'steamcmd'. Never raises."""
    try:
        v = json.loads(("" if text is None else str(text)).removeprefix("﻿"))
    except ValueError:
        return "steamcmd"
    return "gog" if isinstance(v, dict) and v.get("mode") == "gog" else "steamcmd"


def read_marker_mode(dir) -> str | None:
    """Mode of <dir>/MARKER: None when there's no marker (not VOLT's copy).
    A marker that exists but can't be read still counts as 'steamcmd'. A
    LEGACY_MARKER with no MARKER beside it is renamed first."""
    legacy = os.path.join(dir, LEGACY_MARKER)
    marker = os.path.join(dir, MARKER)
    if exists(legacy) and not exists(marker):
        try:
            os.rename(legacy, marker)
        except OSError as e:
            # ponytail: stderr until VOLT's log subsystem is ported.
            print(f"[steamcmd] couldn't migrate legacy {LEGACY_MARKER} marker in {dir}: {e}", file=sys.stderr)
    try:
        # errors="replace": Node's readFile(..., 'utf8') never fails on bad bytes.
        with open(marker, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        return "steamcmd"
    return parse_marker_mode(text)
