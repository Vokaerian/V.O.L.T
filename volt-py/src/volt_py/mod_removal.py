"""Remove completely (the RimWorld mod right-click menu, RIMWORLD.md #52):
delete a mod's files from every place VOLT scans, so neither the Active nor
the Inactive list picks it up again. Pure Python, no Qt: the screen shows
the plan in its confirm, then runs it (RimWorldMainScreen._remove_completely).

What it may delete, and nothing else:
  - every folder directly under <game>/Mods that holds this mod: a hand-
    installed copy, a SteamCMD copy (marker'd) or a broken <Mods>/<wid>;
  - optionally (the confirm's checkbox, off by default) the SteamCMD
    library's cached copy, <app_root>/steamcmd-library/.../294100/<wid>;
  - a folder in Steam's Workshop content folder (a digits-only item folder)
    ONLY when Steam, asked by the caller, says it is NOT subscribed (a
    leftover; user decision 2026-09-30) - run_removal refuses otherwise.
Refused outright: an official Core/DLC mod (source 'official' or a
'ludeon.*' package id). A subscribed Workshop item is refused by the caller
after asking Steam (subscribed_refusal: Unsubscribe's job). Every path is
re-checked right before the delete (a direct child of the expected parent;
the library and Workshop ones a digits-only name).
Deletes are best effort (fsutil.remove_tree_best_effort): a locked file is
skipped and reported, never fatal.
"""

import os
import re
from pathlib import Path

from . import mods as mods_mod
from .fsutil import is_dir, remove_tree_best_effort
from .mod_list_io import not_found_workshop_id
from .paths import has_steam_appid, mod_roots, workshop_dir_for
from .steam_cmd import content_dir, find_item, library_copy
from .steam_ops import workshop_page


def _is_child(path, parent) -> bool:
    """`path` sits directly inside `parent` (lexically: a link named there
    is removed as a link, never followed - remove_tree_best_effort)."""
    return os.path.dirname(os.path.abspath(str(path))) == os.path.abspath(str(parent))


def plan_removal(game_dir, app_root, row_id: str, mod: dict | None) -> dict:
    """What Remove completely would delete for list row `row_id` (`mod`: its
    scanned mod, None for a not-found row). Returns {"refuse": message or
    None, "mods": [folders under <game>/Mods], "workshop": [folders in
    Steam's Workshop content folder], "library": the library copy or None,
    "wid": the Workshop id when known}. Scans the mod roots itself (a fresh
    look, so hidden duplicates count too). A "workshop" folder may only be
    deleted once the caller has asked Steam and it is NOT subscribed
    (run_removal refuses otherwise): a leftover, e.g. a folder Steam kept
    after an unsubscribe with no About.xml in it (user decision 2026-09-30)."""
    ws_dir = workshop_dir_for(game_dir) if has_steam_appid(game_dir) else None
    wid = mods_mod.workshop_id(mod) or not_found_workshop_id(row_id, {})
    pkg = mod["id"] if mod else (None if wid else str(row_id).lower())  # a not-found row's id is its lowercased packageId
    lib = library_copy(app_root, wid or pkg)
    if not wid:
        found = lib or (find_item(ws_dir, pkg) if ws_dir else None)
        wid = found[0] if found else None
    name = mod["name"] if mod else row_id
    plan = {"refuse": None, "mods": [], "workshop": [], "library": lib[1] if lib else None, "wid": wid}
    if (mod and mod["source"] == "official") or (pkg or "").startswith("ludeon."):
        plan["refuse"] = f"{name} is part of RimWorld itself (Core or a DLC), so VOLT never deletes it."
        return plan
    mods_dir = Path(game_dir) / "Mods"
    for root in mod_roots(game_dir):
        for r in mods_mod.scan_dir(root["dir"], root["source"]):
            m = r.get("mod")
            if not m or not ((pkg and m["id"] == pkg) or (wid and m["folder"] == wid and root["source"] != "official")):
                continue
            if root["source"] == "official":
                plan["refuse"] = f"{name} shares its package id with an official RimWorld folder ({m['path']}), so VOLT won't delete it."
                return plan
            if root["source"] == "workshop":
                if not re.fullmatch(r"\d{1,20}", m["folder"], re.ASCII):
                    plan["refuse"] = (f"{name} has a copy in Steam's Workshop folder that isn't a Workshop item folder "
                                      f"({m['path']}), so VOLT won't delete it.")
                    return plan
                plan["workshop"].append(Path(m["path"]))
                continue
            plan["mods"].append(Path(m["path"]))
    if wid and is_dir(mods_dir / wid) and Path(mods_dir / wid) not in plan["mods"]:
        plan["mods"].append(mods_dir / wid)  # a broken copy that didn't scan as a mod
    if wid and ws_dir and is_dir(ws_dir / wid) and Path(ws_dir / wid) not in plan["workshop"]:
        plan["workshop"].append(ws_dir / wid)  # e.g. a leftover Steam kept with no About.xml
    return plan


def workshop_ids(plan: dict) -> list[str]:
    """The Workshop ids of plan["workshop"]'s folders: what to ask Steam about."""
    return [Path(p).name for p in plan.get("workshop") or []]


def subscribed_refusal(name: str, wids: list[str]) -> str:
    """The message when Steam reports the item still subscribed."""
    return (f"{name} is subscribed on Steam (Workshop item {', '.join(wids)}), and VOLT never deletes a subscribed "
            "item's folder from here. Unsubscribe from it first (Unsubscribe in this menu, or on its Workshop page "
            f"in Steam: {workshop_page(wids[0])}), then use Remove completely for anything left behind.")


def run_removal(game_dir, app_root, plan: dict, include_library: bool) -> list[dict]:
    """Deletes what plan_removal listed (the library copy only when
    `include_library`; Steam Workshop folders only when the caller set
    plan["workshop_not_subscribed"] after Steam said no - else ValueError),
    re-checking every path first. One {"path", "removed", "skipped", "gone"}
    per folder; a path that fails the check is {"path", "refused": why} and
    is never touched."""
    if plan.get("refuse"):
        raise ValueError(plan["refuse"])
    if plan.get("workshop") and not plan.get("workshop_not_subscribed"):
        raise ValueError("Steam wasn't asked whether the Workshop item is subscribed, so its folder was left alone.")
    mods_dir = Path(game_dir) / "Mods"
    targets = [(p, mods_dir) for p in plan["mods"]]
    targets += [(p, workshop_dir_for(game_dir)) for p in plan.get("workshop") or []]
    if include_library and plan.get("library"):
        targets.append((plan["library"], content_dir(app_root)))
    out = []
    for path, parent in targets:
        folder = os.path.basename(os.path.abspath(str(path)))
        if not _is_child(path, parent) or folder in ("", ".", "..") or (
                parent != mods_dir and not re.fullmatch(r"\d{1,20}", folder, re.ASCII)):
            out.append({"path": Path(path), "refused": f"not directly inside {parent}"})
            continue
        out.append({"path": Path(path), **remove_tree_best_effort(path)})
    return out
