"""VOLT main window (PySide6 app shell)."""

import sys
from importlib.metadata import version

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QMainWindow

from volt_py.app_root import resolve_base_root
from volt_py.screens.game_select import GameSelectScreen
from volt_py.screens.rimworld_main_screen import RimWorldMainScreen

DEFAULT_SIZE = (1600, 900)
MIN_SIZE = (1000, 600)
# 'resize' fires continuously while dragging, so saving is debounced.
SAVE_DEBOUNCE_MS = 500


def _read_int(settings: QSettings, key: str, fallback: int) -> int:
    # IniFormat hands values back as strings; anything missing or
    # non-numeric (hand-edited / corrupted file) falls back to the default.
    try:
        return int(settings.value(key, fallback))
    except (TypeError, ValueError):
        return fallback


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # Version comes from the installed package metadata, which tracks
        # pyproject.toml's [project] version (mirrors Electron's app.getVersion()).
        self.setWindowTitle(f"V. O. L. T. v{version('volt-py')}")

        # Debounced save (created before any resize() call, since resizeEvent
        # uses it): each resize restarts the single-shot timer (Electron's
        # clearTimeout/setTimeout). No flush on close - Electron parity, known
        # gap tracked in TODO.md #31.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._save_window_state)

        # Window size only, persisted at <base>/window-state.ini (not under a
        # per-game folder - the window exists before any game is chosen).
        # Port of Electron's lib/windowState.js; an explicit-path IniFormat
        # file, never Qt's Registry-backed default, so it travels with the
        # portable folder. Position/maximized state aren't handled (parity).
        self._window_state_file = resolve_base_root() / "window-state.ini"
        self._window_state = QSettings(
            str(self._window_state_file), QSettings.Format.IniFormat
        )
        width = _read_int(self._window_state, "width", DEFAULT_SIZE[0])
        height = _read_int(self._window_state, "height", DEFAULT_SIZE[1])
        self.setMinimumSize(*MIN_SIZE)
        # Clamp explicitly too, so a bad file can't request a sub-minimum size.
        self.resize(max(width, MIN_SIZE[0]), max(height, MIN_SIZE[1]))

        # Game-selection screen first (port of Electron's GameSelect/GameGate).
        # One game per run: no way back to it, and the pick isn't persisted
        # (TODO.md #30, Electron parity).
        game_select = GameSelectScreen()
        game_select.gameSelected.connect(self._on_game_selected)
        self.setCentralWidget(game_select)

    def _on_game_selected(self, slug: str) -> None:
        # Constructing the game's screen is the whole "activation" (Electron's
        # gameActivate IPC): RimWorldMainScreen resolves its own APP-ROOT and
        # starts its log. setCentralWidget hides the game-select screen and
        # deleteLater()s it, so this is safe to run from the tile's own
        # click/key handler. Only RimWorld's tile is enabled today.
        if slug == "rimworld":
            self.setCentralWidget(RimWorldMainScreen())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._save_timer.start()

    def _save_window_state(self) -> None:
        # Created on first save, not at startup (Electron's writeJson mkdirs too).
        self._window_state_file.parent.mkdir(parents=True, exist_ok=True)
        self._window_state.setValue("width", self.width())
        self._window_state.setValue("height", self.height())
        self._window_state.sync()
        if self._window_state.status() != QSettings.Status.NoError:
            print(
                f"[windowState] save failed: {self._window_state.fileName()}",
                file=sys.stderr,
            )
