"""The game's real ModsConfig.xml (port of Electron's
src/electron/lib/modsConfig.js). Reading is harmless; writing happens ONLY via
push_mods_config (the "Push" action, SCOPE.md §2a). Push replaces just the
<activeMods> block and leaves everything else in the file byte-for-byte
(version, knownExpansions, BOM, line endings), after copying the current file
to ModsConfig.xml.volt-backup (a single rolling backup, overwritten each push).
"""

import re
import shutil
import sys
from pathlib import Path

from .fsutil import exists, is_dir, read_text, write_text_atomic
from .ids import clean_ids, is_writable_id
from .xml import escape_xml, get_ci, list_, parse_xml, text

FILE_NAME = "ModsConfig.xml"
BACKUP_SUFFIX = ".volt-backup"

_BLOCK = re.compile(r"^([ \t]*)(<activeMods\b[^>]*/>|<activeMods\b[^>]*>[\s\S]*?</activeMods\s*>)", re.M)
_CLOSE = re.compile(r"^([ \t]*)</ModsConfigData\s*>", re.M)


def mods_config_path(config_dir) -> Path:
    return Path(config_dir) / FILE_NAME


def read_mods_config(config_dir) -> dict:
    file = mods_config_path(config_dir)
    if not exists(file):
        return {"path": file, "exists": False, "version": None, "active_mods": [], "known_expansions": []}
    root = parse_xml(read_text(file))
    if root.tag.lower() != "modsconfigdata":
        root = None
    return {
        "path": file,
        "exists": True,
        "version": text(get_ci(root, "version")) or None,
        "active_mods": clean_ids(list_(get_ci(root, "activeMods"))),
        "known_expansions": list_(get_ci(root, "knownExpansions")),
    }


def render_active_mods(ids: list[str], indent: str, eol: str) -> str:
    if not ids:
        return "<activeMods />"
    child = indent + (indent or "  ")
    return eol.join(["<activeMods>", *(f"{child}<li>{escape_xml(i)}</li>" for i in ids), f"{indent}</activeMods>"])


def apply_active_mods(xml_text: str, ids: list[str]) -> str:
    """xml_text with its <activeMods> block replaced by `ids`; every other byte kept."""
    eol = "\r\n" if "\r\n" in xml_text else "\n"
    m = _BLOCK.search(xml_text)
    if m:
        return xml_text[: m.start()] + m[1] + render_active_mods(ids, m[1], eol) + xml_text[m.end() :]
    close = _CLOSE.search(xml_text)
    if not close:
        raise ValueError(
            "ModsConfig.xml doesn't look like a RimWorld mods config (no <ModsConfigData>); refusing to overwrite it"
        )
    indent = "  "
    return xml_text[: close.start()] + indent + render_active_mods(ids, indent, eol) + eol + xml_text[close.start() :]


def fresh_mods_config(ids: list[str], game_version: str | None, eol: str) -> str:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<ModsConfigData>"]
    if game_version:
        lines.append(f"  <version>{escape_xml(game_version)}</version>")
    lines += ["  " + render_active_mods(ids, "  ", eol), "</ModsConfigData>", ""]
    return eol.join(lines)


def push_mods_config(config_dir, active_ids: list[str], game_version: str | None = None) -> dict:
    if not is_dir(config_dir):
        raise ValueError(f"Config folder not found: {config_dir}. Launch RimWorld once, or set the folder manually.")
    all_ids = clean_ids(active_ids)
    ids = [i for i in all_ids if is_writable_id(i)]
    file = mods_config_path(config_dir)
    backup_path = None
    if exists(file):
        # encoding utf-8 (not -sig) + newline="": BOM and CRLF stay in the text.
        with open(file, encoding="utf-8", newline="") as f:
            out = apply_active_mods(f.read(), ids)
        backup_path = file.with_name(file.name + BACKUP_SUFFIX)
        shutil.copyfile(file, backup_path)
    else:
        out = fresh_mods_config(ids, game_version, "\r\n" if sys.platform == "win32" else "\n")
    write_text_atomic(file, out)
    return {"path": file, "backup_path": backup_path, "count": len(ids), "skipped": len(all_ids) - len(ids)}
