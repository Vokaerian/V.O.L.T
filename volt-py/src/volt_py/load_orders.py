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
  "pinning": {                           # Offline mods (offline_mods.py; 0.6.16): the load
    "enabled": false,                    # order's own frozen copies in <LO>/local-mods/<folder>;
    "use_local_copies": false,           # enabled = any entry. mods: {packageId: {folder, origin,
    "dir": "local-mods", "mods": {}      # workshop_id?, copied_at, size_bytes, source_path}}
  },
  "own_data": false                      # opt-in: Modded runs use <LO>/data as the game's
}                                        # data root (rimworld_launch.py; 0.6.15)
Unknown top-level fields are preserved (forward compatibility).
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from .fsutil import read_json, rmtree_force, write_json
from .ids import clean_ids
from .mods import natural_key
from .offline_mods import LOCAL_MODS_DIR, normalize_pinning
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
    return {"enabled": False, "use_local_copies": False, "dir": LOCAL_MODS_DIR, "mods": {}}


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
        "pinning": normalize_pinning(pinning, default_pinning()),
        "own_data": raw.get("own_data") is True,
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
            out.append({"slug": e.name, "name": m["name"], "updated_at": m["updated_at"], "active_count": len(m["active"]),
                        "own_data": m["own_data"]})
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
            "own_data": False,  # opt-in, never inherited (Copy to new starts without its own data)
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


def set_own_data(app_root, slug, on: bool) -> dict:
    """Turns the load order's own game data on / off (manifest only: turning
    it off never deletes <LO>/data, so turning it back on finds it again)."""
    file = manifest_path(app_root, slug)
    raw = read_json(file)
    normalize_manifest(raw, slug)  # validates (e.g. refuses a newer schema)
    nxt = {**{k: v for k, v in raw.items() if k not in _CAMEL}, "own_data": bool(on)}
    write_json(file, nxt)
    return normalize_manifest(nxt, slug)


def set_pinning(app_root, slug, pinning) -> dict:
    """Writes the load order's Offline mods block (offline_mods.py), normalized
    (enabled = any entry), and nothing else: the lists, updated_at and unknown
    fields stay as they are, so it never touches the unsaved-changes state."""
    file = manifest_path(app_root, slug)
    raw = read_json(file)
    normalize_manifest(raw, slug)  # validates (e.g. refuses a newer schema)
    nxt = {**{k: v for k, v in raw.items() if k not in _CAMEL}, "pinning": normalize_pinning(pinning, default_pinning())}
    write_json(file, nxt)
    return normalize_manifest(nxt, slug)


def delete_load_order(app_root, slug) -> None:
    """Removes the load order's whole folder (manifest and anything beside it,
    its own game data <LO>/data and its Offline copies <LO>/local-mods
    included - saves and settings; read-only files too).
    Permanent - the caller confirms first. Mods themselves are never touched."""
    assert_slug(slug)  # never rmtree a path built from an unchecked slug
    rmtree_force(load_orders_root(app_root) / slug)



def offline_index(app_root) -> list[tuple[str, dict]]:
    """(load order name, its Offline entries) for every readable load order:
    every manifest read once (an unreadable one is skipped - list_load_orders
    logs it). The removal confirms' "also kept Offline in" lookups (0.6.18)."""
    out = []
    for e in list_load_orders(app_root):
        if "error" in e:
            continue
        try:
            out.append((e["name"], load_load_order(app_root, e["slug"])["pinning"]["mods"]))
        except (OSError, ValueError):
            continue
    return out


def offline_holders(app_root, mod_id: str | None = None, workshop_id: str | None = None, index=None) -> list[str]:
    """Names of every load order keeping `mod_id` (a lowercased packageId) or
    the Workshop item `workshop_id` Offline (an entry's workshop_id, or a
    Workshop-id folder name). `index`: an offline_index() already read for
    this action (Sync checks many mods), else read now."""
    pid = (mod_id or "").strip().lower()
    wid = str(workshop_id) if workshop_id else None
    return [name for name, entries in (offline_index(app_root) if index is None else index)
            if (pid and pid in entries) or (wid and any(
                str(x.get("workshop_id")) == wid or x.get("folder") == wid for x in entries.values()))]
