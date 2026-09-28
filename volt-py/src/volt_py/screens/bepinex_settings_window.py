"""Settings window for a Thunderstore/BepInEx game (THUNDERSTORE.md §8e):
the same modal shape as RimWorld's SettingsWindow (screens/settings_window.py,
whose page / path-value / button helpers are reused), with the tabs a
Thunderstore game actually needs today:

- General: the game folder (the only path setting - BepInEx config lives
  inside each load order's own tree, THUNDERSTORE.md TODO #6; no Steam
  acquisition mode, Thunderstore is the sole source) with Browse... and
  Autodetect.
- Troubleshooting: Open log file / Open previous log file, as RimWorld's.
  §8c's "Clean cache" belongs on this tab too and isn't built yet (§8e's
  full tab list is still open).

Opened from the paths bar's Settings button (BepInExMainScreen._show_settings);
Browse / Autodetect are the screen's own (on_browse(kind, parent) /
on_autodetect(parent)), this window then re-reads paths_state().
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from volt_py import paths
from volt_py.applog import log
from volt_py.screens.settings_window import (
    GAP,
    NO_LOG_TOOLTIP,
    NO_PREV_LOG_TOOLTIP,
    PATH_LABEL_WIDTH,
    SOURCE_LABEL,
    WINDOW_SIZE,
    _button,
    _button_row,
    _muted,
    _page,
    _PathValue,
)


class BepInExSettingsWindow(QDialog):
    def __init__(
        self,
        game_name: str,
        paths_state: Callable[[], dict],
        on_browse: Callable[[str, QWidget], None],
        on_autodetect: Callable[[QWidget], None],
        warn: Callable[..., None],
        log_path: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settings")
        self.setWindowTitle("Settings")
        self.setModal(True)
        self._game_name = game_name
        self._paths_state = paths_state
        self._on_browse = on_browse
        self._on_autodetect = on_autodetect
        self._warn = warn
        self._log_path = log_path
        prev = log_path.with_name(log_path.name + ".prev") if log_path else None
        self._prev_log_path = prev if prev and prev.exists() else None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("Settings")
        title.setProperty("role", "modal-title")
        header.addWidget(title)
        header.addStretch(1)
        self.close_button = _button("Close")
        header.addWidget(self.close_button)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.addTab(self._build_general(), "General")
        self.tabs.addTab(self._build_troubleshooting(), "Troubleshooting")
        layout.addWidget(self.tabs, 1)

        self.close_button.clicked.connect(lambda: self.reject())
        self.tabs.currentChanged.connect(lambda i: log(f"settings: {self.tabs.tabText(i)} tab"))

        width, height = WINDOW_SIZE
        if parent is not None:
            bounds = parent.window().size()
            width, height = min(width, bounds.width() - 32), min(height, bounds.height() - 32)
        self.resize(width, height)
        self._refresh()
        self.close_button.setFocus()

    def _build_general(self) -> QWidget:
        page, layout = _page()
        self.game_value = _PathValue()
        self.game_tag = QLabel()
        self.game_tag.setProperty("role", "tag")
        self.game_browse = _button("Browse...")
        row = QHBoxLayout()
        row.setSpacing(GAP)
        name = _muted("Game folder")
        name.setFixedWidth(PATH_LABEL_WIDTH)
        row.addWidget(name)
        row.addWidget(self.game_value, 1)
        row.addWidget(self.game_tag)
        row.addWidget(self.game_browse)
        layout.addLayout(row)
        note = _muted(
            f"Mods and their BepInEx config live inside each load order's own folder under VOLT's data folder, "
            f"never in the {self._game_name} install - so this is the only path to set."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.autodetect_button = _button("Autodetect paths")
        layout.addLayout(_button_row(self.autodetect_button))
        layout.addStretch(1)
        self.game_browse.clicked.connect(lambda: self._browse())
        self.autodetect_button.clicked.connect(lambda: self._autodetect())
        return page

    def _build_troubleshooting(self) -> QWidget:
        page, layout = _page()
        self.log_button = _button("Open log file")
        self.prev_log_button = _button("Open previous log file")
        self.log_button.setEnabled(self._log_path is not None)
        self.log_button.setToolTip(str(self._log_path) if self._log_path else NO_LOG_TOOLTIP)
        self.prev_log_button.setEnabled(self._prev_log_path is not None)
        self.prev_log_button.setToolTip(
            str(self._prev_log_path) if self._prev_log_path
            else NO_LOG_TOOLTIP if self._log_path is None
            else NO_PREV_LOG_TOOLTIP
        )
        layout.addLayout(_button_row(self.log_button, self.prev_log_button))
        layout.addStretch(1)
        self.log_button.clicked.connect(lambda: self._open_log(self._log_path))
        self.prev_log_button.clicked.connect(lambda: self._open_log(self._prev_log_path))
        return page

    def _refresh(self) -> None:
        state = self._paths_state()
        game_dir = state["game_dir"]
        self.game_value.set_value(game_dir)
        tag = SOURCE_LABEL.get(state["game_source"]) if game_dir else None
        self.game_tag.setText(tag or "")
        self.game_tag.setVisible(bool(tag))

    def _browse(self) -> None:
        log("settings: Browse... (game folder)")
        self._on_browse("game", self)
        self._refresh()

    def _autodetect(self) -> None:
        log("settings: Autodetect paths")
        self._on_autodetect(self)
        self._refresh()

    def _open_log(self, path: Path | None) -> None:
        if path is None:
            return
        try:
            paths.open_path(path)
        except OSError as err:
            log(f"settings: open log {path}: the OS refused: {err!r}")
            self._warn("Couldn't open log file", str(err), self)
            return
        log(f"settings: opened log {path}")
