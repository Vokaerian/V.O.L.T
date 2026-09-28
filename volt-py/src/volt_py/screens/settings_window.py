"""Settings window (port of SettingsWindow.jsx): a modal dialog, a header
(title + Close) over three tabs.

- General: the game / local mods / config folder paths (the game folder's
  storefront tag; Browse... for the game and config folders - local mods is
  always <game folder>/Mods, so it has none), then Autodetect paths.
- Steam: "Download mods via:" - the three exclusive mod-acquisition modes
  (settings steam_acquire_via; unset = auto: 'gog' for a GOG install, else
  'steamcmd' - settings.effective_acquire_via), then Check for missing
  Workshop mods.
- Troubleshooting: Open log file (<app_root>/volt.log, applog.py) and Open
  previous log file (volt.log.prev, disabled when there isn't one).

Opened from the paths bar's Settings button (RimWorldMainScreen._show_settings).
Browse / Autodetect are the screen's own (on_browse / on_autodetect: they
store the new paths and rescan, shared with the no-game message's buttons as
App.jsx shares onBrowse / onAutodetect); this window then re-reads the paths
(paths_state) and shows the new values. The acquisition mode is saved here
directly (SettingsStore.set_steam_acquire_via), as the Rules window saves its
own edits.

Tabs: a plain QTabWidget styled by theme.py (QDialog#settings), in place of
the Electron window's row of tab buttons over a panel.

Check for missing Workshop mods calls the screen's handler (on_check_missing:
RimWorldMainScreen._check_missing_workshop): every not-found Workshop row of
the Active list (mod_list_io.missing_workshop_rows) is fetched by the mode
chosen above, through the same path as a row's Subscribe. Always enabled, as
in Electron (whose only disable is its own "Checking..." re-entrancy flag,
not ported: the screen's `downloading` set already covers a second click).

Logging is dev-only in the Python port (applog.py): in a packaged build there
is no log file, so both log buttons are disabled.
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from volt_py import paths
from volt_py.applog import log
from volt_py.screens.flow_layout import FlowLayout
from volt_py.settings import ACQUIRE_VIA, SettingsStore, effective_acquire_via

SOURCE_LABEL = {"steam": "Steam", "gog": "GOG", "manual": "Manual"}
# SettingsWindow.jsx ACQUIRE_OPTIONS: (mode, label, tooltip), verbatim.
ACQUIRE_OPTIONS = (
    (
        "steamcmd",
        "SteamCMD, then sync to Steam (recommended)",
        "Downloads with SteamCMD into the Mods folder, so a mod works right away; Sync to Steam later subscribes "
        "it on Steam and removes the copy.",
    ),
    (
        "steamworks",
        "Steam client directly",
        "Subscribes through the Steam client; Steam downloads the mod into its own Workshop folder. Nothing goes "
        "into the Mods folder.",
    ),
    (
        "gog",
        "SteamCMD, keep in Mods (GOG)",
        "Downloads with SteamCMD into the Mods folder and keeps it there for good: never synced to Steam. Chosen "
        "automatically for a GOG install.",
    ),
)
assert tuple(mode for mode, _, _ in ACQUIRE_OPTIONS) == ACQUIRE_VIA

CHECK_MISSING_TOOLTIP = (
    "Download every mod in the active list that isn't found on disk but has a Workshop id, via the method chosen above"
)
NO_LOG_TOOLTIP = "No log file: logging is only on in development builds."
NO_PREV_LOG_TOOLTIP = "No previous log yet (created on the next launch)"

# .modal.settings-window: 900 x 600, at most the viewport minus 32px.
WINDOW_SIZE = (900, 600)
PATH_LABEL_WIDTH = 100  # .path-label: width 100px
GAP = 8  # .path-row / .button-row / .settings-panel gap


def _repolish(widget: QWidget) -> None:
    # A property selector isn't re-evaluated on its own after the first polish.
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _button(text: str) -> QPushButton:
    button = QPushButton(text)
    # No Enter-activates-default in this dialog: with autoDefault on, the first
    # button would become the default and Enter would click it.
    button.setAutoDefault(False)
    return button


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("muted", True)
    return label


def _button_row(*buttons: QPushButton) -> QHBoxLayout:
    """.button-row: left-aligned, 8px apart."""
    row = QHBoxLayout()
    row.setSpacing(GAP)
    for button in buttons:
        row.addWidget(button)
    row.addStretch(1)
    return row


def _page() -> tuple[QWidget, QVBoxLayout]:
    """One tab's page (.settings-panel: padding 12px, gap 8px; its --panel-2
    frame is the tab widget's pane, theme.py)."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(GAP)
    return page, layout


