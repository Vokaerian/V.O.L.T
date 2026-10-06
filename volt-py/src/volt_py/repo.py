"""R.E.P.O.'s own constants and path detection (REPO.md): the third
instance of the Thunderstore/BepInEx pattern, valheim.py's shape (the
contract tools/checks/volt_py_bepinex_games.py pins), one row in
bepinex_games.GAMES. Its manager screen is the shared one, Help text
included - no HELP_OVERRIDES needed (the pack injects winhttp.dll +
doorstop_config.ini like Lethal Company's).

Values read off the real install 2026-10-06 (Steam library common/REPO,
developer semiwork, Unity 2022.3.67f2): Mono backend (REPO_Data/Managed/
Assembly-CSharp.dll + MonoBleedingEdge/, no GameAssembly.dll), Windows-only
exe. The framework pack is the same generic BepInEx-BepInExPack Lethal
Company uses (5.4.2305 in the user's r2modman export, Doorstop 4.5.0).
AsyncLoggers exists for this game but is not assumed anywhere.

Steam only, Thunderstore the sole mod source (no Workshop, no config_dir).
"""

from pathlib import Path

from . import paths
from .bepinex_load_orders import ThunderstoreGame
from .fsutil import exists, is_dir

NAME = "R.E.P.O."  # shown in the manager screen's messages (screens/bepinex_main_screen.py)
SLUG = "repo"  # APP-ROOT folder name under games/ and the game-select tile key (screens/game_select.py)
COMMUNITY = "repo"  # Thunderstore community slug (thunderstore.io/c/repo/)
STEAM_APPID = "3241660"
STEAM_INSTALLDIR = "REPO"  # appmanifest installdir fallback when the .acf is missing (the real folder's name)
DATA_DIR = "REPO_Data"  # Unity data folder beside the exe (holds Managed/ - confirmed on the real install)
GAME_EXES = ["REPO.exe"]  # Windows only (UnityCrashHandler64.exe beside it is not the game)
FRAMEWORK_PACKAGE = "BepInEx-BepInExPack"  # the community's BepInEx pack (the same package as Lethal Company's)
EXAMPLE_PACKAGE = "Zehs-REPOLib"  # the Team-Package the Help window's Add mod entry quotes (most mods need it)
# No LAUNCH_ARG_EXAMPLES: R.E.P.O. has no well-known arguments of its own,
# so Settings > Launch shows the generic Unity ones
# (bepinex_settings_window.UNITY_LAUNCH_ARG_EXAMPLES).

GAME = ThunderstoreGame(slug=SLUG, community=COMMUNITY, framework_package=FRAMEWORK_PACKAGE)


def is_game_root(dir) -> bool:
    """A R.E.P.O. install: holds REPO_Data/ or the exe."""
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
    with R.E.P.O.'s appid / folder name / root check, or None."""
    return paths.find_steam_app(STEAM_APPID, STEAM_INSTALLDIR, is_game_root, tried)


def autodetect() -> dict:
    """Same shape as valheim.autodetect(): `game` is the pick, `games` every
    hit (Steam only), `tried` the folders looked at."""
    tried: list = []
    steam = find_steam_install(tried)
    games = [g for g in (steam,) if g]
    return {"game": games[0] if games else None, "games": games, "tried": tried}
