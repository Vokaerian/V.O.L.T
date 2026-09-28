"""Valheim main screen (VALHEIM.md PLAN item 3, stage 3b): the Thunderstore/
BepInEx manager screen (screens/bepinex_main_screen.py) bound to Valheim's
own module (valheim.py: constants, detection, the framework package) and
Help entries. The next BepInEx game is this file with its own module and
entries (`CLAUDE.md` §6's "the next BepInEx game can largely copy-paste").
"""

from PySide6.QtWidgets import QWidget

from volt_py import valheim
from volt_py.screens.bepinex_main_screen import BepInExMainScreen
from volt_py.screens.valheim_help_entries import VALHEIM_HELP_ENTRIES


class ValheimMainScreen(BepInExMainScreen):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(valheim, VALHEIM_HELP_ENTRIES, parent)
