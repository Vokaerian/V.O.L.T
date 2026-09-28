"""Mod id helpers (port of Electron's src/electron/lib/ids.js), shared by
scanning, ModsConfig.xml and load-order manifests. A mod id is its
lowercased packageId."""

# Fallback id for a mod whose About.xml has no packageId. Never pushed to ModsConfig.xml.
NO_PACKAGE_ID_PREFIX = "folder:"
# Pending Workshop placeholder (collection/rentry import of an item that isn't
# installed yet). May be saved in a load order; never pushed or exported.
PENDING_WORKSHOP_PREFIX = "workshop:"


def is_writable_id(mod_id: str) -> bool:
    """Whether an id may be written to a ModsConfig.xml (Push, RimPy .xml export)."""
    return not mod_id.startswith((NO_PACKAGE_ID_PREFIX, PENDING_WORKSHOP_PREFIX))


def exportable_ids(ids) -> list[str]:
    """lists.js exportableIds: ids for a shared export (rentry.co page, RimSort
    clipboard text, RimPy .xml) - pending "workshop:<id>" placeholders (not a
    real mod yet) and "folder:<name>" ids (no packageId) are left out."""
    return [i for i in ids if is_writable_id(i)]


def clean_ids(ids) -> list[str]:
    """Trim, lowercase, drop non-strings/empties/duplicates, keep order."""
    if not isinstance(ids, list):
        return []
    # dict.fromkeys: ordered dedupe.
    return list(dict.fromkeys(i for raw in ids if isinstance(raw, str) and (i := raw.strip().lower())))
