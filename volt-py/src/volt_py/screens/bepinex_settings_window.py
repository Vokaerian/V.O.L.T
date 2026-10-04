"""Settings window for a Thunderstore/BepInEx game (THUNDERSTORE.md §8e):
the same modal shape as RimWorld's SettingsWindow (screens/settings_window.py,
whose page / path-value / button helpers are reused), with the tabs a
Thunderstore game actually needs today:

- General: the game folder (the only path setting - BepInEx config lives
  inside each load order's own tree, THUNDERSTORE.md TODO #6; no Steam
  acquisition mode, Thunderstore is the sole source) with Browse... and
  Autodetect; then ANIMATIONS (Windows / On / Off, RimWorld's shared
  animations_row - this game's settings.json); then DATA FOLDER, a key row
  like GAME FOLDER's (this game's APP-ROOT, Open data folder shows it in
  Explorer) with a muted line saying what's in it. 0.6.2: SECTION_GAP extra
  space between the three groups, so the button no longer reads as part of
  ANIMATIONS. 0.6.30: UPDATES last (settings_window.UpdatesBlock, key row).
- Launch (2026-09-30): "Launch arguments", one line of extra command-line
  arguments for the game (settings.json launch_args, saved as typed on
  editingFinished and again when the window closes, only once
  bepinex_launch.parse_launch_args accepts it - an unclosed quote warns and
  isn't saved). BepInExMainScreen._run appends them to both Modded and
  Vanilla launches. 0.6.2: the key keeps its full width (min, not fixed:
  LAUNCH ARGUMENTS in the copper caps is wider than the key column, which
  only matters for alignment on General), a placeholder, and muted examples
  under the note - the game module's LAUNCH_ARG_EXAMPLES, else
  UNITY_LAUNCH_ARG_EXAMPLES.
- Troubleshooting: Open log file / Open previous log file, as RimWorld's,
  then Clean cache (labelled "Clean up downloads" since 0.6.24; THUNDERSTORE.md §8c): deletes every cached package zip
  no load order of this game references (bepinex_load_orders.
  clean_package_cache - aborts with nothing deleted if a load order can't
  be read), synchronously (a scan + a few unlinks), then says what it did
  in a message box (clean_result_text). No confirm: the cache is fully
  regenerable. Disabled - and refused on click - while the screen is busy
  (is_busy: an install / download / update / launch in flight), so it
  never races a download into the cache. (§8e's full tab list is still
  open.) Then (2026-09-30): Copy log to clipboard (the current log's
  last LOG_COPY_BYTES, plain text); Copy troubleshooting info
  (applog.troubleshooting_text: VOLT / OS / Python / PySide6 versions, the
  screen's troubleshooting_info() fields, launch args, animations, the log's
  last 50 lines); Reset installation - empties the game folder and opens
  steam://validate/<appid> so Steam re-downloads it (the user reversed
  THUNDERSTORE.md §7's non-adoption 2026-09-30). Guards live Qt-free in
  bepinex_launch (reset_refusal, wipe_game_folder); here: disabled while
  busy, refused while the game exe runs, the screen's Enter-confirms
  _confirm naming the folder, then a result box.
  0.6.2 layout: four groups (settings_window._group, shared with RimWorld's
  window since 0.6.8), each a copper side-rule terminal heading
  (painters.TerminalLabel rule="heading", the Rules / Warnings dialog
  headings) over a muted one-line description and its buttons, SECTION_GAP
  apart: LOGS (Open log file, Open previous log file, Copy log to
  clipboard), SUPPORT INFO (Copy troubleshooting info), MOD CACHE (Clean
  cache), and RESET INSTALLATION pushed to the bottom of the page by the
  stretch (destructive; no danger button variant exists, so separation
  only).

Opened from the paths bar's Settings button (BepInExMainScreen._show_settings);
Browse / Autodetect are the screen's own (on_browse(kind, parent) /
on_autodetect(parent)), this window then re-reads paths_state().
"""

import platform
import webbrowser
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

import PySide6
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from volt_py import bepinex_launch as bl, bepinex_load_orders as lo, paths
from volt_py.applog import log, read_tail, troubleshooting_text
from volt_py.screens.settings_window import (
    GAP,
    LOGS_NOTE,
    NO_LOG_TOOLTIP,
    NO_PREV_LOG_TOOLTIP,
    PATH_LABEL_WIDTH,
    SECTION_GAP,
    SOURCE_LABEL,
    WINDOW_SIZE,
    UpdatesBlock,
    _button,
    _button_row,
    _group,
    _key,
    _muted,
    _page,
    _PathValue,
    animations_row,
    underline_tabs,
)
from volt_py.settings import SettingsStore
from volt_py.thunderstore_browse import format_size

