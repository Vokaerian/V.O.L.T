"""Per-game settings store, <app_root>/settings.json (port of Electron's
src/electron/lib/settings.js). Holds the resolved paths (autodetected or
picked manually), the last-opened load order, the user's per-mod colors and
the user's own Sort rules.

Keys are snake_case (Python naming), so this file is NOT interchangeable with
Electron's camelCase settings.json.
"""

import re
import sys
import uuid
from pathlib import Path

from .app_root import GAME_SLUG, resolve_app_root
from .fsutil import read_json, write_json

DEFAULTS = {
    "schema_version": 1,
    "game_dir": None,  # RimWorld install root; Mods folder = <game_dir>/Mods
    "game_source": None,  # 'steam' | 'gog' | 'manual'
    "config_dir": None,  # folder holding ModsConfig.xml
    "last_load_order": None,  # slug
    "mod_colors": {},  # mod id (lowercased packageId) -> '#rrggbb'; global, not per load order
    "ignored_scan_issues": [],  # scan problem paths hidden from the Scan issues window; global
    # User-created Sort rules (sort.py's top tier), global: a list, not keyed
    # by mod - several entries may name the same mod on purpose. Each entry:
    # {"id": uuid hex (how the UI addresses one entry), "mod": packageId,
    #  "load_before": [packageId, ...], "load_after": [packageId, ...]},
    # packageIds stored exactly as typed (sort.py matches case-insensitively).
    "user_rules": [],
    # Mod-acquisition mode ('steamcmd' | 'steamworks' | 'gog'), or None = not
    # chosen yet - the UI then uses 'gog' for a GOG install and 'steamcmd'
    # otherwise. Only set_steam_acquire_via stores a value.
    "steam_acquire_via": None,
    "skip_sync_confirm": False,  # True once "Don't ask me again" was ticked in Sync to Steam's heads-up dialog
    "share_dir": None,  # folder of the last Import / Export file pick (Thunderstore games' .r2z profiles)
    # Settings > General > Animations (phase 4): 'windows' = follow Windows'
    # "Animation effects", 'on' / 'off' override it (theme.animations_enabled).
    # Per game like every key here (there is no app-wide settings file); a
    # file from before 0.5.14 has no key and loads as 'windows'.
    "animations": "windows",
    # Settings > Launch (Thunderstore games): extra command-line arguments for
    # the game, as typed (bepinex_launch.parse_launch_args splits them at Run).
    "launch_args": "",
}

ACQUIRE_VIA = ("steamcmd", "steamworks", "gog")
ANIMATIONS = ("windows", "on", "off")


def effective_acquire_via(stored, game_source) -> str:
    """The acquisition mode in effect (lists.js effectiveAcquireVia): the
    stored choice when the user made one, else 'gog' for a GOG install and
    'steamcmd' otherwise. Only an explicit choice is ever stored, so the GOG
    auto-pick follows the detected install until the user picks something."""
    if stored in ACQUIRE_VIA:
        return stored
    return "gog" if game_source == "gog" else "steamcmd"


_HEX_COLOR = re.compile(r"#[0-9a-f]{6}", re.IGNORECASE)


