"""The Thunderstore/BepInEx games VOLT manages: one row per game module
(valheim.py's shape - the contract tools/checks/volt_py_bepinex_games.py
pins). A row here is what enables that game's tile on the game-select
screen (screens/game_select.py) and what main_window opens as a
BepInExMainScreen with screens/bepinex_help_entries.help_entries(module).
A module's SLUG must equal its tile's key there. RimWorld isn't a
Thunderstore game and has its own screen.
"""

from . import lethal, valheim

GAMES = (valheim, lethal)
BY_SLUG = {game.SLUG: game for game in GAMES}