CLEAN_CACHE_TOOLTIP = ("Deletes VOLT's downloaded copies of mods that no profile uses, to free up space "
                       "(they download again if you need them later)")
CLEAN_CACHE_BUSY_TOOLTIP = "Unavailable while VOLT is installing, updating or running the game"
LOG_COPY_BYTES = 200 * 1024  # Copy log to clipboard: the log's tail, so a long session doesn't flood the clipboard
COPY_LOG_TOOLTIP = "Copies the log file as plain text (the last 200 KB when it's longer)"
COPY_INFO_TOOLTIP = "Copies versions, paths, the profile and the log's last 50 lines as plain text, for a bug report"
LAUNCH_ARGS_NOTE = "Extra start options for the game (command-line arguments), used by both Modded and Vanilla."
# Launch's examples when the game module has no LAUNCH_ARG_EXAMPLES: Unity
# player options (docs.unity3d.com "Unity Standalone Player command line
# arguments"), true for any Unity game.
UNITY_LAUNCH_ARG_EXAMPLES = (
    ("-screen-fullscreen 0", "starts in a window"),
    ("-window-mode borderless", "borderless fullscreen"),
    ("-screen-width 1920 -screen-height 1080", "sets the resolution"),
)
DATA_FOLDER_NOTE = "VOLT's own files for this game: profiles, downloaded mods and settings."
SUPPORT_NOTE = "Versions, paths and the profile (plus the log's last lines), ready to paste into a bug report."


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def clean_result_text(res: dict) -> tuple[str, str, bool]:
    """clean_package_cache's result -> (title, message, is_warning) for the
    message box."""
    if res["unreadable"]:
        names = ", ".join(f'"{u["slug"]}"' for u in res["unreadable"])
        first = res["unreadable"][0]["error"]
        return (
            "Couldn't clean up downloads",
            f"Nothing was deleted: VOLT couldn't read the profile{'s' if len(res['unreadable']) > 1 else ''} "
            f"{names} ({first}). Clean up downloads only runs when every profile can be read, so it never removes a "
            f"mod one of them uses.",
            True,
        )
    kept = len(res["kept"])
    if res["removed"]:
        text = (f"Removed {_plural(len(res['removed']), 'downloaded mod')} that no profile uses, "
                f"freeing {format_size(res['freed'])}.")
        if kept:
            text += f" {_plural(kept, 'downloaded mod')} in use {'was' if kept == 1 else 'were'} kept."
    else:
        text = ("Nothing to clean up: every downloaded mod is used by a profile." if kept
                else "Nothing to clean up: VOLT has no downloaded mods.")
    if res["failed"]:
        names = ", ".join(name for name, _ in res["failed"])
        text += f" {_plural(len(res['failed']), 'file')} couldn't be removed (in use by another program?): {names}."
    return "Clean up downloads", text, bool(res["failed"])


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
        game,
        confirm: Callable[..., bool],
        troubleshooting_info: Callable[[], list[tuple[str, object]]],
    ) -> None:
        """app_root: this game's APP-ROOT (Clean cache's package cache and
        load orders, Open data folder). is_busy(): the screen has a mutating
        job in flight. settings: the screen's SettingsStore (General >
        Animations, Launch). game: the game module (valheim.py's shape:
        STEAM_APPID, is_game_root, find_game_exe) for Reset installation.
        confirm(title, message, confirm_label=, parent=): the screen's
        Enter-confirms box. troubleshooting_info(): the screen's (key, value)
        lines for Copy troubleshooting info (game, folder, load order, mods)."""
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
        self._game = game
        self._confirm = confirm
        self._troubleshooting_info = troubleshooting_info
        self._bad_launch_args: str | None = None  # the last text refused (warned once, not again on close)
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
        self.tabs.addTab(self._build_launch(), "Launch")
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
            f"Your mods and their settings live in each profile's own folder in VOLT's data folder, never in the "
            f"{self._game_name} install - so this is the only folder to set."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.autodetect_button = _button("Autodetect paths")
        layout.addLayout(_button_row(self.autodetect_button))
        layout.addSpacing(SECTION_GAP)
        layout.addLayout(animations_row(self._settings, page))
        layout.addSpacing(SECTION_GAP)
        # DATA FOLDER: a key row like GAME FOLDER's - the key names the button's folder, the path shows it
        self.data_folder_value = _PathValue()
        self.data_folder_value.set_value(self._app_root)
        self.data_folder_button = _button("Open data folder")
        self.data_folder_button.setToolTip(str(self._app_root))
        row = QHBoxLayout()
        row.setSpacing(GAP)
        name = _key("Data folder")
        name.setFixedWidth(PATH_LABEL_WIDTH)
        row.addWidget(name)
        row.addWidget(self.data_folder_value, 1)
        row.addWidget(self.data_folder_button)
        layout.addLayout(row)
        note = _muted(DATA_FOLDER_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(SECTION_GAP)
        self.updates = UpdatesBlock(key=True)
        layout.addWidget(self.updates)
        layout.addStretch(1)
        self.game_browse.clicked.connect(lambda: self._browse())
        self.autodetect_button.clicked.connect(lambda: self._autodetect())
        self.data_folder_button.clicked.connect(lambda: self._open_data_folder())
        return page

    def _build_launch(self) -> QWidget:
        page, layout = _page()
        row = QHBoxLayout()
        row.setSpacing(GAP)
        name = _key("Launch arguments")
        name.setMinimumWidth(PATH_LABEL_WIDTH)  # min, not fixed: the plural caps outgrow the key column (clipped in 0.6.1)
        row.addWidget(name)
        examples = getattr(self._game, "LAUNCH_ARG_EXAMPLES", None) or UNITY_LAUNCH_ARG_EXAMPLES
        self.launch_args_edit = QLineEdit(self._settings.get().get("launch_args") or "")
        self.launch_args_edit.setPlaceholderText(f"e.g. {examples[0][0]}")
        row.addWidget(self.launch_args_edit, 1)
        layout.addLayout(row)
        note = _muted(f"{LAUNCH_ARGS_NOTE} Separate several with spaces; quote a value that has spaces.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(SECTION_GAP)
        layout.addWidget(_muted("Examples:"))
        # the arguments in mono (selectable, to copy), what each does beside them in the muted sans
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        for i, (arg, what) in enumerate(examples):
            code = QLabel(arg)
            code.setProperty("role", "scan-mono")  # muted mono 12px (theme.py)
            code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(code, i, 0)
            grid.addWidget(_muted(what), i, 1)
        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        self.launch_args_edit.editingFinished.connect(lambda: self._save_launch_args())
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
        self.copy_log_button = _button("Copy log to clipboard")
        self.copy_log_button.setEnabled(self._log_path is not None)
        self.copy_log_button.setToolTip(COPY_LOG_TOOLTIP if self._log_path else NO_LOG_TOOLTIP)
        _group(layout, "Logs", LOGS_NOTE, self.log_button, self.prev_log_button, self.copy_log_button)
        layout.addSpacing(SECTION_GAP)
        self.copy_info_button = _button("Copy troubleshooting info")
        self.copy_info_button.setToolTip(COPY_INFO_TOOLTIP)
        _group(layout, "Support info", SUPPORT_NOTE, self.copy_info_button)
        layout.addSpacing(SECTION_GAP)
        self.clean_cache_button = _button("Clean up downloads")
        self._apply_clean_state()
        _group(layout, "Downloaded mods", f"{CLEAN_CACHE_TOOLTIP}.", self.clean_cache_button)
        layout.addStretch(1)  # the destructive group sits apart, at the bottom of the page
        self.reset_button = _button("Reset installation")
        self._apply_clean_state()
        _group(
            layout, "Reset installation",
            f"Fixes a game damaged by broken or leftover mod files. Deletes everything in the {self._game_name} "
            "folder, then asks Steam to check and download the game files again. Your profiles and mods in VOLT's "
            "data folder are kept.",
            self.reset_button,
        )
        self.log_button.clicked.connect(lambda: self._open_log(self._log_path))
        self.prev_log_button.clicked.connect(lambda: self._open_log(self._prev_log_path))
        self.clean_cache_button.clicked.connect(lambda: self._clean_cache())
        self.copy_log_button.clicked.connect(lambda: self._copy_log())
        self.copy_info_button.clicked.connect(lambda: self._copy_info())
        self.reset_button.clicked.connect(lambda: self._reset_installation())
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
            self._warn("Couldn't open log file", "Windows couldn't open the log file.",
                       means="No program is set up to open .log files, or the file was moved.",
                       tryit="Use Copy log instead, or open the file from VOLT's data folder with Notepad.",
                       details=f"{path}\n{err}", parent=self)
            return
        log(f"settings: opened log {path}")

    def _apply_clean_state(self) -> None:
        busy = self._is_busy()
        self.clean_cache_button.setEnabled(not busy)
        self.clean_cache_button.setToolTip(CLEAN_CACHE_BUSY_TOOLTIP if busy else CLEAN_CACHE_TOOLTIP)
        if hasattr(self, "reset_button"):  # built after the first call (Clean cache's row)
            self.reset_button.setEnabled(not busy)
            self.reset_button.setToolTip(
                CLEAN_CACHE_BUSY_TOOLTIP if busy
                else f"Deletes everything in the {self._game_name} folder, then asks Steam to verify the game files"
            )

    def _clean_cache(self) -> None:
        log(f"settings: Clean cache ({self._app_root})")
        if self._is_busy():  # safety net behind the disabled button: never race a download into the cache
            log("settings: Clean cache refused: the screen is busy")
            self._warn("Clean up downloads", "VOLT is busy right now.",
                       means="It's installing, updating or running the game.",
                       tryit="Wait until that's done, then try again.", parent=self)
            return
        try:
            res = lo.clean_package_cache(self._app_root)
        except Exception as err:  # a folder that can't be listed: nothing is half-swept silently
            log(f"settings: Clean cache FAILED: {err!r}")
            self._warn("Couldn't clean up downloads", "VOLT couldn't clean up its downloaded mod files.",
                       means="Nothing was deleted.",
                       tryit="Close the game and try again.",
                       details=str(err) or repr(err), parent=self)
            return
        title, text, warning = clean_result_text(res)
        if warning:
            self._warn(title, text, tryit="Close the game and anything else using VOLT's files, then try again.",
                       details=f"VOLT's data folder: {self._app_root}", parent=self)
        else:
            log(f"info shown: {title}: {text}")
            QMessageBox.information(self, title, text)

    def _open_data_folder(self) -> None:
        try:
            paths.open_path(self._app_root)
        except OSError as err:
            log(f"settings: open data folder {self._app_root}: the OS refused: {err!r}")
            self._warn("Couldn't open data folder", "Windows couldn't open VOLT's data folder.",
                       means="It may have been moved or deleted.",
                       tryit="Restart VOLT, then try again.",
                       details=f"{self._app_root}\n{err}", parent=self)
            return
        log(f"settings: opened data folder {self._app_root}")

    # ---- Launch ----
    def _save_launch_args(self) -> None:
        text = self.launch_args_edit.text()
        if text == (self._settings.get().get("launch_args") or "") or text == self._bad_launch_args:
            return
        try:
            args = bl.parse_launch_args(text)
        except ValueError as err:
            self._bad_launch_args = text
            log(f"settings: launch arguments {text!r} refused: {err}")
            self._warn("Launch options not saved", "VOLT couldn't read these launch options.",
                       means="They weren't saved; the game keeps starting with the ones you had before.",
                       tryit="Check for a missing closing quote (\"), or clear the box.",
                       details=f"Text: {text!r}\n{err}", parent=self)
            return
        try:
            self._settings.set_launch_args(text)
        except (OSError, ValueError) as err:
            log(f"settings: launch arguments FAILED to save: {err!r}")
            self._warn("Couldn't save settings", "VOLT couldn't save your settings.",
                       means="The change you made won't be remembered next time VOLT starts.",
                       tryit="Make sure VOLT's folder isn't read-only or full, then try again.",
                       details=str(err), parent=self)
            return
        self._bad_launch_args = None
        log(f"settings: launch arguments set to {text!r} -> {args}")

    def done(self, result: int) -> None:
        self._save_launch_args()  # Esc / Close with the field still focused: editingFinished may not have fired
        super().done(result)

    # ---- Troubleshooting: copy ----
    def _copy_log(self) -> None:
        if self._log_path is None:
            return
        try:
            text = read_tail(self._log_path, LOG_COPY_BYTES)
        except OSError as err:
            log(f"settings: copy log {self._log_path} FAILED: {err!r}")
            self._warn("Couldn't copy log", "VOLT couldn't read its log file.",
                       means="Nothing was copied.",
                       tryit="Use Open log file instead, or Help > Report a problem.",
                       details=f"{self._log_path}\n{err}", parent=self)
            return
        QGuiApplication.clipboard().setText(text)
        size = self._log_path.stat().st_size if self._log_path.exists() else 0
        what = "the last 200 KB of the log" if size > LOG_COPY_BYTES else "the log"
        message = f"Copied {what} ({self._log_path.name}) to the clipboard."
        log(f"settings: copied log {self._log_path} ({len(text)} chars); info shown: Copy log: {message}")
        QMessageBox.information(self, "Copy log", message)

    def _copy_info(self) -> None:
        text = troubleshooting_text(self._troubleshooting_fields(), self._log_path)
        QGuiApplication.clipboard().setText(text)
        log(f"settings: copied troubleshooting info ({len(text)} chars)")
        QMessageBox.information(self, "Copy troubleshooting info", "Copied the troubleshooting info to the clipboard.")

    def _troubleshooting_fields(self) -> list[tuple[str, object]]:
        try:
            volt = version("volt-py")
        except Exception:
            volt = "unknown"
        s = self._settings.get()
        return [
            ("VOLT", volt), ("OS", platform.platform()), ("Python", platform.python_version()),
            ("PySide6", PySide6.__version__),
            *self._troubleshooting_info(),
            ("Launch arguments", s.get("launch_args")), ("Animations", s.get("animations")),
        ]

    # ---- Troubleshooting: Reset installation ----
    def _reset_installation(self) -> None:
        state = self._paths_state()
        game_dir, source = state["game_dir"], state["game_source"]
        log(f"settings: Reset installation ({game_dir}, source {source})")
        if self._is_busy():
            log("settings: Reset installation refused: the screen is busy")
            self._warn("Reset installation", "VOLT is busy right now.",
                       means="It's installing, updating or running the game.",
                       tryit="Wait until that's done, then try again.", parent=self)
            return
        reason = bl.reset_refusal(game_dir, source, self._game.is_game_root, self._app_root)
        if reason:
            log(f"settings: Reset installation refused: {reason}")
            self._warn("Reset installation", "Nothing was deleted.", means=reason,
                       tryit="Check the game folder in Settings > General first.", details=f"Game folder: {game_dir}",
                       parent=self)
            return
        exe = self._game.find_game_exe(game_dir)
        pids = bl.running_pids(exe.name) if exe else set()
        if pids:
            log(f"settings: Reset installation refused: {exe.name} is running (pids {sorted(pids)})")
            self._warn("Reset installation", f"{self._game_name} is running.", means="Nothing was deleted.",
                       tryit=f"Quit {self._game_name}, then try again.", details=f"Running: {exe.name} (pids {sorted(pids)})",
                       parent=self)
            return
        if not self._confirm(
            "Reset installation",
            f"Delete EVERYTHING inside {game_dir}? This removes the whole {self._game_name} install (and anything "
            f"else you put in that folder) and can't be undone. Steam then re-downloads the game when it verifies "
            f"the files. Your profiles and mods in VOLT's data folder are kept.",
            confirm_label="Delete and verify",
            parent=self,
        ):
            log("settings: Reset installation cancelled")
            return
        try:
            res = bl.wipe_game_folder(self._app_root, game_dir)
        except (bl.LaunchError, OSError) as err:
            log(f"settings: Reset installation FAILED: {err!r}")
            self._warn("Reset installation failed", "Couldn't empty the game folder.",
                       means="Some or all of the game's files are still there.",
                       tryit=f"Quit {self._game_name} and Steam, then try again.",
                       details=f"Game folder: {game_dir}\n{err}", parent=self)
            return
        url = bl.validate_url(self._game.STEAM_APPID)
        try:
            paths.open_path(url)
            opened = True
        except OSError as err:
            log(f"settings: open {url}: the OS refused: {err!r}; trying the web browser")
            opened = webbrowser.open(url)
        log(f"settings: Reset installation: asked Steam to verify ({url}): {'ok' if opened else 'FAILED'}")
        text = f"Deleted {res['removed']} item{'' if res['removed'] == 1 else 's'} from {game_dir}; "
        text += ("asked Steam to verify files - watch Steam's download progress." if opened
                 else f"couldn't open Steam - verify the files yourself (Steam > {self._game_name} > Properties > "
                      "Installed Files > Verify integrity of game files).")
        if res["failed"]:
            names = ", ".join(p for p, _ in res["failed"][:10])
            more = len(res["failed"]) - 10
            text += (f" {len(res['failed'])} couldn't be deleted (in use by another program?): {names}"
                     + (f" and {more} more" if more > 0 else "") + ".")
        if res["failed"] or not opened:
            self._warn("Reset installation", text,
                       tryit=f"Close anything using the game folder, then use Steam's Verify integrity of game files "
                             f"(Steam > {self._game_name} > Properties > Installed Files).",
                       details=f"Game folder: {game_dir}", parent=self)
        else:
            log(f"info shown: Reset installation: {text}")
            QMessageBox.information(self, "Reset installation", text)