class _PathValue(QLabel):
    """.path-value: one line, mono, elided with … when it doesn't fit (the full
    path in the tooltip); "Not found" in --danger when unset (.unset)."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "path-value")
        self.setTextFormat(Qt.TextFormat.PlainText)
        # Width from the row (flex: 1; min-width: 0), never from the text.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._full = ""

    def set_value(self, value: Path | None) -> None:
        self._full = str(value) if value else "Not found"
        self.setToolTip(str(value) if value else "")
        unset = not value
        if self.property("unset") != unset:
            self.setProperty("unset", unset)
            _repolish(self)
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width()
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, width)))


class SettingsWindow(QDialog):
    def __init__(
        self,
        settings: SettingsStore,
        paths_state: Callable[[], dict],
        on_browse: Callable[[str, QWidget], None],
        on_autodetect: Callable[[QWidget], None],
        warn: Callable[..., None],
        log_path: Path | None,
        parent: QWidget | None = None,
        *,
        on_check_missing: Callable[[QWidget], None] | None = None,
    ) -> None:
        """paths_state(): the screen's current {"game_dir", "game_source",
        "config_dir"} (None when unset / not found). on_browse(kind, parent)
        ('game' | 'config'), on_autodetect(parent) and on_check_missing(parent)
        (Check for missing Workshop mods): the screen's own actions,
        reporting any failure themselves over `parent` (this window).
        warn(title, message, parent): the screen's _warn. log_path: this
        run's volt.log, None when there's no log (packaged build)."""
        super().__init__(parent)
        self.setObjectName("settings")
        self.setWindowTitle("Settings")
        self.setModal(True)
        self._settings = settings
        self._paths_state = paths_state
        self._on_browse = on_browse
        self._on_autodetect = on_autodetect
        self._on_check_missing = on_check_missing
        self._warn = warn
        self._log_path = log_path
        # The previous run's log (applog.init_log's rotation), checked now:
        # it only ever appears at the next launch.
        prev = log_path.with_name(log_path.name + ".prev") if log_path else None
        self._prev_log_path = prev if prev and prev.exists() else None

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()  # .validation-head: title left, Close right
        title = QLabel("Settings")
        title.setProperty("role", "modal-title")
        header.addWidget(title)
        header.addStretch(1)
        self.close_button = _button("Close")
        header.addWidget(self.close_button)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.tabBar().setDrawBase(False)  # no base line under the tabs: they sit apart from the panel
        self.tabs.tabBar().setExpanding(False)
        self.tabs.addTab(self._build_general(), "General")
        self.tabs.addTab(self._build_steam(), "Steam")
        self.tabs.addTab(self._build_troubleshooting(), "Troubleshooting")
        layout.addWidget(self.tabs, 1)

        self.close_button.clicked.connect(lambda: self.reject())  # Esc rejects too (QDialog default)
        self.tabs.currentChanged.connect(lambda i: log(f"settings: {self.tabs.tabText(i)} tab"))

        width, height = WINDOW_SIZE
        if parent is not None:
            bounds = parent.window().size()
            width, height = min(width, bounds.width() - 32), min(height, bounds.height() - 32)
        self.resize(width, height)
        self._refresh()
        self.close_button.setFocus()

    # ---- tabs ----
    def _build_general(self) -> QWidget:
        page, layout = _page()
        self.game_value = _PathValue()
        self.game_tag = QLabel()
        self.game_tag.setProperty("role", "tag")
        self.game_browse = _button("Browse...")
        self.mods_value = _PathValue()
        self.config_value = _PathValue()
        self.config_browse = _button("Browse...")
        for label, value, extras in (
            ("Game folder", self.game_value, (self.game_tag, self.game_browse)),
            ("Local mods", self.mods_value, ()),
            ("Config folder", self.config_value, (self.config_browse,)),
        ):
            row = QHBoxLayout()  # .path-row
            row.setSpacing(GAP)
            name = _muted(label)  # .path-label
            name.setFixedWidth(PATH_LABEL_WIDTH)
            row.addWidget(name)
            row.addWidget(value, 1)
            for widget in extras:
                row.addWidget(widget)
            layout.addLayout(row)
        self.autodetect_button = _button("Autodetect paths")
        layout.addLayout(_button_row(self.autodetect_button))
        layout.addStretch(1)

        self.game_browse.clicked.connect(lambda: self._browse("game"))
        self.config_browse.clicked.connect(lambda: self._browse("config"))
        self.autodetect_button.clicked.connect(lambda: self._autodetect())
        return page

    def _build_steam(self) -> QWidget:
        page, layout = _page()
        # The radio row wraps (flex-wrap in the .jsx): three options plus the
        # GOG note can outgrow the window's width.
        flow = FlowLayout(horizontal_spacing=GAP, vertical_spacing=GAP, center_rows=False)
        flow.addWidget(_muted("Download mods via:"))
        # Siblings under one parent: Qt keeps them mutually exclusive (autoExclusive).
        self.acquire_radios: dict[str, QRadioButton] = {}
        for mode, label, hint in ACQUIRE_OPTIONS:
            radio = QRadioButton(label)
            radio.setToolTip(hint)
            radio.toggled.connect(lambda checked, mode=mode: checked and self._set_acquire_via(mode))
            self.acquire_radios[mode] = radio
            flow.addWidget(radio)
        self.acquire_auto_note = _muted("(chosen automatically: GOG install)")
        flow.addWidget(self.acquire_auto_note)
        layout.addLayout(flow)

        self.check_missing_button = _button("Check for missing Workshop mods")
        self.check_missing_button.setToolTip(CHECK_MISSING_TOOLTIP)
        self.check_missing_button.clicked.connect(lambda: self._check_missing())
        layout.addLayout(_button_row(self.check_missing_button))
        layout.addStretch(1)
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

    # ---- state ----
    def _refresh(self) -> None:
        """Shows the screen's current paths and the acquisition mode in effect."""
        state = self._paths_state()
        game_dir = state["game_dir"]
        self.game_value.set_value(game_dir)
        tag = SOURCE_LABEL.get(state["game_source"]) if game_dir else None
        self.game_tag.setText(tag or "")
        self.game_tag.setVisible(bool(tag))
        self.mods_value.set_value(game_dir / "Mods" if game_dir else None)
        self.config_value.set_value(state["config_dir"])

        stored = self._settings.get()["steam_acquire_via"]
        via = effective_acquire_via(stored, state["game_source"])
        for mode, radio in self.acquire_radios.items():
            # Signals blocked: showing the mode in effect isn't a choice (the
            # GOG auto-pick must stay unstored until the user clicks).
            radio.blockSignals(True)
            radio.setChecked(mode == via)
            radio.blockSignals(False)
        # App.jsx acquireAuto (nothing valid stored) && acquireVia === 'gog'.
        self.acquire_auto_note.setVisible(stored not in ACQUIRE_VIA and via == "gog")

    # ---- actions ----
    def _browse(self, kind: str) -> None:
        log(f"settings: Browse... ({kind} folder)")
        self._on_browse(kind, self)
        self._refresh()

    def _autodetect(self) -> None:
        log("settings: Autodetect paths")
        self._on_autodetect(self)
        self._refresh()

    def _check_missing(self) -> None:
        log("settings: Check for missing Workshop mods")
        if self._on_check_missing is not None:
            self._on_check_missing(self)

    def _set_acquire_via(self, via: str) -> None:
        """A radio clicked: stored as an explicit choice (ends the GOG auto-pick)."""
        before = self._settings.get()["steam_acquire_via"]
        try:
            self._settings.set_steam_acquire_via(via)
        except (OSError, ValueError) as err:
            log(f"settings: download method {via} FAILED to save: {err!r}")
            self._warn("Couldn't save download method", str(err), self)
        else:
            log(f"settings: download method set to {via} (was {before or 'unset (auto)'})")
        self._refresh()

    def _open_log(self, path: Path | None) -> None:
        """Opens a log file with the OS's own association (App.jsx onOpenPath)."""
        if path is None:
            return
        try:
            paths.open_path(path)
        except OSError as err:
            log(f"settings: open log {path}: the OS refused: {err!r}")
            self._warn("Couldn't open log file", str(err), self)
            return
        log(f"settings: opened log {path}")
