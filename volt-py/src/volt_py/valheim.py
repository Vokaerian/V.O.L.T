"""Valheim's own constants and path detection (VALHEIM.md SCOPE): the
per-game instance of the Thunderstore/BepInEx pattern. Everything generic
lives in thunderstore.py / bepinex_install.py / bepinex_load_orders.py; this
module holds only what differs per game. Every other BepInEx game (lethal.py;
R.E.P.O. next) is a module of this shape with its own values, one row in
bepinex_games.GAMES, and - only where its manager screen truly differs -
HELP_OVERRIDES / HELP_EXTRA for screens/bepinex_help_entries.py. The required
attributes are pinned by tools/checks/volt_py_bepinex_games.py.

Steam only - no GOG release, no Steam Workshop; Thunderstore is the sole mod
source, so paths.py's Workshop/Mods-folder/config-dir helpers don't apply
and there is no config_dir setting (THUNDERSTORE.md TODO #6).
"""

from pathlib import Path

from . import paths
from .bepinex_load_orders import ThunderstoreGame
from .fsutil import exists, is_dir

NAME = "Valheim"  # shown in the manager screen's messages (screens/bepinex_main_screen.py)
SLUG = "valheim"  # APP-ROOT folder name under games/ (app_root.resolve_app_root) and game-select id
COMMUNITY = "valheim"  # Thunderstore community slug (thunderstore.io/c/valheim/)
STEAM_APPID = "892970"  # the client; the dedicated server is a separate app (896660)
STEAM_INSTALLDIR = "Valheim"  # appmanifest installdir fallback when the .acf is missing
DATA_DIR = "valheim_Data"  # Unity data folder beside the exe (holds Managed/ - confirmed on the real install)
GAME_EXES = ["valheim.exe", "valheim.x86_64"]  # Windows / Linux; no macOS build
FRAMEWORK_PACKAGE = "denikson-BepInExPack_Valheim"  # Thunderstore's pinned BepInEx pack for this community
EXAMPLE_PACKAGE = "ValheimModding-Jotunn"  # the Team-Package the Help window's Add mod entry quotes
# Settings > Launch's examples, (arguments, what they do): Valheim's own
# -console plus Unity player options (docs.unity3d.com "Unity Standalone
# Player command line arguments"). A game without this list gets the window's
# generic Unity ones (bepinex_settings_window.UNITY_LAUNCH_ARG_EXAMPLES).
LAUNCH_ARG_EXAMPLES = (
    ("-console", "turns on the in-game console (F5)"),
    ("-window-mode exclusive", "exclusive fullscreen"),
    ("-screen-fullscreen 0", "starts in a window"),
    ("-screen-width 1920 -screen-height 1080", "sets the resolution"),
)

GAME = ThunderstoreGame(slug=SLUG, community=COMMUNITY, framework_package=FRAMEWORK_PACKAGE)


def is_game_root(dir) -> bool:
    """A Valheim install: holds valheim_Data/ or one of the game exes."""
    if not is_dir(dir):
        return False
    d = Path(dir)
    return is_dir(d / DATA_DIR) or any(exists(d / exe) for exe in GAME_EXES)


def find_game_exe(game_dir) -> Path | None:
    """The first GAME_EXES entry present directly in `game_dir`, else None."""
    if not game_dir:
        return None
    for name in GAME_EXES:
        exe = Path(game_dir) / name
        if exists(exe):
            return exe
    return None


def find_steam_install(tried: list | None = None) -> dict | None:
    """{"source": "steam", "game_dir", "steam_root"} via paths.find_steam_app
    with Valheim's appid / folder name / root check, or None."""
    return paths.find_steam_app(STEAM_APPID, STEAM_INSTALLDIR, is_game_root, tried)


def autodetect() -> dict:
    """Same shape as paths.autodetect() minus config_dir (none for Valheim):
    `game` is the pick, `games` every hit (Steam only), `tried` the folders
    looked at."""
    tried: list = []
    steam = find_steam_install(tried)
    games = [g for g in (steam,) if g]
    return {"game": games[0] if games else None, "games": games, "tried": tried}
