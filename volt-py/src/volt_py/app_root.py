"""Base APP-ROOT resolution (port of Electron's src/electron/lib/appRoot.js).

The base root is where VOLT keeps its per-run data (window-state.ini today;
per-game subfolders later, as in Electron's resolveAppRoot). Resolved as:
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

    The one dev-vs-packaged check: resolve_base_root and applog (dev-only
    logging) both use it, so fixing the signal here fixes both.
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


def resolve_app_root(slug: str, env: Mapping[str, str] | None = None) -> Path:
    """Per-game APP-ROOT: <base root>/<slug> (Electron's resolveAppRoot).

    Holds that game's settings.json, load-orders/, log, etc.
    """
    return resolve_base_root(env) / slug
