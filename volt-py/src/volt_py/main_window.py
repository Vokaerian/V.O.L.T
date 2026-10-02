"""VOLT main window (PySide6 app shell)."""

import sys
from importlib.metadata import version

from PySide6.QtCore import QRectF, QSettings, QTimer
from PySide6.QtGui import QPainter, QResizeEvent
from PySide6.QtWidgets import QMainWindow

from volt_py import bepinex_games, theme
from volt_py.app_root import resolve_base_root
from volt_py.painters import crossfade, paint_dots
from volt_py.screens.bepinex_help_entries import help_entries
from volt_py.screens.bepinex_main_screen import BepInExMainScreen
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
        # The pick isn't persisted (TODO.md #30); each manager's "Games" button
        # / Alt+Left comes back here (_on_back_requested, 0.6.8).
        self.setCentralWidget(self._game_select())

    def _game_select(self) -> GameSelectScreen:
        # A fresh screen every time (first launch and every way back), so no
        # tile keeps a hover/focus state from before (no origin-tile focus, by
        # decision).
        game_select = GameSelectScreen()
        game_select.gameSelected.connect(self._on_game_selected)
        return game_select

    def _on_game_selected(self, slug: str) -> None:
        # Constructing the game's screen is the whole "activation" (Electron's
        # gameActivate IPC): RimWorldMainScreen resolves its own APP-ROOT and
        # starts its log. setCentralWidget hides the game-select screen and
        # deleteLater()s it, so this is safe to run from the tile's own
        # click/key handler. RimWorld has its own screen; every Thunderstore
        # game in bepinex_games.GAMES gets the shared BepInEx manager bound to
        # its module and Help entries (only those tiles are enabled).
        # The screen is built first (its synchronous scan, and its Settings >
        # Animations mode applied), then swapped in under a MOTION_SCREEN
        # crossfade of the game-select snapshot (painters.crossfade: phase 4
        # M1; the new screen and its mod lists are live at once, no effect).
        # A fresh screen on every pick, re-entering the same game included: its
        # own log (re)start, migration and scan run again (nothing is cached
        # on the old, deleted screen).
        if slug == "rimworld":
            screen = RimWorldMainScreen()
        elif slug in bepinex_games.BY_SLUG:
            game = bepinex_games.BY_SLUG[slug]
            screen = BepInExMainScreen(game, help_entries(game))
        else:
            return
        screen.back_requested.connect(self._on_back_requested)
        self._swap_to(screen)

    def _on_back_requested(self) -> None:
        # A manager's "Games" button / Alt+Left, already past its own guard
        # (unsaved-changes confirm, not busy) and teardown (_request_back):
        # the reverse of _on_game_selected - a new game-select screen under
        # the same MOTION_SCREEN crossfade. Emitted from the manager's own
        # click/shortcut handler; setCentralWidget only deleteLater()s it.
        self._swap_to(self._game_select())

    def _swap_to(self, screen) -> None:
        old = self.centralWidget()
        area = old.geometry() if old is not None else None
        crossfade(self, lambda: self.setCentralWidget(screen), theme.MOTION_SCREEN, area)

    def paintEvent(self, event) -> None:
        # The Circuit dot grid over the window's --bg (the QSS fills the --bg
        # first): one cached device-pixel tile, tiled over the dirty rect
        # (painters.paint_dots). The screens are transparent, their panels
        # opaque - so it shows around and between them.
        super().paintEvent(event)
        painter = QPainter(self)
        paint_dots(painter, QRectF(event.rect()))
        painter.end()

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
