"""Base APP-ROOT resolution (port of Electron's src/electron/lib/appRoot.js).

The base root is where VOLT keeps its per-run data: window-state.ini at the
base itself, and one data folder per game under <base>/games/<slug>
(resolve_app_root; since 0.6.7 - it was <base>/<slug> before, which
migrate_legacy_app_root moves into place once). Resolved as:
 - VOLT_APP_ROOT env var, if set, always wins (testing / custom setups).
 - Packaged (unpacked-folder build): the folder containing the app's own
   executable, so the build stays portable - everything lives beside the exe.
 - Dev (`uv run volt-py`): volt-py/dev-app-root/. In dev, sys.executable is
   the venv's python.exe, so "folder of the exe" would point into .venv/.

Not ported yet: Electron's Linux AppImage branch (APPIMAGE env var) - Linux
builds come later, and a Nuitka Linux build won't be an Electron AppImage.
"""

import os
import sys
from collections.abc import Mapping
from pathlib import Path

# This file is volt-py/src/volt_py/app_root.py, so parents[0] is volt_py/,
# parents[1] is src/, parents[2] is the volt-py project root. Holds while the
# package runs from source (uv's default editable install), which is the only
# case this dev branch is used for.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# RimWorld's own slug. Hardcoded until game selection exists (Electron picks
# the slug on its game-selection screen; RimWorld is the only ported game).
GAME_SLUG = "rimworld"


def is_packaged() -> bool:
    """True in a packaged build, False when running from source (dev).

    The one dev-vs-packaged check (resolve_base_root uses it).
    """
    # Nuitka never sets sys.frozen; it defines a `__compiled__` global in every
    # compiled module instead (checked against Nuitka 4.2.2's source). sys.frozen
    # is kept for PyInstaller/cx_Freeze-style builds.
    return "__compiled__" in globals() or bool(getattr(sys, "frozen", False))


def resolve_base_root(env: Mapping[str, str] | None = None) -> Path:
    if env is None:
        env = os.environ
    override = env.get("VOLT_APP_ROOT")
    if override:
        return Path(override).resolve()
    if is_packaged():
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT / "dev-app-root"


GAMES_DIR = "games"  # <base>/games/<slug>: every game's data folder


def resolve_app_root(slug: str, env: Mapping[str, str] | None = None) -> Path:
    """Per-game APP-ROOT: <base root>/games/<slug> (Electron's resolveAppRoot
    used <base>/<slug>; VOLT did too before 0.6.7).

    Holds that game's settings.json, load-orders/, log, etc. Pure path math:
    the one-time move from the old location is migrate_legacy_app_root.
    """
    return resolve_base_root(env) / GAMES_DIR / slug


def migrate_legacy_app_root(slug: str, env: Mapping[str, str] | None = None) -> str | None:
    """Moves a pre-0.6.7 <base>/<slug> data folder to <base>/games/<slug>
    (settings, load orders, logs, steamcmd - everything, one rename).

    Call it before anything creates the new folder (init_log does), i.e.
    right after resolve_app_root in each game screen. Only moves when the old
    folder exists and the new one doesn't; never overwrites. Never raises.
    Returns a line for volt.log (the caller logs it after init_log - the log
    isn't open yet here), or None when there was nothing to do.
    """
    try:
        base = resolve_base_root(env)
        old, new = base / slug, base / GAMES_DIR / slug
        if not old.is_dir():
            return None
        if new.exists():
            return f"app root migration: both {old} and {new} exist - left both alone, using {new}"
        new.parent.mkdir(parents=True, exist_ok=True)
        # Same parent volume, so a plain atomic rename; fails whole (e.g. a
        # file in it held open on Windows) rather than half-moving.
        os.replace(old, new)
        return f"app root migration: moved {old} -> {new}"
    except Exception as err:
        return f"app root migration: moving {slug!r} data folder to {GAMES_DIR}/ failed, using the new path: {err!r}"
