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


def resolve_base_root(env: Mapping[str, str] | None = None) -> Path:
    if env is None:
        env = os.environ
    override = env.get("VOLT_APP_ROOT")
    if override:
        return Path(override).resolve()
    # PLACEHOLDER, unverified: sys.frozen is the common "packaged" flag
    # (PyInstaller/cx_Freeze set it), but Nuitka doesn't always set it,
    # depending on build flags. Check against real Nuitka output once
    # packaging starts (CLAUDE.md §3) - Nuitka's own `__compiled__` global
    # may be the reliable test instead.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT / "dev-app-root"
