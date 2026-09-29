"""Settings window for a Thunderstore/BepInEx game (THUNDERSTORE.md §8e):
the same modal shape as RimWorld's SettingsWindow (screens/settings_window.py,
whose page / path-value / button helpers are reused), with the tabs a
Thunderstore game actually needs today:

- General: the game folder (the only path setting - BepInEx config lives
  inside each load order's own tree, THUNDERSTORE.md TODO #6; no Steam
  acquisition mode, Thunderstore is the sole source) with Browse... and
  Autodetect; then ANIMATIONS (Windows / On / Off, RimWorld's shared
  animations_row - this game's settings.json).
- Troubleshooting: Open log file / Open previous log file, as RimWorld's,
  then Clean cache (THUNDERSTORE.md §8c): deletes every cached package zip
  no load order of this game references (bepinex_load_orders.
  clean_package_cache - aborts with nothing deleted if a load order can't
  be read), synchronously (a scan + a few unlinks), then says what it did
  in a message box (clean_result_text). No confirm: the cache is fully
  regenerable. Disabled - and refused on click - while the screen is busy
  (is_busy: an install / download / update / launch in flight), so it
  never races a download into the cache. (§8e's full tab list is still
  open.)

Opened from the paths bar's Settings button (BepInExMainScreen._show_settings);
Browse / Autodetect are the screen's own (on_browse(kind, parent) /
on_autodetect(parent)), this window then re-reads paths_state().
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QTabWidget, QVBoxLayout, QWidget

from volt_py import bepinex_load_orders as lo, paths
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
    _key,
    _muted,
    _page,
    _PathValue,
    animations_row,
    underline_tabs,
)
from volt_py.settings import SettingsStore
from volt_py.thunderstore_browse import format_size

CLEAN_CACHE_TOOLTIP = "Removes cached mods that aren't in any load order to free up storage space"
CLEAN_CACHE_BUSY_TOOLTIP = "Unavailable while VOLT is installing, updating or running the game"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def clean_result_text(res: dict) -> tuple[str, str, bool]:
    """clean_package_cache's result -> (title, message, is_warning) for the
    message box."""
    if res["unreadable"]:
        names = ", ".join(f'"{u["slug"]}"' for u in res["unreadable"])
        first = res["unreadable"][0]["error"]
        return (
            "Couldn't clean cache",
            f"Nothing was deleted: VOLT couldn't read the load order{'s' if len(res['unreadable']) > 1 else ''} "
            f"{names} ({first}). Clean cache only runs when every load order can be read, so it never removes a "
            f"mod one of them uses.",
            True,
        )
    kept = len(res["kept"])
    if res["removed"]:
        text = (f"Removed {_plural(len(res['removed']), 'cached mod')} that no load order uses, "
                f"freeing {format_size(res['freed'])}.")
        if kept:
            text += f" {_plural(kept, 'cached mod')} in use {'was' if kept == 1 else 'were'} kept."
    else:
        text = ("Nothing to clean: every cached mod is used by a load order." if kept
                else "Nothing to clean: the mod cache is empty.")
    if res["failed"]:
        names = ", ".join(name for name, _ in res["failed"])
        text += f" {_plural(len(res['failed']), 'file')} couldn't be removed (in use by another program?): {names}."
    return "Clean cache", text, bool(res["failed"])


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
        *,
        app_root: Path,
        is_busy: Callable[[], bool],
        settings: SettingsStore,
    ) -> None:
        """app_root: this game's APP-ROOT (Clean cache's package cache and
        load orders). is_busy(): the screen has a mutating job in flight.
        settings: the screen's SettingsStore (General > Animations)."""
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
        self._app_root = app_root
        self._is_busy = is_busy
        self._settings = settings
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
        underline_tabs(self.tabs)
        self.tabs.addTab(self._build_general(), "General")
        self.tabs.addTab(self._build_troubleshooting(), "Troubleshooting")
        layout.addWidget(self.tabs, 1)

        self.close_button.clicked.connect(lambda: self.reject())
        self.tabs.currentChanged.connect(lambda i: log(f"settings: {self.tabs.tabText(i)} tab"))
        # A job can finish while this modal window is open: re-read the busy state on every tab switch.
        self.tabs.currentChanged.connect(lambda i: self._apply_clean_state())

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
        name = _key("Game folder")  # a copper terminal key (step 3.4)
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
        layout.addLayout(animations_row(self._settings, page))
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
        self.clean_cache_button = _button("Clean cache")
        self._apply_clean_state()
        layout.addLayout(_button_row(self.clean_cache_button))
        layout.addStretch(1)
        self.log_button.clicked.connect(lambda: self._open_log(self._log_path))
        self.prev_log_button.clicked.connect(lambda: self._open_log(self._prev_log_path))
        self.clean_cache_button.clicked.connect(lambda: self._clean_cache())
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

    def _apply_clean_state(self) -> None:
        busy = self._is_busy()
        self.clean_cache_button.setEnabled(not busy)
        self.clean_cache_button.setToolTip(CLEAN_CACHE_BUSY_TOOLTIP if busy else CLEAN_CACHE_TOOLTIP)

    def _clean_cache(self) -> None:
        log(f"settings: Clean cache ({self._app_root})")
        if self._is_busy():  # safety net behind the disabled button: never race a download into the cache
            log("settings: Clean cache refused: the screen is busy")
            self._warn("Clean cache", "VOLT is busy installing, updating or running the game. Try again once it's done.", self)
            return
        try:
            res = lo.clean_package_cache(self._app_root)
        except Exception as err:  # a folder that can't be listed: nothing is half-swept silently
            log(f"settings: Clean cache FAILED: {err!r}")
            self._warn("Couldn't clean cache", str(err) or repr(err), self)
            return
        title, text, warning = clean_result_text(res)
        if warning:
            self._warn(title, text, self)
        else:
            log(f"info shown: {title}: {text}")
            QMessageBox.information(self, title, text)