class SettingsStore:
    def __init__(self, app_root: Path | None = None):
        if app_root is None:
            app_root = resolve_app_root(GAME_SLUG)
        self.file = Path(app_root) / "settings.json"
        self._cache: dict | None = None

    def get(self) -> dict:
        # ponytail: shallow copies like the JS spread; nested dict/list are
        # shared with the cache, so callers must not mutate them in place.
        if self._cache is None:
            try:
                self._cache = {**DEFAULTS, **read_json(self.file)}
            except FileNotFoundError:
                self._cache = dict(DEFAULTS)
            except (OSError, ValueError, TypeError) as err:
                print(f"[settings] ignoring unreadable {self.file}: {err}", file=sys.stderr)
                self._cache = dict(DEFAULTS)
        return dict(self._cache)

    def update(self, patch: dict) -> dict:
        self._cache = {**self.get(), **patch}
        write_json(self.file, self._cache)
        return dict(self._cache)

    def set_mod_color(self, id: str, color: str | None) -> dict:
        """color: '#rrggbb' to assign, None to clear. Returns the new mod_colors map."""
        if not isinstance(id, str) or not id:
            raise ValueError("set_mod_color expects a mod id.")
        if color is not None and not (isinstance(color, str) and _HEX_COLOR.fullmatch(color)):
            raise ValueError(f"Not a #rrggbb color: {color}")
        mod_colors = dict(self.get()["mod_colors"])
        if color:
            mod_colors[id] = color.lower()
        else:
            mod_colors.pop(id, None)
        return self.update({"mod_colors": mod_colors})["mod_colors"]

    def set_scan_issue_ignored(self, path: str, ignored: bool) -> list:
        """Adds/removes a scan problem's path from ignored_scan_issues. Returns the new list."""
        if not isinstance(path, str) or not path:
            raise ValueError("set_scan_issue_ignored expects a path.")
        rest = [x for x in (self.get()["ignored_scan_issues"] or []) if x != path]
        return self.update({"ignored_scan_issues": rest + [path] if ignored else rest})["ignored_scan_issues"]

    def add_user_rule(
        self, mod: str, load_before: list[str] | None = None, load_after: list[str] | None = None
    ) -> dict:
        """Appends a new user rule entry (always new, even if another entry
        already names `mod`; `mod` may be "" for a not-yet-filled entry) with
        a fresh id. Returns the new entry."""
        entry = {"id": uuid.uuid4().hex, "mod": _rule_mod(mod), "load_before": _rule_ids(load_before, "load_before"),
                 "load_after": _rule_ids(load_after, "load_after")}
        self.update({"user_rules": list(self.get()["user_rules"] or []) + [entry]})
        return entry

    def update_user_rule(self, rule_id: str, **fields) -> dict:
        """Changes mod / load_before / load_after (only the ones given) on the
        entry with that id. Raises ValueError for an unknown id or field.
        Returns the updated entry."""
        unknown = set(fields) - {"mod", "load_before", "load_after"}
        if unknown:
            raise ValueError(f"update_user_rule: unknown field(s) {sorted(unknown)}")
        patch = {k: _rule_mod(v) if k == "mod" else _rule_ids(v, k) for k, v in fields.items()}
        rules = list(self.get()["user_rules"] or [])
        for n, r in enumerate(rules):
            if isinstance(r, dict) and r.get("id") == rule_id:
                rules[n] = {**r, **patch}  # a new dict: never mutate the cached entry
                self.update({"user_rules": rules})
                return rules[n]
        raise ValueError(f"No user rule with id {rule_id!r}")

    def delete_user_rule(self, rule_id: str) -> list:
        """Removes the entry with that id (no-op if there is none). Returns the
        new user_rules list."""
        rules = list(self.get()["user_rules"] or [])
        rest = [r for r in rules if not (isinstance(r, dict) and r.get("id") == rule_id)]
        if len(rest) == len(rules):
            return rules
        return self.update({"user_rules": rest})["user_rules"]

    def set_steam_acquire_via(self, via: str) -> str:
        """An explicit choice: overrides the GOG-install auto-pick. Returns the stored value."""
        if via not in ACQUIRE_VIA:
            raise ValueError(f"Unknown download method: {via}")
        return self.update({"steam_acquire_via": via})["steam_acquire_via"]

    def set_animations(self, mode: str) -> str:
        """Settings > General > Animations. Returns the stored value."""
        if mode not in ANIMATIONS:
            raise ValueError(f"Unknown animation mode: {mode}")
        return self.update({"animations": mode})["animations"]

    def set_launch_args(self, text: str) -> str:
        """Settings > Launch's "Launch arguments", stored as typed. Returns the stored value."""
        if not isinstance(text, str):
            raise ValueError("Launch arguments must be text.")
        return self.update({"launch_args": text})["launch_args"]


def effective_animations(stored) -> str:
    """The animation mode in effect: the stored one, 'windows' for a missing
    or hand-edited value."""
    return stored if stored in ANIMATIONS else "windows"


def _rule_mod(mod) -> str:
    # Blank is allowed: the Rules window's New starts an entry with no mod yet,
    # and its mod field saves on every keystroke (clearing it to retype is
    # normal). sort.py skips an entry whose mod matches no active mod.
    if not isinstance(mod, str):
        raise ValueError("A user rule's mod must be a packageId string.")
    return mod


def _rule_ids(ids, field: str) -> list[str]:
    """None -> []; else a list/tuple of non-empty packageIds, copied as typed."""
    if ids is None:
        return []
    if not isinstance(ids, (list, tuple)) or not all(isinstance(x, str) and x.strip() for x in ids):
        raise ValueError(f"{field} must be a list of packageIds.")
    return list(ids)
