"""Load orders (port of Electron's src/electron/lib/loadOrders.js, SCOPE.md
§2a): one folder per load order under APP-ROOT/load-orders/<slug>/, holding
loadorder.json (the manifest). Mods stay in the real Mods folder and are
referenced by lowercased packageId.

Manifest (schema_version 1). Keys are snake_case, so - like settings.json -
this file is NOT interchangeable with Electron's camelCase manifests:
{
  "schema_version": 1,
  "name": "My first load order!",        # display name; folder name is the slug
  "created_at": "<ISO>", "updated_at": "<ISO>",
  "active":   ["brrainz.harmony", ...],  # ordered = load order
  "inactive": ["some.mod", ...],         # snapshot of the inactive pane at save time
  "pinning": {                           # schema only - copying is NOT implemented yet
    "enabled": false, "use_local_copies": false, "dir": "pinned", "mods": {}
  }
}
Unknown top-level fields are preserved (forward compatibility).
"""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .fsutil import read_json, write_json
from .ids import clean_ids
from .mods import natural_key
from .slug import is_valid_slug, slugify

DIR_NAME = "load-orders"
MANIFEST_FILE = "loadorder.json"
SCHEMA_VERSION = 1

# Electron-era spellings of known fields: dropped from the "unknown keys" we
# carry along, so they never ride next to their snake_case twins.
_CAMEL = {"schemaVersion", "createdAt", "updatedAt"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_orders_root(app_root) -> Path:
    return Path(app_root) / DIR_NAME


def default_pinning() -> dict:
    return {"enabled": False, "use_local_copies": False, "dir": "pinned", "mods": {}}


def assert_slug(slug) -> None:
    # The one guard between a slug and filesystem traversal - keep it strict.
    if not is_valid_slug(slug):
        raise ValueError(f"Invalid load order id: {slug!r}")


def manifest_path(app_root, slug) -> Path:
    assert_slug(slug)
    return load_orders_root(app_root) / slug / MANIFEST_FILE


def normalize_manifest(raw, slug: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("manifest is not a JSON object")
    ver = raw.get("schema_version")
    if isinstance(ver, (int, float)) and not isinstance(ver, bool) and ver > SCHEMA_VERSION:
        raise ValueError(f"manifest schema_version {ver} is newer than this app supports ({SCHEMA_VERSION})")
    name = raw.get("name")
    pinning = raw.get("pinning")
    return {
        **{k: v for k, v in raw.items() if k not in _CAMEL},
        "slug": slug,
        "schema_version": SCHEMA_VERSION,
        "name": name if isinstance(name, str) and name.strip() else slug,
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "active": clean_ids(raw.get("active")),
        "inactive": clean_ids(raw.get("inactive")),
        "pinning": {**default_pinning(), **(pinning if isinstance(pinning, dict) else {})},
    }


def list_load_orders(app_root) -> list[dict]:
    try:
        entries = list(os.scandir(load_orders_root(app_root)))
    except FileNotFoundError:
        return []
    out = []
    for e in entries:
        if not e.is_dir() or not is_valid_slug(e.name):
            continue
        try:
            m = normalize_manifest(read_json(manifest_path(app_root, e.name)), e.name)
            out.append({"slug": e.name, "name": m["name"], "updated_at": m["updated_at"], "active_count": len(m["active"])})
        except Exception as err:  # one bad manifest must not hide the rest
            out.append({"slug": e.name, "name": e.name, "error": str(err)})
    return sorted(out, key=lambda o: natural_key(o["name"]))


def create_load_order(app_root, name: str, active=None, inactive=None) -> dict:
    """New load order: slug the name, suffix -2, -3... on collision, then write its manifest."""
    display = ("" if name is None else str(name)).strip()
    if not display:
        raise ValueError("Load order name is empty")
    root = load_orders_root(app_root)
    root.mkdir(parents=True, exist_ok=True)
    base = slugify(display)
    for n in range(1, 1000):
        slug = base if n == 1 else f"{base}-{n}"
        try:
            (root / slug).mkdir()  # non-recursive: FileExistsError instead of reusing a folder
        except FileExistsError:
            continue
        now = _now()
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "name": display,
            "created_at": now,
            "updated_at": now,
            "active": clean_ids(active),
            "inactive": clean_ids(inactive),
            "pinning": default_pinning(),
        }
        write_json(manifest_path(app_root, slug), manifest)
        return normalize_manifest(manifest, slug)
    raise ValueError(f'Too many load orders named like "{display}"')


def load_load_order(app_root, slug) -> dict:
    return normalize_manifest(read_json(manifest_path(app_root, slug)), slug)


def save_load_order(app_root, slug, active=None, inactive=None) -> dict:
    """Writes the current active/inactive lists to the manifest. No effect on the game."""
    file = manifest_path(app_root, slug)
    raw = read_json(file)
    normalize_manifest(raw, slug)  # validates (e.g. refuses a newer schema)
    nxt = {
        **{k: v for k, v in raw.items() if k not in _CAMEL},
        "schema_version": SCHEMA_VERSION,
        "active": clean_ids(active),
        "inactive": clean_ids(inactive),
        "updated_at": _now(),
    }
    write_json(file, nxt)
    return normalize_manifest(nxt, slug)


def delete_load_order(app_root, slug) -> None:
    """Removes the load order's whole folder (manifest and anything beside it).
    Permanent - the caller confirms first. Mods themselves are never touched."""
    assert_slug(slug)  # never rmtree a path built from an unchecked slug
    shutil.rmtree(load_orders_root(app_root) / slug)
