"""One-time migration of the Electron app's load orders into volt-py.

Electron (dev mode; no packaged Electron build ever existed) keeps its
load orders at <VOLT project root>/src/dev-app-root/<slug>/load-orders/
<folder>/loadorder.json, camelCase keys. On a fresh volt-py install (no
load orders of its own yet) those are copied over once, through
load_orders.create_load_order - which slugs, dedupes ids and writes the
snake_case manifest. Never runs again once volt-py has any load order.

Pure stdlib: no PySide6, so it runs under tools/checks/.
"""

import os
import sys
from pathlib import Path

from . import load_orders
from .fsutil import read_json

# This file is volt-py/src/volt_py/electron_import.py: parents[2] is the
# volt-py project root (same as app_root.py), and its parent is the VOLT
# project root, which also holds Electron's src/.
_VOLT_ROOT = Path(__file__).resolve().parents[2].parent


def electron_dev_app_root(slug: str) -> Path:
    """Electron's dev-mode per-game APP-ROOT (see src/electron/lib/appRoot.js)."""
    return _VOLT_ROOT / "src" / "dev-app-root" / slug


def find_electron_manifests(electron_root) -> list[tuple[str, dict]]:
    """(folder name, raw manifest) for each <electron_root>/<folder>/loadorder.json.

    electron_root is the load-orders/ directory itself. Missing -> [].
    Unreadable or non-object manifests are skipped with a stderr note.
    """
    try:
        entries = sorted(os.scandir(electron_root), key=lambda e: e.name)
    except FileNotFoundError:
        return []
    out = []
    for e in entries:
        if not e.is_dir():
            continue
        file = Path(e.path) / load_orders.MANIFEST_FILE
        if not file.is_file():
            continue
        try:
            raw = read_json(file)
        except (OSError, ValueError) as err:  # JSONDecodeError / UnicodeDecodeError are ValueErrors
            print(f"[electron_import] skipping {file}: {err}", file=sys.stderr)
            continue
        if not isinstance(raw, dict):
            print(f"[electron_import] skipping {file}: not a JSON object", file=sys.stderr)
            continue
        out.append((e.name, raw))
    return out


def import_electron_load_orders_if_needed(app_root, slug: str) -> list[str]:
    """Copies Electron's load orders in, only when volt-py has none. Returns new slugs."""
    if load_orders.list_load_orders(app_root):
        return []
    created = []
    for folder, raw in find_electron_manifests(electron_dev_app_root(slug) / load_orders.DIR_NAME):
        name = raw.get("name")
        display = name if isinstance(name, str) and name.strip() else folder
        try:
            m = load_orders.create_load_order(
                app_root, display, active=raw.get("active"), inactive=raw.get("inactive")
            )
        except ValueError as err:
            print(f"[electron_import] couldn't import {folder!r}: {err}", file=sys.stderr)
            continue
        created.append(m["slug"])
    return created
