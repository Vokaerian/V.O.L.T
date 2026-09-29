"""RimWorld main screen.

Port of the Electron app's main screen (App.jsx + PathsBar / LoadOrderBar /
DetailsPanel / ModList / ActionsColumn, styled by styles.css). Wired so far:
path resolution (saved settings, else autodetect), the paths bar, game
version, Rescan, the details panel, double-click moves between panes,
click-the-selected-row-to-deselect, drag-reorder within Active (a preview
while dragging, one model move at the drop - screens/mod_list.py), and load
orders: the picker, New / Copy to new, Save, and Push (save, then write
ModsConfig.xml), with unsaved-changes tracking (dirty vs a baseline, undo,
discard/push confirms), Run (launches the game; never saves or pushes), the
Scan issues window (screens/scan_issues_window.py), per-pane search (the
query box + eye toggle, pane-title counts; screens/mod_list.py PaneSearch),
mod colors (row swatches, color filter), the rows' decorations (official
badge, outdated names, the selected mod's dependency highlighting;
mod_decorations.py), the rows' right-click menu (_show_mod_menu), Sort
(_sort: user rules + community rules + About.xml + dependency ordering,
sort.py / community_rules.py), the Rules window for
the user's own Sort rules (screens/rules_window.py, from the right-click
menu's Rules... submenu) and live load-order validation (validation.py:
the merged warnings/errors button, the Active rows' issue icons and conflict
marking, the Warnings and errors window - screens/validation_window.py) and
the Settings window (screens/settings_window.py, from the paths bar's
Settings button: General - the paths, Browse... for the game / config folder
and Autodetect paths, shared with the no-game message's "Locate RimWorld
folder..." / "Try autodetect again"; Steam - the mod-acquisition setting,
its "Check for missing Workshop mods" - _check_missing_workshop, fetching
every not-found Workshop row of Active the way Subscribe does;
Troubleshooting - open this run's / the previous run's log file) and
Import... / Export... (mod_list_io.py: each opens a menu of sources /
destinations - import from the clipboard, a RimPy .xml file, a rentry.co page
or a save, replacing the Active list as one undoable, unsaved edit; export
the Active list to rentry.co, the clipboard in RimSort format or a RimPy .xml
file) and Import...'s "From Steam Workshop..." (steam_web_api.py +
screens/collection_dialog.py: a collection URL / id resolves through Steam's
keyless Web API, nested collections expanded; a single mod's link / id is
appended to the Active list, a collection offers Add to list / Replace list /
New load order..., every scanned official id folded in on top since a
Workshop collection can't hold Core / DLC; pending items download right away
through the same SteamCMD path as Subscribe - _on_collection_import,
_acquire_pending; the items' Workshop titles fill workshop_titles). On a
fresh install, the Electron app's dev load orders are migrated once
(electron_import). Not-found rows (App.jsx / lists.js reconcileLists:
an Active id with no scanned mod stays in the list, so Save / Push never
silently drop it - _show_lists keeps every such id, for load, rescan, import
and undo alike; a double-click out of Active just removes it, _move): a
pending Workshop row (a not-found id that is a Workshop id,
mod_list_io.not_found_workshop_id) is rendered with the dashed outline,
"(pending)", the painted Subscribe button, the not-found details view and the
context menu's Subscribe, any other not-found id as the red "(not found)"
row; Subscribe (_subscribe, the button or the menu entry) fetches that one
Workshop item on a background thread, the row showing "downloading..."
meanwhile and a rescan then swapping it for the real mod: with SteamCMD in
the 'steamcmd' / 'gog' acquisition modes (steam_cmd.py:
_download_via_steamcmd / _on_steamcmd_download_done), or through the
running Steam client in the 'steamworks' mode (steam_client.py +
steam_ops.py: _subscribe_via_steam / _on_steam_subscribe_done - subscribe,
then poll until Steam has it installed, up to SYNC_CONCURRENCY items at
once for an import's pending rows; offered only while
steam_client.availability() says Steam can be reached - _steam_available,
refreshed with the paths, gating the button, the menu entry and the
tooltip). The menu's Unsubscribe (_unsubscribe, confirmed first): a real
subscription is unsubscribed through the Steam client, verified, then its
Workshop folder deleted (steam_ops.unsubscribe_verified /
delete_workshop_folder); a SteamCMD download only has its folder deleted
(steam_cmd.delete_item, fsutil.remove_tree_best_effort - best effort, a
locked file is skipped and reported). Sync (_sync_to_steam,
steam_ops.sync_steamcmd_mods): every SteamCMD-downloaded 'steamcmd' copy
becomes a real Steam subscription, its copy deleted once Steam's own
download is on disk; a permanent 'gog' copy is never touched. Still inert:
a pending row not from a collection import has no Workshop title. The
footer (App.jsx's .action-divider + footer.statusbar): the status text on
the left (App.jsx say(text, kind)) carries Run's and Push's success
messages, as in Electron; every other notice (Sort included) is still a
_Notice toast / _warn box for now, and the
SteamCMD download row docks at its right while a download is in flight or
paused (screens/download_bar.py, DownloadBar.jsx: pause / resume, label,
striped progress pill over every item requested, done / total, speed, a
warning icon naming failed items; its state is download_state.DownloadState
in _dl - one shared row for every _download_via_steamcmd call in flight,
fed by each run's live events through _SteamCmdDownloadDone.progress ->
_on_steamcmd_progress, its pause / resume button -> _toggle_download_pause).

Top to bottom:
  paths bar      Settings | Paths: Game / Mods / Config | storefront tag | version
  load-order bar Load order [picker] New.. Copy.. [Unsaved changes undo] | ... Game version
  content row    [details | inactive | active] (1.2 : 1 : 1) + actions column (150px)
  footer         divider; [status text (empty)] ... [download row, while downloading / paused]
"""

import functools
import sys
import threading
import time
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QByteArray, QItemSelectionModel, QObject, QPoint, QRectF, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QGuiApplication, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from volt_py import (
    community_rules, download_state, icons, load_orders, mod_decorations, mod_list_io, mods, mods_config, painters,
    paths, sort, steam_client, steam_cmd, steam_ops, steam_web_api, theme, validation,
)
from volt_py.app_root import GAME_SLUG, resolve_app_root
from volt_py.applog import clip, init_log, log
from volt_py.electron_import import import_electron_load_orders_if_needed
from volt_py.fsutil import read_text, write_text_atomic
from volt_py.ids import exportable_ids
from volt_py.mod_decorations import RowDecor
from volt_py.screens.collection_dialog import CollectionDialog
from volt_py.screens.details_panel import DetailsPanel
from volt_py.screens.download_bar import DownloadBar
from volt_py.screens.help_window import HelpWindow
from volt_py.screens.mod_list import ModListView, mod_matches
from volt_py.screens.rimworld_help_entries import RIMWORLD_HELP_ENTRIES
from volt_py.screens.rules_window import RulesWindow
from volt_py.screens.scan_issues_window import ScanIssuesWindow, workshop_title
from volt_py.screens.settings_window import SettingsWindow
from volt_py.screens.validation_window import ValidationWindow
from volt_py.settings import SettingsStore, effective_acquire_via

# styles.css spacing (px).
BAR_SIDE = 12  # .paths-bar / .loadorder-bar / .content-row horizontal padding
GAP = 8  # .header-row / .loadorder-bar / .content-row / .main gap
# .main: grid-template-columns: minmax(280px, 1.2fr) minmax(240px, 1fr) minmax(240px, 1fr)
GRID_STRETCH = (12, 10, 10)
GRID_MIN_WIDTH = (280, 240, 240)
ACTIONS_WIDTH = 150
NOTICE_MS = 5000  # success notices (_Notice) close themselves after this long
NOTICE_BOTTOM = 24  # px between a notice and the screen's bottom edge

# Steam-client operations (App.jsx's constants, in seconds).
# Subscribe (Steam-client mode): after subscribing, poll install_info every
# SUBSCRIBE_POLL_S until Steam reports the item installed, up to
# SUBSCRIBE_TIMEOUT_S; SUBSCRIBE_NOT_SUBSCRIBED_POLLS polls in a row with the
# item neither subscribed nor downloading = it doesn't exist / is private.
SUBSCRIBE_POLL_S = 2.0
SUBSCRIBE_TIMEOUT_S = 120.0
SUBSCRIBE_NOT_SUBSCRIBED_POLLS = 3
# Unsubscribe: re-check Steam's subscribed flag up to 5 times, 1s apart,
# before touching any files (a returned unsubscribe isn't proof it took).
UNSUBSCRIBE_VERIFY_TRIES = 5
UNSUBSCRIBE_VERIFY_S = 1.0
# Sync to Steam: how many SteamCMD mods are waited on at once in its install
# pass (steam_ops.sync_steamcmd_mods; one Steam helper process each). Also
# the Steam-client mode's Subscribe batch (_subscribe_via_steam). Untested on
# real hardware at 5 in this port: if Steam objects to that many at once
# (failed subscribes, helpers erroring), dial this down - 1 is one-at-a-time.
SYNC_CONCURRENCY = 5
# Sync to Steam's subscribe pass (subscribe + verify, then the helper is
# released): how many run at once. Somewhat above SYNC_CONCURRENCY because
# each item holds its helper for only about a second (Electron's real log
# showed 5 concurrent subscribe calls landing within ~130 ms), so this pass
# finishes a big list quickly - the point of it is registering every
# subscription up front. Capped rather than all at once: each in-flight item
# is its own helper process registered with Steam as "RimWorld running", and
# a 370-mod list must not spawn hundreds. If Steam objects at 8, set this
# back to SYNC_CONCURRENCY.
SYNC_SUBSCRIBE_CONCURRENCY = 8
# Sync to Steam's heads-up dialog (_confirm_sync): the three caveats, one
# bullet each, in this order.
SYNC_CONFIRM_LINES = (
    "Syncing can take a few minutes for a large mod list.",
    'RimWorld will show as "Running" on Steam while the sync helper is active. This is expected, not a bug.',
    "Don't quit VOLT or launch the game until the sync finishes.",
)

SOURCE_LABEL = {"steam": "Steam", "gog": "GOG", "manual": "Manual"}  # PathsBar.jsx

# ModList.jsx EyeIcon: the slash is drawn only when not `open`. Closed
# (slashed, --muted) = the default, hiding non-matches; open (no slash,
# --accent: .search-eye.on) = dimming them.
_EYE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16" '
    'fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round">'
    '<path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z"/>'
    '<circle cx="8" cy="8" r="2"/>'
    "{slash}"
    "</svg>"
)
_EYE_SLASH = '<path d="M2 14L14 2"/>'
# ModList.jsx search-eye title, by dim (eye open).
_EYE_TOOLTIP = {
    False: "Hiding non-matches. Click to show all mods with non-matches dimmed.",
    True: "Showing all mods, non-matches dimmed. Click to hide non-matches.",
}


@functools.cache
def _eye_icon(open: bool) -> QIcon:
    # Rendered at 2x so it stays sharp on high-DPI screens; shown at 14x14.
    # Cached: two icons in all, swapped on every toggle.
    svg = _EYE_SVG.format(color=theme.ACCENT if open else theme.MUTED, slash="" if open else _EYE_SLASH)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, 28, 28))
    painter.end()
    return QIcon(pixmap)


def _label(text: str, *, muted: bool = False) -> QLabel:
    label = QLabel(text)
    if muted:
        label.setProperty("muted", True)
    return label


def _button(text: str, *, variant: str | None = None) -> QPushButton:
    button = QPushButton(text)
    if variant:
        button.setProperty("variant", variant)
    button.setEnabled(False)
    return button


def _panel() -> QFrame:
    frame = QFrame()
    frame.setProperty("panel", True)
    return frame


def _issue_count_html(warnings: int, errors: int) -> str:
    """ActionsColumn.jsx's issue-count label: [warn] N · [x] M, the drawn
    icons (icons.py; were the ⚠︎ / ✕ glyphs, which Windows drew as a color
    emoji) in --warn / --danger, the dot --muted."""
    return (
        f'{icons.inline("warn", theme.WARN)} {warnings} '
        f'<span style="color:{theme.MUTED}">·</span> '
        f'{icons.inline("x", theme.DANGER)} {errors}'
    )


class _Notice(QFrame):
    """A small self-closing success notice ("toast"), laid over the screen as a
    plain child widget: closes itself after NOTICE_MS, or early on a click.

    Deliberately not a QMessageBox. On Windows a QMessageBox with a standard
    icon plays the system message sound when shown (its showEvent raises an
    accessibility Alert, which Windows answers with the icon's sound), and
    exec() blocks until OK is clicked. A child QFrame is never its own window
    and raises no Alert - so no OS sound and nothing modal."""

    def __init__(self, title: str, message: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("notice")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(2)
        heading = QLabel(title)
        heading.setProperty("role", "notice-title")
        layout.addWidget(heading)
        layout.addWidget(QLabel(message))
        timer = QTimer(self)  # a child: dies with the notice if it's clicked away first
        timer.setSingleShot(True)
        timer.timeout.connect(self.close)
        timer.start(NOTICE_MS)

    def mousePressEvent(self, event) -> None:
        self.close()


class _StatusText(QLabel):
    """.status-text: one line that takes the footer's spare width (flex: 1;
    min-width: 0) and elides with … when the text doesn't fit (the
    settings window's _PathValue pattern). set_status_text is App.jsx's
    say(text, kind): kind "info" / "error" / "warn" is a QSS property
    (theme.py: .statusbar.error / .warn .status-text colors)."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "status-text")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._full = ""
        self._kind = "info"

    def set_status_text(self, text: str, kind: str = "info") -> None:
        """Logged like _warn / _notice, so volt.log still shows what was said."""
        log(f"status shown ({kind}): {text}")
        self._full = text
        if kind != self._kind:
            self._kind = kind
            self.setProperty("kind", kind)
            # a property selector isn't re-evaluated on its own after the first polish
            self.style().unpolish(self)
            self.style().polish(self)
        self._elide()

    def status_kind(self) -> str:
        return self._kind

    def status_text(self) -> str:
        return self._full

    def sizeHint(self):
        return QSize(0, self.fontMetrics().height())  # one text line tall, no width of its own

    def minimumSizeHint(self):
        return self.sizeHint()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width()
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, width)))


class _CommunityRulesLoaded(QObject):
    """Carries "the startup community-rules lookup finished" from its
    background thread to the GUI thread (a queued connection). No payload:
    the result lives in community_rules' own cache (loaded_rules)."""

    done = Signal()


def _fetch_community_rules(app_root: Path, loaded: _CommunityRulesLoaded) -> None:
    """Background-thread body: the once-per-process community-rules lookup
    (community_rules.get_community_rules - never raises), then `loaded.done`.
    A module function, not a screen method, so the thread holds no reference
    to the screen; it does hold `loaded`, so that object outlives any emit."""
    result = community_rules.get_community_rules(app_root)
    log(f"community rules: background lookup finished (source={result['source']}, {len(result['rules'])} mods with rules)")
    try:
        loaded.done.emit()
    except RuntimeError as err:  # shutting down: the Qt side is already gone
        log(f"community rules: could not signal the screen ({err!r})")


class _SteamCmdDownloadDone(QObject):
    """Carries one SteamCMD download run's outcome from its background thread
    to the GUI thread (a queued connection; the _CommunityRulesLoaded
    pattern). done's payload: {"rows": [row ids], "wids": [Workshop ids],
    "report": steam_cmd.download_items' result or None, "failure": the
    error message when the run raised, else None, "carrier": this object,
    so the screen can drop it from _steamcmd_jobs}. progress: every live
    steam_cmd event (create_progress_parser's dicts), emitted from the
    download thread for the footer's download row (_on_steamcmd_progress)."""

    done = Signal(object)
    progress = Signal(object)


def _download_workshop_items(app_root: Path, wids: list[str], mods_dir: Path, mode: str, rows: list[str],
                             carrier: _SteamCmdDownloadDone) -> None:
    """Background-thread body: one steam_cmd.download_items run (blocks for
    seconds to minutes), then `carrier.done`. A module function, not a screen
    method, so the thread holds no reference to the screen; it does hold
    `carrier`, which the screen also keeps until the done slot has run."""
    report, failure = None, None

    def on_event(ev: dict) -> None:
        carrier.progress.emit(ev)  # a RuntimeError at shutdown is caught and logged by download_items

    try:
        report = steam_cmd.download_items(app_root, wids, mods_dir, on_event=on_event, mode=mode)
    except Exception as err:  # SteamCmdError / ValueError, or anything unexpected: the thread must never die silently
        failure = str(err) or repr(err)
        log(f"steamcmd download: run FAILED - {failure}")
    try:
        carrier.done.emit({"rows": rows, "wids": wids, "report": report, "failure": failure, "carrier": carrier})
    except RuntimeError as err:  # shutting down: the Qt side is already gone
        log(f"steamcmd download: could not signal the screen ({err!r})")


class _SteamClientDone(QObject):
    """Carries one Steam-client operation's outcome (a Subscribe batch, an
    Unsubscribe, a Sync to Steam - steam_ops flows over steam_client) from its
    background thread to the GUI thread (a queued connection; the
    _SteamCmdDownloadDone pattern). done's payload: a dict with "carrier":
    this object (so the screen can drop it from _steam_jobs) plus the
    operation's own fields (each thread body documents its own). item: one
    Workshop id whose part of a batch has landed, emitted per item as it
    finishes, for the Subscribe batch's rows to stop "downloading" one by one
    (App.jsx's per-item setDownloading)."""

    done = Signal(object)
    item = Signal(object)


def _emit(carrier: _SteamClientDone, what: str, payload: dict) -> None:
    try:
        carrier.done.emit({**payload, "carrier": carrier})
    except RuntimeError as err:  # shutting down: the Qt side is already gone
        log(f"{what}: could not signal the screen ({err!r})")


def _steam_ops_for(app_root: Path, game_dir: Path, mods_dir: Path | None = None):
    """The `steam` object steam_ops' flows take (lists.js's `steam` of
    functions, App.jsx wired it to the IPC api): steam_client's calls bound to
    this game, plus steam_cmd.delete_item bound to <game>/Mods (Sync's
    delete_copy), release, a real sleep and clock. Built on the calling
    thread, used on the background one."""
    return SimpleNamespace(
        subscribe=lambda wid: steam_client.subscribe(app_root, game_dir, wid),
        install_info=lambda wid: steam_client.install_info(app_root, game_dir, wid),
        is_subscribed=lambda wid: steam_client.is_subscribed(app_root, game_dir, wid),
        unsubscribe=lambda wid: steam_client.unsubscribe(app_root, game_dir, wid),
        release=steam_client.release,
        delete_copy=lambda path: steam_cmd.delete_item(mods_dir, path),
        sleep=time.sleep,
        now=time.monotonic,
    )


def _subscribe_workshop_items(steam, wids: list[str], rows_by_wid: dict[str, list[str]],
                              carrier: _SteamClientDone) -> None:
    """Background-thread body of the Steam-client Subscribe batch (App.jsx
    subscribeViaSteamworks's runPool): each Workshop id runs Subscribe's own
    flow (steam_ops.steam_subscribe_and_wait), up to SYNC_CONCURRENCY at
    once, `carrier.item` per finished id ({"wid", "rows": its row ids} - they
    stop "downloading"), then `carrier.done` with {"wids", "rows": every row
    id, "failed": [{"wid", "error"}] in completion order, "failure": a message
    when the pool itself raised, else None}."""
    failed: list[dict] = []
    failure = None
    total = len(wids)
    done = 0
    lock = threading.Lock()

    def one(wid: str) -> None:
        nonlocal done
        try:
            steam_ops.steam_subscribe_and_wait(
                wid, steam, poll_s=SUBSCRIBE_POLL_S, timeout_s=SUBSCRIBE_TIMEOUT_S,
                not_subscribed_polls=SUBSCRIBE_NOT_SUBSCRIBED_POLLS,
            )
        except Exception as err:  # SteamClientError, or anything unexpected: one item's failure never ends the batch
            error = str(err) or repr(err)
            log(f"subscribe {wid}: FAILED - {error}")
            failed.append({"wid": wid, "error": error})
        finally:
            with lock:
                done += 1
                n = done
            if total > 1:
                log(f"steam subscribe batch: {n}/{total} done ({total - n} remaining)")
            try:
                carrier.item.emit({"wid": wid, "rows": rows_by_wid[wid]})
            except RuntimeError as err:  # shutting down
                log(f"steam subscribe batch: could not signal the screen for {wid} ({err!r})")

    try:
        steam_ops.run_pool(wids, SYNC_CONCURRENCY, one)
    except Exception as err:  # never expected (`one` handles its own errors); the JS catches too
        failure = str(err) or repr(err)
        log(f"steam subscribe batch: FAILED - {failure}")
    _emit(carrier, "steam subscribe batch",
          {"wids": wids, "rows": [r for rows in rows_by_wid.values() for r in rows], "failed": failed, "failure": failure})


def _unsubscribe_workshop_item(steam, game_dir: Path, mod_id: str, wid: str, name: str,
                               carrier: _SteamClientDone) -> None:
    """Background-thread body of Unsubscribe's 'steam' kind (App.jsx
    unsubscribeNow): unsubscribe, verify Steam really dropped it
    (steam_ops.unsubscribe_verified), and only then delete the item's
    Workshop folder (steam_ops.delete_workshop_folder). `carrier.done` with
    {"mod_id", "wid", "name", "result": the delete's dict or None, "failure":
    the error message when it didn't get to the delete, else None}."""
    result, failure = None, None
    try:
        steam_ops.unsubscribe_verified(wid, name, steam, tries=UNSUBSCRIBE_VERIFY_TRIES, wait_s=UNSUBSCRIBE_VERIFY_S)
        result = steam_ops.delete_workshop_folder(game_dir, wid)
    except Exception as err:  # SteamClientError (still subscribed, Steam down...), or anything unexpected
        failure = str(err) or repr(err)
        log(f"unsubscribe {wid}: FAILED - {failure}")
    _emit(carrier, f"unsubscribe {wid}",
          {"mod_id": mod_id, "wid": wid, "name": name, "result": result, "failure": failure})


def _sync_to_steam_run(steam, mods_snapshot: dict, carrier: _SteamClientDone) -> None:
    """Background-thread body of Sync to Steam (App.jsx syncToSteam's await):
    steam_ops.sync_steamcmd_mods over a snapshot of the scanned mods, its
    per-item progress logged (Electron showed it in the status bar; this
    port's status text isn't wired yet), then `carrier.done` with {"result":
    its {"total", "synced", "pending", "failed"} dict or None, "failure": the
    message when the run itself raised, else None}."""
    result, failure = None, None

    def on_progress(done: int, total: int) -> None:
        log(f"sync progress: {done}/{total} ({total - done} remaining)")

    try:
        result = steam_ops.sync_steamcmd_mods(
            mods_snapshot, steam, tries=UNSUBSCRIBE_VERIFY_TRIES, wait_s=UNSUBSCRIBE_VERIFY_S, poll_s=SUBSCRIBE_POLL_S,
            timeout_s=SUBSCRIBE_TIMEOUT_S, concurrency=SYNC_CONCURRENCY,
            subscribe_concurrency=SYNC_SUBSCRIBE_CONCURRENCY, on_progress=on_progress,
        )
    except Exception as err:  # the run itself (not one item) raised: unexpected, but the thread must never die silently
        failure = str(err) or repr(err)
        log(f"sync: run FAILED - {failure}")
    _emit(carrier, "sync", {"result": result, "failure": failure})


class RimWorldMainScreen(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_paths_bar())
        layout.addWidget(self._build_load_order_bar())
        layout.addLayout(self._build_content_row(), 1)
        layout.addWidget(self._build_footer())

        self.game_dir: Path | None = None
        self.config_dir: Path | None = None
        self._mods: dict[str, dict] = {}  # id -> scanned mod
        # Pending Workshop rows (App.jsx workshopTitles / downloading): a
        # not-found Workshop id's title, keyed by Workshop id (shown instead
        # of the id: row name, tooltip, details), and the row ids with a
        # Subscribe under way (faded, "downloading..."; _download_via_steamcmd
        # adds, _on_steamcmd_download_done removes, each followed by
        # _refresh_workshop_rows). workshop_titles is filled by the Steam
        # Workshop import (_on_collection_import: every resolved item's title).
        self.workshop_titles: dict[str, str] = {}
        self.downloading: set[str] = set()
        # Each SteamCMD download in flight: its signal carrier (kept alive
        # here until its queued `done` has been delivered) and its thread.
        self._steamcmd_jobs: dict[_SteamCmdDownloadDone, threading.Thread] = {}
        # Steam-client operations (steam_client / steam_ops through the Steam
        # client, App.jsx's steamAvailable / syncing / busy): whether Steam
        # Workshop actions through the Steam client can be offered for this
        # install (steam_client.availability(), refreshed whenever the paths
        # are - _refresh_steam), each operation in flight (its carrier and
        # thread, as _steamcmd_jobs), the mod ids with an Unsubscribe under
        # way (their menu entry disabled meanwhile) and whether a Sync to
        # Steam is running (its button reads "Syncing...", a second click is
        # refused).
        self._steam_available = False
        self._steam_jobs: dict[_SteamClientDone, threading.Thread] = {}
        self._unsubscribing: set[str] = set()
        self._syncing = False
        # The footer's SteamCMD download row (App.jsx dl): None = hidden; else
        # one shared download_state.DownloadState across every run in flight
        # (its `active` counts them) - _download_via_steamcmd merges a start
        # in, _on_steamcmd_progress folds the live events in,
        # _on_steamcmd_download_done settles it (paused, or gone), and
        # _render_download_bar paints it.
        self._dl: download_state.DownloadState | None = None
        self._order: dict[str, int] = {}  # id -> scan (name-sorted) position
        self._game_version: str | None = None  # Version.txt's first line (_apply_paths)
        # Row decorations: memoized per scan (keyed on the self._mods object,
        # which every rescan replaces) - _outdated_ids / _dependency_index.
        self._outdated_key: tuple | None = None  # (mods dict, game version) of _outdated
        self._outdated: set[str] = set()
        self._dep_index_for: dict | None = None  # the mods dict _dep_index was built from
        self._dep_index: dict = {}
        # The selected mod's dependencies / dependents (App.jsx dependencyIds /
        # dependentIds), tinted in both panes (_highlight_dependencies).
        self._dependency_ids: frozenset = frozenset()
        self._dependent_ids: frozenset = frozenset()
        # Live validation (validation.validate_active over the Active list,
        # App.jsx's `validation` memo; _update_validation): its issues, the
        # same grouped by mod (App.jsx issuesByMod) and its conflict pairs.
        self._validation_issues: list[dict] = []
        self._issues_by_mod: dict[str, list[dict]] = {}
        self._conflicts: dict[str, set[str]] = {}
        self._scan_problems: list[dict] = []  # minus ignored_scan_issues; the Scan issues window's list
        self.app_root = resolve_app_root(GAME_SLUG)
        # Dev-only action log at <app_root>/volt.log. Started here because this
        # is the first point the per-game APP-ROOT is known; once a real
        # game-selection screen exists (multi-game, later slice), this moves to
        # wherever the chosen game's app root gets resolved. None in a packaged
        # build (no log): Settings > Troubleshooting's log buttons follow.
        self._log_path: Path | None = init_log(self.app_root)
        log(f"app root: {self.app_root}")
        # Community rules: looked up now, off the GUI thread (Electron fetches
        # them at launch; this screen is where this game's app root - and its
        # cache file - is first known), so validation's community tier is live
        # without a Sort. A Sort clicked meanwhile waits for this same lookup
        # (community_rules' lock). A daemon threading.Thread, not a QThread:
        # the fetch blocks in urllib and can't be interrupted, and a QThread
        # still running when it's destroyed at quit is a Qt fatal error -
        # a daemon thread just ends with the process.
        self._community_rules_loaded = _CommunityRulesLoaded()  # no parent: owned by self and the thread
        self._community_rules_loaded.done.connect(
            self._on_community_rules_loaded, Qt.ConnectionType.QueuedConnection
        )
        self._community_rules_thread = threading.Thread(
            target=_fetch_community_rules,
            args=(self.app_root, self._community_rules_loaded),
            name="community-rules",
            daemon=True,
        )
        self._community_rules_thread.start()
        log(f"community rules: background lookup started (thread {self._community_rules_thread.name})")
        self._settings = SettingsStore()
        # Settings > General > Animations, app-wide from here on (phase 4)
        theme.set_animation_mode(self._settings.get()["animations"])
        log(f"animations: {self._settings.get()['animations']}")
        self.current_load_order: str | None = None  # slug
        # App.jsx baselineActive/history: dirty = Active ids != baseline (order
        # matters); _history = pre-change Active snapshots, most recent last.
        # Both reset on load-order load/create/save.
        self._baseline: list[str] = []
        self._history: list[list[str]] = []
        self._was_dirty = False
        self._connect_signals()
        self._resolve_paths()
        # Load orders before the first rescan: it splits Active/Inactive by the current one.
        migrated = import_electron_load_orders_if_needed(self.app_root, GAME_SLUG)
        if migrated:
            print(f"[rimworld] imported Electron load orders: {', '.join(migrated)}")
        log(f"Electron load-order import: {'imported ' + ', '.join(migrated) if migrated else 'nothing imported'}")
        self._reload_load_order_picker()
        self._apply_paths()
        if self.game_dir:
            if self._scan():
                self._apply_current_load_order_to_panes()
        else:
            log("no game folder: skipping the initial rescan")

    # ---- paths: saved settings, else autodetect ----
    def _resolve_paths(self) -> None:
        store = self._settings
        s = store.get()
        game_dir = s["game_dir"]
        if not (game_dir and paths.is_game_root(game_dir)):
            # Unset, or the saved install moved/was deleted: re-detect.
            log(
                f"paths: saved game folder {game_dir!r} is not a RimWorld install, autodetecting"
                if game_dir else "paths: no saved game folder, autodetecting"
            )
            game_dir = None
            found = paths.autodetect()
            log(
                f"paths: autodetect found game={clip(found['game'])}, config_dir={found['config_dir']}, "
                f"tried={clip(found['tried'])}"
            )
            if found["game"]:
                game_dir = str(found["game"]["game_dir"])
                s = store.update({
                    "game_dir": game_dir,
                    "game_source": found["game"]["source"],
                    # Keep a previously saved config dir if detection found none.
                    "config_dir": str(found["config_dir"]) if found["config_dir"] else s["config_dir"],
                })
        self._load_paths()
        if self.game_dir is None:
            log(f"paths: no game folder found; config_dir={self.config_dir}")
        else:
            log(f"paths: game_dir={self.game_dir}, config_dir={self.config_dir}, source={self._game_source}")

    def _load_paths(self) -> None:
        """game_dir / _game_source / config_dir from settings (main.js
        pathsState): a saved game folder that's no longer a RimWorld install
        counts as unset, and flags _saved_game_dir_missing (the no-game
        message's wording)."""
        s = self._settings.get()
        saved = s["game_dir"]
        ok = bool(saved) and paths.is_game_root(saved)
        self.game_dir = Path(saved) if ok else None
        self._game_source = s["game_source"] if ok else None
        self._saved_game_dir_missing = bool(saved) and not ok
        self.config_dir = Path(s["config_dir"]) if s["config_dir"] else None

    def _paths_state(self) -> dict:
        """The current paths, for the Settings window."""
        return {"game_dir": self.game_dir, "game_source": self._game_source, "config_dir": self.config_dir}

    def _reload_for_paths(self) -> None:
        """After Browse / Autodetect changed the saved paths (App.jsx
        reloadForPaths): re-reads them, refreshes the paths bar etc., then
        rescans. A game folder that was already set keeps the on-screen
        Active list (Rescan); one found just now shows the current load
        order, as at startup."""
        had_game = self.game_dir is not None
        self._load_paths()
        log(
            f"paths changed: game_dir={self.game_dir}, config_dir={self.config_dir}, source={self._game_source}, "
            f"saved game folder missing={self._saved_game_dir_missing}"
        )
        self._apply_paths()
        if self.game_dir is None:
            log("paths changed: no game folder, nothing to rescan")
        elif had_game:
            self.rescan()
        elif self._scan():
            self._apply_current_load_order_to_panes()

    def _browse_path(self, kind: str, parent: QWidget | None = None) -> None:
        """Browse... for the game ('game') or config ('config') folder
        (main.js paths:browse + App.jsx onBrowse): a folder picker; a pick
        that doesn't look right is refused with a warning, never saved.
        parent: the dialog asking (Settings), so the picker and any warning
        sit over it; else this screen."""
        if kind not in ("game", "config"):
            raise ValueError(f"Unknown path kind: {kind}")
        s = self._settings.get()
        current = s["game_dir"] if kind == "game" else s["config_dir"]
        start = current or (paths.default_config_dir() if kind == "config" else None)
        caption = (
            "Locate your RimWorld install folder" if kind == "game"
            else "Locate RimWorld's Config folder (holds ModsConfig.xml)"
        )
        log(f"browse {kind} folder: picker opened at {start}")
        picked = QFileDialog.getExistingDirectory(parent if parent is not None else self, caption, str(start or ""))
        if not picked:
            log(f"browse {kind} folder: cancelled")
            return
        picked = str(paths.norm(picked))  # the dialog returns / separators on Windows too
        if kind == "game":
            game_dir = paths.normalize_game_dir(picked)
            if not game_dir:
                self._warn(
                    "Couldn't set game folder",
                    f'"{picked}" doesn\'t look like a RimWorld install folder '
                    "(expected Data/Core or the RimWorld executable inside it).",
                    parent,
                )
                return
            patch = {"game_dir": str(game_dir), "game_source": "manual"}
        else:
            if not (Path(picked).name.lower() == "config" or mods_config.mods_config_path(picked).exists()):
                self._warn(
                    "Couldn't set config folder",
                    f'"{picked}" doesn\'t look like RimWorld\'s Config folder '
                    "(expected a folder named Config, or one containing ModsConfig.xml).",
                    parent,
                )
                return
            patch = {"config_dir": picked}
        try:
            self._settings.update(patch)
        except OSError as err:
            self._warn("Couldn't save settings", str(err), parent)
            return
        log(f"browse {kind} folder: picked {picked}, saved {patch}")
        self._reload_for_paths()
        self._notice(
            "Paths",
            f"Game folder set to {self.game_dir}." if kind == "game" else f"Config folder set to {self.config_dir}.",
        )

    def _autodetect_paths(self, parent: QWidget | None = None) -> None:
        """Autodetect paths / Try autodetect again (main.js runAutodetect(true)
        + App.jsx onAutodetect): whatever detection finds replaces the saved
        path; what it doesn't find is left as it was. parent: as _browse_path."""
        found = paths.autodetect()
        log(
            f"autodetect (user): found game={clip(found['game'])}, config_dir={found['config_dir']}, "
            f"tried={clip(found['tried'])}"
        )
        patch = {}
        if found["game"]:
            patch["game_dir"] = str(found["game"]["game_dir"])
            patch["game_source"] = found["game"]["source"]
        if found["config_dir"]:
            patch["config_dir"] = str(found["config_dir"])
        if patch:
            try:
                self._settings.update(patch)
            except OSError as err:
                self._warn("Couldn't save settings", str(err), parent)
                return
        self._reload_for_paths()
        game = found["game"]
        if game:
            source = "GOG" if game["source"] == "gog" else "Steam"
            self._notice("Autodetect", f"Found RimWorld ({source}) at {game['game_dir']}.")
        else:
            # ponytail: a warning box - App.jsx says this in the status bar
            # (kind 'warn'), which this port doesn't have yet.
            self._warn("Autodetect", "Autodetect didn't find a RimWorld install. Please locate it manually.", parent)

    def _show_settings(self) -> None:
        log("settings window opened")
        SettingsWindow(
            self._settings, self._paths_state, self._browse_path, self._autodetect_paths, self._warn,
            self._log_path, self, on_check_missing=self._check_missing_workshop,
        ).exec()
        log("settings window closed")

    def _show_help(self) -> None:
        log("help window opened")
        HelpWindow(RIMWORLD_HELP_ENTRIES, parent=self).exec()
        log("help window closed")

    def _apply_paths(self) -> None:
        has_game = self.game_dir is not None
        mods_dir = self.game_dir / "Mods" if has_game else None
        for link, path in (
            (self.game_link, self.game_dir),
            (self.mods_link, mods_dir),
            (self.config_link, self.config_dir),
        ):
            link.setEnabled(path is not None)
            link.setToolTip(str(path) if path else "")

        source_label = SOURCE_LABEL.get(self._game_source)
        self.storefront_tag.setText(source_label or "")
        self.storefront_tag.setVisible(bool(source_label))

        self.game_version_label.setVisible(has_game)
        self._game_version = None
        if has_game:
            game_version = paths.read_game_version(self.game_dir)
            log(f"game version: {game_version or '(unreadable)'}")
            self.game_version_label.setText(f"Game version: {game_version or '—'}")
            self._game_version = game_version  # outdated marking (_outdated_ids)

        self._grid.setVisible(has_game)
        self._no_game.setVisible(not has_game)
        self._no_game_text.setText(
            ("The saved RimWorld folder no longer exists." if self._saved_game_dir_missing
             else "Autodetect didn't find a Steam or GOG install of RimWorld.")
            + " Please locate your RimWorld install folder (the one containing Data and Mods)."
        )
        self.rescan_button.setEnabled(has_game)
        self.run_button.setEnabled(has_game)  # ActionsColumn.jsx: disabled={busy || noGame}
        self.inactive_list.setEnabled(has_game)
        self.active_list.setEnabled(has_game)
        for search, eye in ((self.inactive_search, self.inactive_eye), (self.active_search, self.active_eye)):
            search.setEnabled(has_game)
            eye.setEnabled(has_game)
        self._refresh_steam()  # App.jsx reloadForPaths -> refreshSteam: Steam availability follows the paths
        self._apply_load_order_state()

    def _refresh_steam(self) -> steam_client.AvailabilityResult:
        """App.jsx refreshSteam (steam:available): whether Steam Workshop
        actions through the Steam client can be offered for this install -
        steam_client.availability(), a few file checks, no helper process. Re-
        read whenever the paths are (re)loaded and at the start of each Steam-
        client operation (a user who just placed the native files needn't
        restart). The reason is logged when it says no; the panes re-read
        their rows when the answer changes (the Subscribe button's enabled
        look, _subscribe_ready). Returns the result (available, reason)."""
        r = steam_client.availability(self.app_root, self.game_dir)
        if r.available != self._steam_available:
            log(f"steam available: {r.available}" + (f" ({r.reason})" if r.reason else ""))
            self._steam_available = r.available
            self._refresh_workshop_rows()
        elif not r.available:
            log(f"steam available: False ({r.reason})")
        return r

    def _acquire_via(self) -> str:
        """The mod-acquisition mode in effect (settings.effective_acquire_via)."""
        return effective_acquire_via(self._settings.get()["steam_acquire_via"], self._game_source)

    def _subscribe_ready(self) -> bool:
        """lists.js subscribeReady: whether Subscribe can run at all in the
        mode in effect - always in the SteamCMD modes, only with Steam
        available in the Steam-client mode. Gates the painted Subscribe button
        and the menu entry (ModList.jsx canSubscribe)."""
        return steam_ops.subscribe_ready(self._acquire_via(), self._steam_available)

    def _apply_load_order_state(self) -> None:
        has_game = self.game_dir is not None
        self.load_order_picker.setEnabled(has_game and self.load_order_picker.count() > 0)
        self.new_button.setEnabled(has_game)
        self.copy_button.setEnabled(has_game)
        self.save_button.setEnabled(has_game and self.current_load_order is not None)
        self.push_button.setEnabled(has_game and self.config_dir is not None)
        # ActionsColumn.jsx: disabled={disabled || !canSort}, canSort = active.length > 0.
        # Every Active change ends here (model row signals; resets are followed by a call).
        self.sort_button.setEnabled(has_game and self.active_list.mod_model.rowCount() > 0)
        # ActionsColumn.jsx: Sync disabled={disabled || syncing}, reading "Syncing..." meanwhile.
        self.sync_button.setEnabled(has_game and not self._syncing)
        self.sync_button.setText("Syncing..." if self._syncing else "Sync")
        # ActionsColumn.jsx: Import disabled={busy}, Export disabled={busy || activeCount === 0}.
        # Import also needs a game here: with no scan, an import would have nothing to show.
        self.import_button.setEnabled(has_game)
        self.export_button.setEnabled(has_game and self.active_list.mod_model.rowCount() > 0)
        # Unsaved changes: label + undo only exist while dirty; Save turns warn-outline.
        dirty = self._dirty()
        if dirty != self._was_dirty:
            log(f"unsaved changes: {'yes' if dirty else 'none'} ({len(self._history)} undo steps)")
            self._was_dirty = dirty
        self.dirty_label.setVisible(has_game and dirty)
        self.undo_button.setVisible(has_game and dirty)
        self.undo_button.setEnabled(has_game)
        variant = "warn-outline" if dirty else ""
        if self.save_button.property("variant") != variant:
            self.save_button.setProperty("variant", variant)
            # A property selector isn't re-evaluated on its own after the first polish.
            self.save_button.style().unpolish(self.save_button)
            self.save_button.style().polish(self.save_button)
        self._update_validation()

    def _update_validation(self) -> None:
        """App.jsx's validation memo (validateActive on every Active change),
        from _apply_load_order_state - every Active change ends there, as do
        rescans (new mods) and the Rules window closing (user rules). Issues
        and conflict pairs over the Active list, the scanned mods, this run's
        community rules once the startup background lookup (or a Sort) has
        loaded them (community_rules.loaded_rules - never fetched from here;
        _on_community_rules_loaded re-runs this when they arrive) and the
        user's own Sort rules. When the result changed: the merged
        warnings/errors button and both panes' decorations (issue icons,
        conflict marking) follow."""
        active = self.active_list.mod_ids()
        user_rules = self._settings.get()["user_rules"] or []
        result = validation.validate_active(active, self._mods, community_rules.loaded_rules(), user_rules)
        issues, conflicts = result["issues"], result["conflicts"]
        if issues == self._validation_issues and conflicts == self._conflicts:
            return
        by_mod: dict[str, list[dict]] = {}  # App.jsx issuesByMod: grouped by mod, issue order kept
        for issue in issues:
            by_mod.setdefault(issue["mod_id"], []).append(issue)
        self._validation_issues, self._issues_by_mod, self._conflicts = issues, by_mod, conflicts
        warnings = sum(1 for i in issues if i["severity"] == "warning")
        log(
            f"validation: {warnings} warnings, {len(issues) - warnings} errors over {len(active)} active mods "
            f"({len(conflicts)} mods in conflicts): {clip([i['key'] for i in issues])}"
        )
        self._update_issues_button()
        for pane in (self.inactive_list, self.active_list):
            pane.mod_model.refresh_decorations()

    @Slot()
    def _on_community_rules_loaded(self) -> None:
        """The startup community-rules lookup finished (on the GUI thread, via
        a queued connection): re-run validation, which now has the community
        tier (or still none, if the lookup found no rules)."""
        rules = community_rules.loaded_rules()
        log(f"community rules: loaded ({len(rules or {})} mods with rules), re-running validation")
        self._update_validation()

    def _dirty(self) -> bool:
        return self.active_list.mod_ids() != self._baseline

    def _reset_baseline(self) -> None:
        """The on-screen Active list becomes the saved state: not dirty, no undo."""
        self._baseline = self.active_list.mod_ids()
        self._history = []
        self._apply_load_order_state()

    def _connect_signals(self) -> None:
        self.settings_button.setEnabled(True)  # always usable (PathsBar.jsx: disabled only while busy)
        self.settings_button.clicked.connect(lambda: self._show_settings())
        self.help_button.setEnabled(True)  # always usable, like Settings
        self.help_button.clicked.connect(lambda: self._show_help())
        self.game_link.clicked.connect(lambda: self._open_folder(self.game_dir))
        self.mods_link.clicked.connect(lambda: self._open_folder(self.game_dir / "Mods"))
        self.config_link.clicked.connect(lambda: self._open_folder(self.config_dir))
        self.load_order_link.clicked.connect(
            lambda: self.current_load_order and self._open_folder(self._load_order_dir())
        )
        self.rescan_button.clicked.connect(lambda: self.rescan())
        # Every real Active change (double-click move in/out, drag-drop commit)
        # goes through one of these model signals; the *AboutTo* ones fire
        # before the change, so the list is still the pre-change snapshot.
        # Repopulating (set_mod_ids -> model reset: load, rescan, undo) isn't
        # connected, so it never counts as an edit.
        active_model = self.active_list.mod_model
        for signal in (active_model.rowsAboutToBeInserted, active_model.rowsAboutToBeRemoved,
                       active_model.rowsAboutToBeMoved):
            signal.connect(lambda *_: self._history.append(self.active_list.mod_ids()))
        for signal in (active_model.rowsInserted, active_model.rowsRemoved, active_model.rowsMoved):
            signal.connect(lambda *_: self._apply_load_order_state())
        self.undo_button.clicked.connect(lambda: self._undo())
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self).activated.connect(lambda: self._undo_shortcut())
        # One selection across both panes (App.jsx keeps a single selected id).
        self.inactive_list.selectionModel().selectionChanged.connect(
            lambda *_: self._on_selection_changed(self.inactive_list, self.active_list)
        )
        self.active_list.selectionModel().selectionChanged.connect(
            lambda *_: self._on_selection_changed(self.active_list, self.inactive_list)
        )
        self.inactive_list.doubleClicked.connect(
            lambda index: self._move(index, self.inactive_list, self.active_list)
        )
        self.active_list.doubleClicked.connect(
            lambda index: self._move(index, self.active_list, self.inactive_list)
        )
        self.load_order_picker.currentIndexChanged.connect(self._on_load_order_picker_changed)
        self.new_button.clicked.connect(lambda: self._new_load_order())
        self.copy_button.clicked.connect(lambda: self._copy_to_new_load_order())
        self.sort_button.clicked.connect(lambda: self._sort())
        self.import_button.clicked.connect(lambda: self._show_action_menu(self.import_button, self._import_menu_items()))
        self.export_button.clicked.connect(lambda: self._show_action_menu(self.export_button, self._export_menu_items()))
        self.save_button.clicked.connect(lambda: self._save_load_order())
        self.sync_button.clicked.connect(lambda: self._sync_to_steam())
        self.push_button.clicked.connect(lambda: self._push())
        self.run_button.clicked.connect(lambda: self._run())
        self.scan_issues_button.clicked.connect(lambda: self._show_scan_issues())
        self.issues_button.clicked.connect(lambda: self._show_validation())  # unscoped (App.jsx setIssuesOpen({}))
        self.download_bar.toggled.connect(lambda: self._toggle_download_pause())

    def _load_order_dir(self) -> Path | None:
        """The open load order's own folder (load-orders/<slug>), else None."""
        if self.current_load_order is None:
            return None
        return load_orders.load_orders_root(self.app_root) / self.current_load_order

    def _apply_load_order_link(self) -> None:
        """Paths: Load order - enabled/tooltip follow current_load_order only
        (not the game path: the folder lives under app_root). Called at both
        places current_load_order is assigned."""
        path = self._load_order_dir()
        self.load_order_link.setEnabled(path is not None)
        self.load_order_link.setToolTip(str(path) if path else "")

    @staticmethod
    def _open_folder(path: Path) -> None:
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        log(f"open folder {path}: {'opened' if opened else 'FAILED (openUrl returned false)'}")

    def _pane_name(self, pane: ModListView) -> str:
        return "Active" if pane is self.active_list else "Inactive"

    def _warn(self, title: str, message: str, parent: QWidget | None = None) -> None:
        """QMessageBox.warning, logged too - so a failure nobody saw on screen
        still shows up in volt.log. parent: a dialog showing the failure (the
        Rules window), so the box sits over it; else this screen."""
        log(f"warning shown: {title}: {message}")
        QMessageBox.warning(parent if parent is not None else self, title, message)

    def _notice(self, title: str, message: str) -> None:
        """A success notice (_Notice): non-modal, silent, closes itself after
        NOTICE_MS. Logged like _warn. Replaces any notice still showing."""
        log(f"info shown: {title}: {message}")
        for old in self.findChildren(_Notice):
            old.close()
        notice = _Notice(title, message, self)
        self._place_notice(notice)
        notice.show()

    def _place_notice(self, notice: _Notice) -> None:
        """Bottom-center, above everything else (clear of the Push/Run buttons
        at the bottom right)."""
        notice.adjustSize()
        notice.move((self.width() - notice.width()) // 2, self.height() - notice.height() - NOTICE_BOTTOM)
        notice.raise_()

    def _confirm(self, title: str, message: str, *, confirm_label: str) -> bool:
        """A question box with `confirm_label` / Cancel (the confirm button is
        the default, Esc = Cancel), logged like _warn. True if confirmed."""
        box = QMessageBox(QMessageBox.Icon.Question, title, message, QMessageBox.StandardButton.Cancel, self)
        confirm = box.addButton(confirm_label, QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(confirm)  # Enter confirms (user decision 2026-09-29)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)  # Esc still cancels
        box.exec()
        confirmed = box.clickedButton() is confirm
        log(f"confirm shown: {title}: {message} -> {confirm_label if confirmed else 'Cancel'}")
        return confirmed

    def _confirm_sync(self) -> bool:
        """Sync to Steam's heads-up before a real sync starts (never for a
        refused / nothing-to-sync click): what to expect, a "Don't ask me
        again" checkbox, Cancel (Esc) / Sync (the default). True if Sync
        was clicked; Sync with the box ticked stores skip_sync_confirm, so
        _sync_to_steam skips this from then on. Cancel stores nothing, ticked
        or not. Logged like _confirm."""
        # ponytail: a hand-built one-off for this one call site, not a reusable
        # "confirm with a checkbox" helper - nothing else needs one yet; lift it
        # out next to _confirm if a second caller shows up.
        dialog = QDialog(self)
        dialog.setObjectName("syncConfirm")
        dialog.setWindowTitle("Sync to Steam")
        layout = QVBoxLayout(dialog)  # .modal: padding 16px, gap 10px (as CollectionDialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel("Sync to Steam")
        title.setProperty("role", "modal-title")
        layout.addWidget(title)
        for line in SYNC_CONFIRM_LINES:
            label = QLabel("\u2022 " + line)
            label.setWordWrap(True)
            layout.addWidget(label)
        dont_ask = QCheckBox("Don't ask me again")
        layout.addWidget(dont_ask)
        buttons = QHBoxLayout()  # .button-row.end: right-aligned, 8px apart
        buttons.setSpacing(8)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        buttons.addWidget(cancel)
        sync = QPushButton("Sync")
        sync.setProperty("variant", "primary")
        sync.setDefault(True)  # Enter = Sync, like _confirm; Esc rejects (QDialog default)
        sync.clicked.connect(dialog.accept)
        buttons.addWidget(sync)
        layout.addLayout(buttons)
        dialog.setFixedWidth(min(420, self.window().width() - 32))
        confirmed = dialog.exec() == QDialog.DialogCode.Accepted
        skip = confirmed and dont_ask.isChecked()
        dialog.deleteLater()  # a child of the screen: don't keep one per Sync click
        log(
            f"sync confirm shown -> {'Sync' if confirmed else 'Cancel'}"
            f" (don't ask again: {'ticked' if dont_ask.isChecked() else 'not ticked'}"
            f"{', stored' if skip else ''})"
        )
        if skip:
            self._settings.update({"skip_sync_confirm": True})
        return confirmed

    def _confirm_discard(self) -> bool:
        """True if there's nothing unsaved, or the user agrees to lose it."""
        return not self._dirty() or self._confirm(
            "Unsaved changes", "Discard unsaved changes to the current list?", confirm_label="Discard changes"
        )

    # ---- mods: scan, select, move ----
    def rescan(self) -> None:
        """Rescan button: re-reads the mods, keeping the on-screen Active list
        (App.jsx reloadForPaths) - unsaved edits, baseline and undo survive."""
        if self._scan():
            self._show_lists(self.active_list.mod_ids())
            self._apply_load_order_state()  # a pending id resolving to its now-installed mod can change dirty

    def _scan(self) -> bool:
        """Scans the mod roots into self._mods/_order. False if a root was unreadable."""
        # ponytail: synchronous scan on the GUI thread - the window freezes for
        # the walk + About.xml parses; a big Workshop folder could make that
        # noticeable. Move it to a QThread/QRunnable if that's ever reported.
        roots = paths.mod_roots(self.game_dir)
        log("rescan: roots " + ", ".join(f"{r['source']}={r['dir']}" for r in roots))
        try:
            result = mods.scan_mod_roots(roots)
        except OSError as err:  # an unreadable root (scan_dir re-raises)
            self._warn("Rescan failed", str(err))
            return False
        log(f"rescan: {len(result['mods'])} mods, {len(result['problems'])} scan problems")
        for problem in result["problems"]:
            log(f"rescan problem: {problem.get('kind', '?')} at {problem.get('path')}: {clip(problem.get('message'))}")
        # App.jsx scanFor: ignored paths never reach the window, this scan or later ones.
        ignored = set(self._settings.get()["ignored_scan_issues"] or [])
        self._scan_problems = [p for p in result["problems"] if str(p["path"]) not in ignored]
        hidden = len(result["problems"]) - len(self._scan_problems)
        if hidden:
            log(f"rescan: {hidden} scan problems hidden (ignored in settings)")
        self._update_scan_issues_button()
        self._mods = {m["id"]: m for m in result["mods"]}
        self._order = {m["id"]: i for i, m in enumerate(result["mods"])}
        return True

    def _mod_display_name(self, mod_id: str) -> str:
        """A pane row's text (ModListModel's display_name). A not-found row:
        its Workshop title when known (ModList.jsx `title || id`), else the id."""
        m = self._mods.get(mod_id)
        if m:
            return m["name"] or m["folder"]
        return self._workshop_title(mod_id) or mod_id

    def _workshop_title(self, mod_id: str) -> str | None:
        """A not-found Workshop-id row's known title (App.jsx
        workshopTitles.get(notFoundWorkshopId(id))), else None."""
        wid = mod_list_io.not_found_workshop_id(mod_id, self._mods)
        return self.workshop_titles.get(wid) if wid else None

    def _apply_current_load_order_to_panes(self) -> None:
        """Shows the current load order's saved Active list and makes it the
        baseline (unsaved edits and undo are dropped)."""
        active: list[str] = []
        if self.current_load_order:
            try:
                active = load_orders.load_load_order(self.app_root, self.current_load_order)["active"]
            except (OSError, ValueError) as err:
                self._warn("Couldn't load load order", str(err))
        self._show_lists(active)
        self._reset_baseline()

    def _show_lists(self, active: list[str]) -> None:
        """App.jsx showLists (lists.js reconcileLists): Active = every id of
        `active`, in order - an id that didn't scan (a removed / renamed /
        never-installed mod, or a pending Workshop id) stays as a "not
        found" row, and a "workshop:<id>" sentinel whose item scans now is
        swapped for that mod's id (mod_list_io.reconcile_active); Inactive =
        every other scanned mod, in scan (name) order - a not-found id never
        goes there. A repopulate, not an edit."""
        given = list(active)
        active = mod_list_io.reconcile_active(given, self._mods)
        not_found = [i for i in active if i not in self._mods]
        resolved = [i for i in given if i.startswith("workshop:") and i not in active]
        if not_found:
            log(
                f"load order {self.current_load_order}: {len(not_found)} active ids didn't scan, "
                f"kept as not-found rows: {clip(not_found)}"
            )
        if resolved:
            log(f"load order {self.current_load_order}: {len(resolved)} pending Workshop ids are installed now: {clip(resolved)}")
        active_set = set(active)
        self.active_list.set_mod_ids([])
        self.inactive_list.set_mod_ids(
            i for i in sorted(self._mods, key=self._order.__getitem__) if i not in active_set
        )
        self.active_list.set_mod_ids(active)
        log(
            f"panes rebuilt for load order {self.current_load_order}: "
            f"{len(self.active_list.mod_ids())} active, {len(self.inactive_list.mod_ids())} inactive"
        )
        self._show_details(None)
        self._highlight_dependencies(None)

    def _undo_shortcut(self) -> None:
        """Ctrl+Z: exactly the undo button's click, and only while it could be
        clicked - shown (this screen showing, something to undo) and enabled
        (not busy). A focused text field keeps its own Ctrl+Z (Qt hands it
        the key first - ShortcutOverride - and this check covers the rest),
        and a list drag under way ignores it (the button can't be clicked
        mid-drag either)."""
        button = self.undo_button
        if (not button.isVisible() or not button.isEnabled()
                or isinstance(QApplication.focusWidget(), (QLineEdit, QTextEdit, QPlainTextEdit))
                or self.active_list._drag_state is not None or self.inactive_list._drag_state is not None):
            return
        log("undo: Ctrl+Z")
        button.click()

    def _undo(self) -> None:
        """Restores the most recent pre-change Active list. Not itself undoable; no redo."""
        if not self._history:
            log("undo: nothing to undo")
            return
        log(f"undo: restoring the Active list from before the last change ({len(self._history) - 1} steps left)")
        self._show_lists(self._history.pop())
        self._apply_load_order_state()

    # ---- Sort (App.jsx onSort) ----
    def _sort(self) -> None:
        """Sort button: reorders the Active list by the user's own rules
        (settings user_rules), community rules, each mod's own About.xml
        loadAfter/loadBefore and modDependencies (sort.py auto_sort_active).
        Only changes the on-screen list - Save to keep it.
        A reorder like any drag: marks dirty and is undoable (App.jsx reorder:
        no-op if the order didn't change, else push history, then set)."""
        before = self.active_list.mod_ids()
        log(f"sort: clicked, {len(before)} active mods")
        # ponytail: normally the startup background lookup (__init__) has
        # already loaded the community rules and this returns at once. If it's
        # still in flight, this waits for it here on the GUI thread (the
        # community_rules lock) and the window doesn't repaint meanwhile - up
        # to community_rules.TIMEOUT_S on a dead network.
        self.sort_button.setEnabled(False)
        self.sort_button.repaint()  # show it disabled now: no event loop until the fetch returns
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            try:
                loaded = community_rules.get_community_rules(self.app_root)
            finally:
                QApplication.restoreOverrideCursor()
            rules = loaded["rules"]
            log(f"sort: community rules source={loaded['source']}, {len(rules)} mods with rules")
            user_rules = self._settings.get()["user_rules"] or []
            log(f"sort: {len(user_rules)} user rule entries")
            r = sort.auto_sort_active(before, self._mods, rules, user_rules)
            by_source = {"user": 0, "community": 0, "about": 0, "dependency": 0}
            for rule in r["rules"]:
                by_source[rule["source"]] = by_source.get(rule["source"], 0) + 1
            conflicts = r["dependency_conflicts"]
            log(
                f"sort: {len(r['rules'])} rules among active mods ({by_source['user']} user, "
                f"{by_source['community']} community, {by_source['about']} About.xml, "
                f"{by_source['dependency']} dependency); "
                f"{r['user_overridden']} community/About.xml/dependency rules overridden by user rules; "
                f"{r['overridden']} About.xml rules overridden by community rules; "
                f"{r['unresolved']} rules dropped to break cycles; {len(conflicts)} dependency orderings not applied"
            )
            for c in conflicts:
                log(
                    f"sort: dependency ordering not applied: {c['dependent']} needs {c['dependency']}, "
                    f"but a {'/'.join(c['sources'])} rule says {c['dependent']} loads first"
                )
            after = r["active"]
            if after == before:
                log("sort: order unchanged (already sorted), nothing to undo")
            else:
                moved = sum(1 for a, b in zip(before, after) if a != b)
                log(f"sort: {moved} of {len(after)} positions changed; before: {clip(before)}")
                log(f"sort: after: {clip(after)}")
                selected = self.active_list.selected_mod_id()
                self._history.append(before)
                self.active_list.set_mod_ids(after)  # a reset: not recorded by the row signals, pushed above
                if selected is not None:
                    # Selection is by id in App.jsx, so it survives a reorder; select
                    # without making it current, which would scroll to it.
                    self.active_list.selectionModel().select(
                        self.active_list.mod_model.index(after.index(selected)),
                        QItemSelectionModel.SelectionFlag.ClearAndSelect,
                    )
            self._notice("Sort", self._sort_message(r))
        finally:
            self._apply_load_order_state()  # dirty/undo, and re-enables Sort

    @staticmethod
    def _sort_message(r: dict) -> str:
        """App.jsx onSort's status text, one sentence per line (it's a notice
        here, not the status bar)."""
        u, o, d = r["unresolved"], r["overridden"], len(r["dependency_conflicts"])
        uo = r["user_overridden"]
        lines = [f"Sorted {len(r['active'])} active mods."]
        if u:
            lines.append(
                f"{u} load order rule{'' if u == 1 else 's'} could not be satisfied (circular) "
                f"and {'was' if u == 1 else 'were'} skipped."
            )
        if o:
            lines.append(f"{o} About.xml rule{'' if o == 1 else 's'} overridden by community sorting rules.")
        if uo:
            lines.append(
                f"{uo} community, About.xml or dependency rule{'' if uo == 1 else 's'} "
                "overridden by your own sorting rules."
            )
        if d:
            lines.append(
                f"{d} dependency ordering{'' if d == 1 else 's'} not applied: "
                "a community or About.xml load order rule says the opposite."
            )
        return "\n".join(lines)

    # ---- Import / Export (App.jsx "import / export"; mod_list_io.py) ----
    def _import_menu_items(self) -> list[tuple]:
        """Import...'s entries (App.jsx menuItems, kind 'import'), in order."""
        return [
            ("From clipboard", self._import_clipboard),
            ("From RimPy .xml file...", lambda: self._import_file("rimpy-xml")),
            ("From rentry.co...", self._import_rentry),
            ("Read from save...", lambda: self._import_file("save")),
            ("From Steam Workshop...", self._import_collection),
        ]

    def _export_menu_items(self) -> list[tuple]:
        """Export...'s entries (App.jsx menuItems, kind 'export'), in order."""
        return [
            ("Rentry (share link)", self._publish_rentry),
            ("Clipboard (RimSort)", self._export_rim_sort),
            (".xml (RimPy)", self._export_rim_py),
        ]

    def _show_action_menu(self, button: QPushButton, items: list[tuple]) -> None:
        """Import... / Export...: a native menu of (label, handler) entries,
        dropped 4px below the button (App.jsx openMenu)."""
        log(f"{button.text()} menu opened")
        menu = QMenu(button)
        for label, fn in items:
            menu.addAction(label).triggered.connect(lambda _checked=False, fn=fn: fn())
        menu.exec(button.mapToGlobal(QPoint(0, button.height() + 4)))
        menu.deleteLater()

    @staticmethod
    def _busy(fn):
        """fn() under a busy cursor: a file read or a rentry.co call blocks the
        GUI thread until it returns.
        ponytail: no worker thread - the window doesn't repaint meanwhile, up
        to mod_list_io.RENTRY_TIMEOUT_S on a dead network (same ceiling as
        _sort's community-rules wait). Move to a thread if that's ever reported."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return fn()
        finally:
            QApplication.restoreOverrideCursor()

    def _import(self, source: str, read) -> bool:
        """App.jsx run(...) around an importer: read() returns the raw ids (a
        parse, a file read, a network fetch); they replace the Active list
        (_apply_import). False (after a warning with the reason) if it failed."""
        try:
            raw = self._busy(read)
        except (OSError, ValueError) as err:
            log(f"import from {source} failed: {err!r}")
            self._warn("Import failed", str(err))
            return False
        self._apply_import(raw, source)
        return True

    def _apply_import(
        self, raw_ids: list[str], source: str, *, keep_pending: bool = False, official: list[str] = ()
    ) -> list[str] | None:
        """App.jsx applyImport: the imported list replaces the Active list like
        loading a load order, but as one undoable, unsaved edit - baseline
        untouched (_sort's pattern: one history push, then a repopulate).
        "workshop:<id>" placeholders (a rentry.co page's Workshop-link-only
        entries) become the installed mod with that Workshop id, else are
        skipped and counted - or, with keep_pending (collection import), kept
        as pending rows and counted. official (collection import): official
        ids put at the top of the list too, but not counted as coming from
        `source`. Any other id that doesn't scan is imported all the same, as
        a "not found" row (_show_lists keeps it), and counted in the message
        ("kept as-is"); only the skipped placeholders make it a warning
        (App.jsx: skipped ? 'warn' : 'info'). Returns the new Active list,
        None when nothing was imported."""
        official = list(official)
        r = mod_list_io.resolve_workshop_placeholders([*official, *raw_ids], self._mods, keep_unmatched=keep_pending)
        ids, skipped, pending = r["ids"], r["skipped"], r["pending"]
        not_found = [i for i in ids if i not in self._mods]
        log(
            f"import from {source}: {len(raw_ids)} ids read{f' (+ {len(official)} official)' if official else ''}, "
            f"{len(ids) - len(not_found)} found, {len(not_found)} not found "
            f"(kept as not-found rows: {clip(not_found)}), {pending} pending Workshop rows, "
            f"{skipped} Workshop placeholders not installed (skipped)"
        )
        if len(ids) == len(official):
            self._warn(
                "Import",
                f"None of the {skipped} Workshop mods on the page are installed, so nothing was imported. "
                "Subscribe to them on Steam, rescan, then re-import.",
            )
            return None
        self._history.append(self.active_list.mod_ids())
        self._show_lists(ids)  # a repopulate (model reset): not recorded by the row signals, pushed above
        self._apply_load_order_state()  # dirty/undo
        n_not_found = len(not_found) - pending  # App.jsx notFound: not-found rows that aren't pending ones
        one = pending == 1
        message = (
            f"Imported {len(ids) - len(official)} mods from {source}"
            + (
                f"; {sort.official_phrase(official)} {'is' if len(official) == 1 else 'are'} active too."
                if official else "."
            )
            + (
                f" {n_not_found} of them weren't found in the game's Data or Mods folder "
                "(or the Steam Workshop folder); they're kept as-is."
                if n_not_found else ""
            )
            + (
                f" {pending} {'is' if one else 'are'}n't installed yet and {'is' if one else 'are'} shown as pending; "
                f"Subscribe downloads {'it' if one else 'them'}."
                if pending else ""
            )
            + (
                f" {skipped} Workshop mods on the page aren't installed and were skipped; "
                "subscribe to them on Steam, rescan, then re-import."
                if skipped else ""
            )
        )
        if skipped:
            self._warn("Import", message)
        else:
            self._notice("Import", message)
        return ids

    def _import_clipboard(self) -> None:
        if not self._confirm_discard():
            log("import from the clipboard: cancelled at the discard-changes prompt")
            return
        text = QGuiApplication.clipboard().text()
        log(f"import from the clipboard: {len(text)} chars")
        self._import("the clipboard", lambda: mod_list_io.detect_and_parse(text))

    def _import_file(self, kind: str) -> None:
        """From RimPy .xml file... (kind "rimpy-xml") / Read from save... ("save"):
        main.js modList:importFile. A save's picker starts in RimWorld's Saves
        folder (next to Config) when the config folder is known."""
        save = kind == "save"
        what = "the save" if save else "the RimPy file"
        if not self._confirm_discard():
            log(f"import from {what}: cancelled at the discard-changes prompt")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Read the mod list from a RimWorld save" if save else "Import a RimPy mod list (.xml)",
            str(self.config_dir.parent / "Saves") if save and self.config_dir else "",
            "RimWorld saves (*.rws)" if save else "RimPy mod list (*.xml)",
        )
        if not path:
            log(f"import from {what}: file picker cancelled")
            return
        log(f"import from {what}: {path}")
        if save:
            self._import(what, lambda: mod_list_io.read_save_mod_list(path))
        else:
            self._import(what, lambda: mod_list_io.parse_rim_py_xml_text(read_text(path)))

    def _import_rentry(self) -> None:
        """From rentry.co...: prompts for the page's URL. App.jsx keeps its
        prompt open with the error on a failed fetch; here the error box
        shows, then the same prompt comes back with the URL still in it, until
        an import works or the prompt is cancelled."""
        if not self._confirm_discard():
            log("import from rentry.co: cancelled at the discard-changes prompt")
            return
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Import from rentry.co")
        dialog.setLabelText("Paste the rentry.co page's URL \u2014 the one you'd share, or its /edit link both work.")
        dialog.setOkButtonText("Import")
        app_version = version("volt-py")
        while dialog.exec():
            url = dialog.textValue()
            log(f"import from rentry.co: {url!r}")
            if self._import(
                "rentry.co", lambda: mod_list_io.parse_rentry_page_html(mod_list_io.fetch_rentry_page(url, app_version))
            ):
                break
        else:
            log("import from rentry.co: prompt cancelled")
        dialog.deleteLater()

    # ---- From Steam Workshop... (App.jsx onImportCollection / onCollectionImport) ----
    def _import_collection(self) -> None:
        """From Steam Workshop...: the dialog (screens/collection_dialog.py)
        resolves the collection and matches it against the scan itself; it
        hands back the ordered ids (packageIds / "workshop:<id>" placeholders)
        plus each item's title. No discard prompt here: only a collection's
        Replace list / New load order... swaps the list, so the dialog's gate
        (_may_import_collection) asks then, before the dialog closes."""
        log("import from Steam Workshop: dialog opened")
        app_version = version("volt-py")
        dialog = CollectionDialog(
            self._mods,
            lambda query: steam_web_api.resolve_collection(query, app_version),
            self._may_import_collection,
            parent=self,
        )
        if dialog.exec() and dialog.payload is not None:
            self._on_collection_import(dialog.payload)
        else:
            log("import from Steam Workshop: dialog cancelled")
        dialog.deleteLater()

    def _may_import_collection(self, r: dict) -> bool:
        """The dialog's gate: 'add' appends (nothing is lost, no prompt), a
        single mod too; 'replace' and 'new' swap the whole list, so they ask
        to discard unsaved changes first - declining keeps the dialog open."""
        if not r.get("single") and r["mode"] != "add" and not self._confirm_discard():
            log(f"import from Steam Workshop: {r['mode']} cancelled at the discard-changes prompt")
            return False
        return True

    def _on_collection_import(self, r: dict) -> None:
        """App.jsx onCollectionImport. A single mod's link: appended to the
        current Active list (activate), not a list replacement; not found yet
        -> the same pending row + auto-download. A collection: 'add' appends
        as one undo step (ids already active stay where they are), 'replace'
        and 'new' go through _apply_import; 'new' then names a new load order
        from the screen, so the next Save can't overwrite the one that was
        open - cancelling that puts the list and the undo stack back. Core +
        DLC: a Workshop collection can only hold Workshop items, so every
        scanned official id (sort.official_ids) is made active too, whatever
        the mode - kept apart from r["ids"] so no message counts them as
        coming from the collection. Every pending item is fetched right away
        (_acquire_pending)."""
        titles = {it["id"]: it["title"] for it in r["items"] if it.get("title")}
        self.workshop_titles.update(titles)  # App.jsx setWorkshopTitles
        active = self.active_list.mod_ids()
        if r.get("single"):
            mod_id = r["ids"][0]
            name = f'"{r["title"]}"' if r["title"] else f"Workshop item {r['collection_id']}"
            pending = bool(mod_list_io.not_found_workshop_id(mod_id, self._mods))
            if mod_id in active:
                log(f"import from Steam Workshop: single item {r['collection_id']} -> {mod_id} is already active")
                self._notice("Import", f"{name} is already in the active list.")
            else:
                log(f"import from Steam Workshop: single item {r['collection_id']} -> {mod_id} appended"
                    f"{' as a pending row' if pending else ''}")
                self._edit_active(active, [*active, mod_id])
                self._notice(
                    "Import",
                    f"Added {name} to the end of the active list"
                    f"{' as pending; Subscribe downloads it' if pending else ''}.",
                )
            self._refresh_workshop_rows()
            if pending:
                self._acquire_pending([mod_id])
            return
        source = f'the Steam collection "{r["title"]}"' if r["title"] else f"Steam collection {r['collection_id']}"
        before = list(active)  # New load order...: cancelling the name prompt puts this back
        all_official = sort.official_ids(self._mods)
        official = [i for i in all_official if i not in r["ids"]]
        if r["mode"] == "add":
            uniq = list(dict.fromkeys(r["ids"]))
            added = [i for i in uniq if i not in active]
            already = len(uniq) - len(added)
            pending = sum(1 for i in added if mod_list_io.not_found_workshop_id(i, self._mods))
            # Missing official ids go at the top, never after the mods: right
            # after the list's leading run of official ids, or first if the
            # first official id in load order (Core) is itself missing.
            added_official = [i for i in official if i not in active]
            log(
                f"import from Steam Workshop: add {len(uniq)} ids from {source}: {len(added)} new "
                f"({pending} pending), {already} already active, {len(added_official)} official ids added: "
                f"{clip(added_official)}"
            )
            if added or added_official:
                at = next((n for n, i in enumerate(active) if i not in all_official), len(active))
                if added_official and added_official[0] == all_official[0]:
                    at = 0
                self._edit_active(active, [*active[:at], *added_official, *active[at:], *added])
            one_already, one_pending, one_official = already == 1, pending == 1, len(added_official) == 1
            if added:
                message = f"Added {len(added)} mod{'' if len(added) == 1 else 's'} from {source} to the end of the active list."
            elif added_official:
                message = f"No mods added from {source}: all {len(uniq)} are already in the active list."
            else:
                message = f"Nothing added: all {len(uniq)} mods from {source} are already in the active list."
            if added and already:
                message += (
                    f" {already} {'was' if one_already else 'were'} already active and stayed where "
                    f"{'it was' if one_already else 'they were'}."
                )
            if pending:
                message += (
                    f" {pending} {'is' if one_pending else 'are'}n't installed yet and {'is' if one_pending else 'are'} "
                    f"shown as pending; Subscribe downloads {'it' if one_pending else 'them'}."
                )
            if added_official:
                message += (
                    f" {sort.official_phrase(added_official)} {'was' if one_official else 'were'} also made active, "
                    "at the top of the list (a Steam collection can't include official content)."
                )
            self._notice("Import", message)
            self._refresh_workshop_rows()
            if pending:
                self._acquire_pending(added)
            return
        log(f"import from Steam Workshop: {r['mode']} with {len(r['ids'])} ids from {source} (+ {len(official)} official)")
        ids = self._apply_import(r["ids"], source, keep_pending=True, official=official)
        self._refresh_workshop_rows()
        # Every pending item is fetched right away, by the mode in effect: one
        # SteamCMD download call (or, in Steam client mode, the gate message).
        if ids:
            self._acquire_pending(ids)
        # New load order...: the collection is on screen now; the new load order saves exactly that.
        if ids and r["mode"] == "new":
            plus = f" (plus {sort.official_phrase(official)})" if official else ""
            created = self._create_load_order(
                "New load order from Steam Workshop",
                active=self.active_list.mod_ids(),
                inactive=self.inactive_list.mod_ids(),
                message=f"Save the {len(ids) - len(official)} mods imported from {source}{plus} as a new load order?"
                + (" The load order you had open stays as it was last saved." if self.current_load_order else ""),
            )
            if not created:
                # Undo the import too, so a later Save can't write the collection
                # into the load order still open (App.jsx revertOnCancel).
                log("import from Steam Workshop: new load order not created, reverting the import")
                self._history.pop()  # _apply_import's undo entry
                self._show_lists(before)
                self._apply_load_order_state()

    def _edit_active(self, before: list[str], after: list[str]) -> None:
        """One undoable edit of the whole Active list (App.jsx pushHistory +
        setActive / setInactive as one step; _sort's pattern): a history push,
        then a repopulate - a model reset, not recorded by the row signals -
        keeping the selected row selected (by id, as App.jsx does)."""
        selected = self.active_list.selected_mod_id()
        self._history.append(list(before))
        self._show_lists(after)
        now = self.active_list.mod_ids()
        if selected is not None and selected in now:
            # Select without making it current, which would scroll to it.
            self.active_list.selectionModel().select(
                self.active_list.mod_model.index(now.index(selected)),
                QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
        self._apply_load_order_state()

    def _publish_rentry(self) -> None:
        """Rentry (share link): publishes the Active list's rentry.co page and
        copies its URL. Pending "workshop:" / "folder:" ids are left out
        (ids.exportable_ids), as for every export."""
        ids = exportable_ids(self.active_list.mod_ids())
        app_version = version("volt-py")
        text = mod_list_io.build_rentry_markdown(ids, self._mods, app_version, self._game_version)
        log(f"export: publishing {len(ids)} mods to rentry.co ({len(text)} chars)")
        try:
            url = self._busy(lambda: mod_list_io.publish_rentry(text, app_version))
        except (OSError, ValueError) as err:
            log(f"export to rentry.co failed: {err!r}")
            self._warn("Export failed", str(err))
            return
        QGuiApplication.clipboard().setText(url)
        log(f"export: published to {url}, URL copied to clipboard")
        self._notice("Export", f"Published to rentry.co: {url} (copied to clipboard).")

    def _export_rim_sort(self) -> None:
        """Clipboard (RimSort): the Active list as RimSort's "Name [id][url]" text."""
        ids = exportable_ids(self.active_list.mod_ids())
        text = mod_list_io.build_rim_sort_text(ids, self._mods, version("volt-py"), self._game_version)
        QGuiApplication.clipboard().setText(text)
        log(f"export: copied {len(ids)} mods to the clipboard in RimSort format ({len(text)} chars)")
        self._notice("Export", f"Copied {len(ids)} mods to the clipboard in RimSort/rentry.co format.")

    def _export_rim_py(self) -> None:
        """.xml (RimPy): main.js modList:exportFile - a fresh ModsConfig.xml-shaped file."""
        ids = exportable_ids(self.active_list.mod_ids())
        path, _ = QFileDialog.getSaveFileName(
            self, "Export the active list as a RimPy mod list", "VOLT-export.xml", "RimPy mod list (*.xml)"
        )
        if not path:
            log("export to RimPy .xml: file picker cancelled")
            return
        path = Path(path)
        eol = "\r\n" if sys.platform == "win32" else "\n"
        try:
            write_text_atomic(path, mods_config.fresh_mods_config(ids, self._game_version, eol))
        except OSError as err:
            log(f"export to RimPy .xml {path} failed: {err!r}")
            self._warn("Export failed", str(err))
            return
        log(f"export: wrote {len(ids)} mods to {path}")
        self._notice("Export", f"Exported {len(ids)} mods to {path}.")

    # ---- load orders: picker, New / Copy, Delete, Save, Push ----
    def _reload_load_order_picker(self, select_slug: str | None = None) -> None:
        all_entries = load_orders.list_load_orders(self.app_root)
        for e in all_entries:
            if "error" in e:
                log(f"load-order picker: skipping unreadable load order {e['slug']}: {e['error']}")
        entries = [e for e in all_entries if "error" not in e]
        slugs = [e["slug"] for e in entries]
        last = self._settings.get()["last_load_order"]
        if select_slug in slugs:
            slug = select_slug
        elif last in slugs:
            slug = last
        else:
            slug = slugs[0] if slugs else None
        picker = self.load_order_picker
        picker.blockSignals(True)
        picker.clear()
        for i, e in enumerate(entries):
            picker.addItem(e["name"])
            picker.setItemData(i, e["slug"])
        picker.setCurrentIndex(slugs.index(slug) if slug else -1)
        picker.blockSignals(False)
        self.current_load_order = slug
        self._apply_load_order_link()
        log(
            f"load-order picker reloaded: {len(entries)} load orders, current={slug} "
            f"(requested={select_slug}, last saved={last})"
        )

    def _on_load_order_picker_changed(self, index: int) -> None:
        slug = self.load_order_picker.itemData(index)
        if slug == self.current_load_order:
            return
        if not self._confirm_discard():
            log(f"load order switch to {slug} cancelled: keeping unsaved changes in {self.current_load_order}")
            picker = self.load_order_picker
            picker.blockSignals(True)
            picker.setCurrentIndex(picker.findData(self.current_load_order))
            picker.blockSignals(False)
            return
        log(f"load order selected: {self.current_load_order} -> {slug}")
        self.current_load_order = slug
        self._apply_load_order_link()
        self._settings.update({"last_load_order": slug})
        self._apply_current_load_order_to_panes()
        self._apply_load_order_state()

    def _show_load_order_menu(self, pos: QPoint) -> None:
        """Picker right-click: Delete the selected (= open) load order. No menu
        with nothing selected; a disabled picker gets no right-click at all."""
        picker = self.load_order_picker
        slug, name = picker.currentData(), picker.currentText()
        if not slug:
            return
        menu = QMenu(picker)
        menu.addAction(f'Delete "{name}"...').triggered.connect(lambda: self._delete_load_order(slug, name))
        menu.exec(picker.mapToGlobal(pos))
        menu.deleteLater()

    def _delete_load_order(self, slug: str, name: str) -> None:
        """Confirms, deletes the load order's folder, then reloads the picker.
        If the open one is gone, the picker's own fallback (last used, else
        first, else none) becomes current and fills the panes - the delete
        confirm already covers losing its unsaved changes. Otherwise the open
        load order and its unsaved edits are left alone."""
        if not self._confirm(
            "Delete load order",
            f'Delete "{name}"? Its saved mod list is removed from disk. This can\'t be undone.\n\n'
            "Your mods themselves aren't touched.",
            confirm_label="Delete",
        ):
            log(f"delete load order {slug} ({name!r}): cancelled")
            return
        try:
            load_orders.delete_load_order(self.app_root, slug)
            log(f"deleted load order {slug} ({name!r})")
        except (OSError, ValueError) as err:  # e.g. a locked file: part of the folder may be gone
            log(f"delete load order {slug} ({name!r}) failed: {err!r}")
            self._warn("Couldn't delete load order", str(err))
        # Reload either way, so the picker matches what's actually left on disk.
        old = self.current_load_order
        self._reload_load_order_picker(select_slug=old)
        if self.current_load_order == old:
            self._apply_load_order_state()
            return
        self._settings.update({"last_load_order": self.current_load_order})
        self._apply_current_load_order_to_panes()

    def _pane_ids(self, pane: ModListView) -> list[str]:
        return pane.mod_ids()

    def _create_load_order(self, title: str, active=None, inactive=None, message: str | None = None) -> bool:
        """Prompts for a name (under `message`, when given - NameDialog.jsx's
        text above the input), creates the load order and makes it current.
        False if cancelled/failed."""
        name, ok = QInputDialog.getText(self, title, f"{message}\n\nName:" if message else "Name:")
        if not ok or not name.strip():
            log(f"{title}: {'cancelled' if not ok else 'empty name entered'}, nothing created")
            return False
        counts = f"{len(active or [])} active, {len(inactive or [])} inactive"
        try:
            manifest = load_orders.create_load_order(self.app_root, name, active=active, inactive=inactive)
        except (OSError, ValueError) as err:
            log(f"{title}: create {name!r} ({counts}) failed")
            self._warn("Couldn't create load order", str(err))
            return False
        log(f"{title}: created {name!r} as slug {manifest['slug']} ({counts})")
        self._settings.update({"last_load_order": manifest["slug"]})
        self._reload_load_order_picker(select_slug=manifest["slug"])
        self._reset_baseline()  # Copy/Push: the panes now match what was just saved
        return True

    def _new_load_order(self) -> None:
        # Blank: every scanned mod lands in Inactive. (Electron pre-fills Core +
        # DLC in release order; that needs the unported Sort logic.)
        if not self._confirm_discard():
            log("New load order: cancelled at the discard-changes prompt")
            return
        if self._create_load_order("New load order"):
            self._apply_current_load_order_to_panes()

    def _copy_to_new_load_order(self) -> None:
        # The panes already show exactly what gets saved - no rebuild needed.
        self._create_load_order(
            "Copy to new load order",
            active=self._pane_ids(self.active_list),
            inactive=self._pane_ids(self.inactive_list),
        )

    def _save_load_order(self) -> None:
        active_ids = self._pane_ids(self.active_list)
        inactive_ids = self._pane_ids(self.inactive_list)
        counts = f"{len(active_ids)} active, {len(inactive_ids)} inactive"
        try:
            load_orders.save_load_order(
                self.app_root,
                self.current_load_order,
                active=active_ids,
                inactive=inactive_ids,
            )
        except (OSError, ValueError) as err:
            log(f"save load order {self.current_load_order} ({counts}) failed")
            self._warn("Save failed", str(err))
            return
        log(f"saved load order {self.current_load_order} ({counts})")
        self._reset_baseline()

    def _push(self) -> None:
        """Saves the panes into the current load order, then writes ModsConfig.xml."""
        if self.config_dir is None:
            log("push aborted: no config folder set")
            self._warn("Can't push", "No config folder set — can't write ModsConfig.xml.")
            return
        active_ids = self._pane_ids(self.active_list)
        inactive_ids = self._pane_ids(self.inactive_list)
        log(
            f"push: load order {self.current_load_order}, config_dir={self.config_dir}, "
            f"{len(active_ids)} active, {len(inactive_ids)} inactive"
        )
        if self._dirty() and not self._confirm(
            "Save before pushing",
            "This load order has unsaved changes. Push saves them into the load order first, then writes "
            f"its active list ({len(active_ids)} mods, in this order) to the game's ModsConfig.xml.",
            confirm_label="Save & Push",
        ):
            log("push cancelled at the save-before-pushing prompt")
            return
        if self.current_load_order is None and not self._create_load_order(
            "New load order", active=active_ids, inactive=inactive_ids
        ):
            log("push aborted: no current load order, and none was created")
            return
        try:
            load_orders.save_load_order(self.app_root, self.current_load_order, active=active_ids, inactive=inactive_ids)
            self._reset_baseline()  # saved - stays so even if the ModsConfig.xml write fails
            result = mods_config.push_mods_config(
                self.config_dir,
                active_ids,
                game_version=paths.read_game_version(self.game_dir) if self.game_dir else None,
            )
        except (OSError, ValueError) as err:
            log(f"push failed during save/write of load order {self.current_load_order}")
            self._warn("Push failed", str(err))
            return
        log(
            f"push: wrote {result['count']} mods to {result['path']} "
            f"(skipped {result['skipped']} unwritable ids, backup={result['backup_path']})"
        )
        self.status_text.set_status_text(
            f"Pushed {result['count']} active mods to {result['path']}."
            + (f" Skipped {result['skipped']} without a packageId." if result["skipped"] else "")
        )

    # ---- scan issues ----
    def _update_scan_issues_button(self) -> None:
        """ActionsColumn.jsx: "N scan issue(s)", only while there are any."""
        n = len(self._scan_problems)
        self.scan_issues_button.setText(f"{n} scan issue{'' if n == 1 else 's'}")
        self.scan_issues_button.setVisible(n > 0)

    def _show_scan_issues(self) -> None:
        """The window looks up Steam Workshop titles itself for a duplicate-id
        pair with identical names (App.jsx passes steamAvailable): the keyless
        Web API, plus the Steam-client fallback while Steam is available."""
        log(f"scan issues window opened: {len(self._scan_problems)} issues")
        app_root, game_dir, steam, app_version = self.app_root, self.game_dir, self._steam_available, version("volt-py")

        def web_titles(ids: list[str]) -> list[dict]:
            return steam_web_api.get_published_file_details(ids, app_version)

        def client_item(wid: str) -> dict:
            return steam_client.workshop_item(app_root, game_dir, wid)

        ScanIssuesWindow(
            self._scan_problems, self._ignore_scan_issue, self,
            title_lookup=lambda wid: workshop_title(wid, steam, web_titles, client_item),
        ).exec()
        log(f"scan issues window closed: {len(self._scan_problems)} issues left")

    def _ignore_scan_issue(self, path: str) -> list[dict] | None:
        """Scan issues window's Ignore (App.jsx ignoreScanIssue): persists the
        path to ignored_scan_issues and drops it from the list. Returns the new
        list, or None if saving failed."""
        kinds = [p.get("kind") for p in self._scan_problems if str(p["path"]) == path]
        try:
            self._settings.set_scan_issue_ignored(path, True)
        except (OSError, ValueError) as err:
            log(f"scan issues: ignore {path} ({', '.join(map(str, kinds))}) FAILED: {err!r}")
            self._warn("Couldn't ignore scan issue", str(err))
            return None
        self._scan_problems = [p for p in self._scan_problems if str(p["path"]) != path]
        log(
            f"scan issues: ignored {path} ({', '.join(map(str, kinds))}), saved to settings; "
            f"{len(self._scan_problems)} issues left"
        )
        self._update_scan_issues_button()
        return self._scan_problems

    def _update_issues_button(self) -> None:
        """ActionsColumn.jsx's merged "⚠ N · ✕ M" button: live counts, shown
        only while either is nonzero."""
        warnings = sum(1 for i in self._validation_issues if i["severity"] == "warning")
        errors = len(self._validation_issues) - warnings
        self.issues_button.findChild(QLabel).setText(_issue_count_html(warnings, errors))
        self.issues_button.setVisible(warnings > 0 or errors > 0)

    def _show_validation(self, key: str | None = None, severity: str | None = None) -> None:
        """The Warnings and errors window: unscoped (the merged button), or
        on issue `key` (an Active row's issue icon; App.jsx showIssue) /
        the first issue of `severity`."""
        log(f"validation window opened: {len(self._validation_issues)} issues, key {key}, severity {severity}")
        ValidationWindow(
            self._validation_issues, self._mods, self, initial_key=key, initial_severity=severity
        ).exec()
        log("validation window closed")

    # ---- Run ----
    def _run(self) -> None:
        """Run (App.jsx onRun): launches the game. Never saves or pushes - with
        unsaved changes it asks first, and the game starts with whatever
        ModsConfig.xml was last pushed."""
        if self._dirty() and not self._confirm(
            "Unsaved load order changes",
            "The active list has unsaved changes. Run doesn't save or push them: "
            "RimWorld starts with the mod list last pushed to its ModsConfig.xml.",
            confirm_label="Run without saving",
        ):
            log("run cancelled at the unsaved-changes prompt (nothing saved or pushed)")
            return
        self._launch_game()

    def _launch_game(self) -> None:
        """App.jsx launchNow + main.js game:launch: the first GAME_EXES match
        directly in the game folder, opened via the OS (os.startfile)."""
        exe = paths.find_game_exe(self.game_dir)
        log(
            f"run: game_dir={self.game_dir}, exe={exe or 'none found'} (looked for {', '.join(paths.GAME_EXES)}), "
            f"load order {self.current_load_order}, unsaved changes: {'yes' if self._dirty() else 'none'}"
        )
        if exe is None:
            self._warn("Run failed", f"No RimWorld executable found in {self.game_dir or '(game folder not set)'}")
            return
        try:
            paths.open_path(exe)
        except OSError as err:
            log(f"run: the OS refused to open {exe}: {err!r}")
            self._warn("Run failed", str(err))
            return
        log(f"run: launched {exe}")
        self.status_text.set_status_text("Launching RimWorld...")

    def _on_selection_changed(self, source: ModListView, other: ModListView) -> None:
        mod_id = source.selected_mod_id()
        if mod_id is not None:
            log(f"selected {mod_id} in {self._pane_name(source)}")
            other.clearSelection()  # re-enters for `other`, which then does nothing
            self._show_details(mod_id)
            self._highlight_dependencies(mod_id)
        elif other.selected_mod_id() is None:
            log(f"selection cleared ({self._pane_name(source)})")
            self._show_details(None)
            self._highlight_dependencies(None)

    # ---- row decorations (mod_decorations.py; painted by screens/mod_list.py) ----
    def _outdated_ids(self) -> set[str]:
        """The scanned mods lists.js isOutdated marks against the installed
        game version: computed once per scan / version, then set lookups."""
        key = self._outdated_key
        if key is None or key[0] is not self._mods or key[1] != self._game_version:
            version = self._game_version
            self._outdated = {i for i, m in self._mods.items() if mod_decorations.is_outdated(m, version)}
            self._outdated_key = (self._mods, version)
            log(
                f"outdated mods (game version {version or 'unknown'}): {len(self._outdated)} of "
                f"{len(self._mods)}: {clip(sorted(self._outdated))}"
            )
        return self._outdated

    def _dependency_index(self) -> dict:
        """lists.js buildDependencyIndex over the scanned mods, built once per
        scan (App.jsx: useMemo on mods)."""
        if self._dep_index_for is not self._mods:
            self._dep_index = mod_decorations.build_dependency_index(self._mods)
            self._dep_index_for = self._mods
            log(
                f"dependency index: {len(self._dep_index['depends_on'])} of {len(self._mods)} mods "
                f"depend on other scanned mods ({sum(map(len, self._dep_index['depends_on'].values()))} links)"
            )
        return self._dep_index

    def _row_decor(self, mod_id: str) -> RowDecor:
        """A pane row's decorations (ModListModel's decor). warning / error:
        the mod has a validation issue of that severity (only Active mods
        ever do; only the Active pane paints the icons); conflict: it's in
        one of validation's conflict pairs (both panes get it, as App.jsx
        passes `conflicts` to both lists - only active mods ever match);
        not_found: no scanned mod (RowLabel's !mod), with pending /
        downloading (RowView: pending = !mod && pendingWid && !downloading)
        picking the look; neither -> the plain red "(not found)" row."""
        m = self._mods.get(mod_id)
        issues = self._issues_by_mod.get(mod_id, ())
        downloading = m is None and mod_id in self.downloading
        pending = not downloading and mod_list_io.not_found_workshop_id(mod_id, self._mods) is not None
        return RowDecor(
            official=m is not None and m.get("source") == "official",
            outdated=mod_id in self._outdated_ids(),
            dependency=mod_id in self._dependency_ids,
            dependent=mod_id in self._dependent_ids,
            warning=any(i["severity"] == "warning" for i in issues),
            error=any(i["severity"] == "error" for i in issues),
            conflict=mod_id in self._conflicts,
            pending=pending,
            downloading=downloading,
            not_found=m is None,
            dds_leftover=m is not None and bool(m.get("dds_leftover")),
            row_warn=m is not None and bool(m.get("warnings")),
        )

    def _row_tooltip(self, mod_id: str) -> str:
        """A pane row's tooltip (ModList.jsx Row's title). Its "Incompatible
        with:" names (ModList.jsx conflictNames) follow the mod's conflict
        issue's target order (the JS Set's insertion order; validation's
        conflicts values are unordered sets), any others after, sorted."""
        others = self._conflicts.get(mod_id)
        names = None
        if others:
            order = next((i["targets"] for i in self._issues_by_mod.get(mod_id, ()) if i["kind"] == "conflict"), [])
            ids = [t for t in order if t in others] + sorted(others.difference(order))
            names = [self._mods[t]["name"] if t in self._mods else t for t in ids]  # lists.js modName
        return mod_decorations.row_tooltip(
            self._mods.get(mod_id), mod_id, self._row_decor(mod_id), names, self._workshop_title(mod_id)
        )

    def _highlight_dependencies(self, mod_id: str | None) -> None:
        """The selection changed to `mod_id` (None: cleared): tints its
        dependencies / dependents in both panes (App.jsx dependencyIds /
        dependentIds, re-derived per selection from the per-scan index).
        Repaints only if the sets changed."""
        deps, dependents = mod_decorations.selection_highlights(self._dependency_index(), mod_id)
        if deps == self._dependency_ids and dependents == self._dependent_ids:
            return
        self._dependency_ids, self._dependent_ids = deps, dependents
        if mod_id:
            log(
                f"dependency highlight for {mod_id}: {len(deps)} dependencies {clip(sorted(deps))}, "
                f"{len(dependents)} dependents {clip(sorted(dependents))}"
            )
        else:
            log("dependency highlight cleared (no selection)")
        for pane in (self.inactive_list, self.active_list):
            pane.mod_model.refresh_decorations()

    def _move(self, index, source: ModListView, target: ModListView) -> None:
        """Double-click: the row at `index` (in `source`) moves to `target`
        (App.jsx activate / deactivate). A not-found Active row (no scanned
        mod: _show_lists keeps them) just leaves the list - deactivate's
        `if (mods.has(id))` gates the Inactive insert, as there's no mod to
        show there; re-loading or re-importing the list brings it back. The
        other direction can't meet one: Inactive only ever holds scanned mods.
        The removal is the edit (history / dirty via the model's row signals),
        with or without an insert."""
        mod_id = source.mod_model.remove_row(index.row()) if index.isValid() else None
        if mod_id is None:
            log(f"double-click in {self._pane_name(source)}: no mod at row {index.row()}, nothing moved")
            return
        target_ids = target.mod_ids()
        if target is self.inactive_list:
            if mod_id not in self._order:
                log(
                    f"removed not-found row {mod_id} (row {index.row()}) from {self._pane_name(source)}; "
                    f"nothing to move to {self._pane_name(target)}; now {len(self.active_list.mod_ids())} active, "
                    f"{len(self.inactive_list.mod_ids())} inactive"
                )
                return
            # Inactive stays in scan (name) order; Active appends at the end.
            pos = self._order[mod_id]
            row = next((i for i, other in enumerate(target_ids) if self._order[other] > pos), len(target_ids))
        else:
            row = len(target_ids)
        target.mod_model.insert_id(row, mod_id)
        log(
            f"moved {mod_id} (row {index.row()}) {self._pane_name(source)} -> {self._pane_name(target)} "
            f"row {row}; now {len(self.active_list.mod_ids())} active, {len(self.inactive_list.mod_ids())} inactive"
        )
        target.setCurrentIndex(target.mod_model.index(row))  # keeps it selected and scrolled into view

    def _show_details(self, mod_id: str | None) -> None:
        """The details panel for the selected row (None: nothing selected); a
        not-found row gets the not-found view, titled by its Workshop title
        when known (App.jsx: DetailsPanel id / mod / pendingTitle)."""
        mod = self._mods.get(mod_id) if mod_id else None
        if mod is None and mod_id:
            self.details_panel.show_mod(None, mod_id, self._workshop_title(mod_id))
        else:
            self.details_panel.show_mod(mod)

    # ---- pending Workshop rows: Subscribe (SteamCMD download, steam_cmd.py) ----
    def _subscribe(self, mod_id: str) -> None:
        """Subscribe on a pending row (its painted button, or the context
        menu): App.jsx onSubscribe - fetch the not-found Workshop id, the row
        showing "downloading..." meanwhile, by the acquisition mode in effect
        (settings.effective_acquire_via): one _download_via_steamcmd call in
        the SteamCMD modes ('steamcmd' / 'gog'), a Steam-client subscribe
        (_subscribe_via_steam) in the 'steamworks' mode."""
        wid = mod_list_io.not_found_workshop_id(mod_id, self._mods)
        if not wid or mod_id in self.downloading:
            log(f"subscribe: {mod_id} is not a pending Workshop row (or already downloading), nothing to do")
            return
        log(f"subscribe: {mod_id} (Workshop id {wid})")
        self._acquire_pending([mod_id])

    def _acquire_pending(self, row_ids: list[str]) -> None:
        """App.jsx acquirePending: fetch the given pending rows right away by
        the acquisition mode in effect (settings.effective_acquire_via) - one
        SteamCMD download run for all of them in the 'steamcmd' / 'gog' modes
        (_download_via_steamcmd), or concurrent Steam-client subscribes in the
        'steamworks' mode (_subscribe_via_steam). Rows that aren't pending, or
        are downloading already, are skipped."""
        rows = list(dict.fromkeys(
            i for i in row_ids if mod_list_io.not_found_workshop_id(i, self._mods) and i not in self.downloading
        ))
        if not rows:
            return
        via = self._acquire_via()
        log(f"acquire pending: {len(rows)} row(s) via {via}: {clip(rows)}")
        if steam_ops.uses_steam_cmd(via):
            self._download_via_steamcmd(rows)
        else:
            self._subscribe_via_steam(rows)

    def _subscribe_via_steam(self, row_ids: list[str]) -> None:
        """App.jsx subscribeViaSteamworks (Settings > Steam mode 'steamworks',
        the Steam client directly): subscribe every given not-found Workshop
        row straight through Steam - a single Subscribe, or all of an
        import's pending rows (_acquire_pending), the counterpart of the
        SteamCMD modes' one download call. Each item runs Subscribe's own
        flow (steam_ops.steam_subscribe_and_wait: subscribe, then poll
        install_info until Steam has it installed), up to SYNC_CONCURRENCY at
        once (steam_ops.run_pool, the same worker pool Sync to Steam uses; one
        Steam helper each), on a daemon thread running
        _subscribe_workshop_items - _SteamClientDone.item lands in
        _on_steam_subscribe_item per finished item (its rows stop
        "downloading"), .done in _on_steam_subscribe_done (one rescan
        resolves the finished rows, then the outcome) - the
        _download_via_steamcmd pattern. With Steam unavailable
        (steam_client.availability) nothing is called: the rows stay pending
        and a message says why (Electron's, plus the availability reason).
        A failed row stays pending, its Subscribe button the retry."""
        rows = list(dict.fromkeys(
            i for i in row_ids if mod_list_io.not_found_workshop_id(i, self._mods) and i not in self.downloading
        ))
        if not rows:
            return
        if self.game_dir is None:  # a pending row can't be on screen without a game, but never trust the caller
            self._warn("Subscribe", "RimWorld install folder is not set.")
            return
        available, reason = self._refresh_steam()
        if not available:
            n = len(rows)
            log(f"steam subscribe batch: {n} row(s) left pending - Steam isn't available ({reason})")
            self._warn(
                "Subscribe",
                f"{n} Workshop mod{' isn' if n == 1 else 's aren'}'t installed and stay{'s' if n == 1 else ''} pending: "
                "Steam isn't available (not a Steam install, or the Steamworks library isn't installed). Switch "
                f"Settings > Steam to a SteamCMD option to download {'it' if n == 1 else 'them'} without Steam."
                + (f"\n\n{reason}" if reason else ""),
            )
            return
        rows_by_wid: dict[str, list[str]] = {}
        for i in rows:
            rows_by_wid.setdefault(mod_list_io.not_found_workshop_id(i, self._mods), []).append(i)
        wids = list(rows_by_wid)
        total = len(wids)
        self.downloading.update(rows)
        self._refresh_workshop_rows()
        log(f"steam subscribe batch: {total} item(s), up to {SYNC_CONCURRENCY} at once: {', '.join(wids)} (rows {clip(rows)})")
        self._notice(
            "Subscribe",
            f"Subscribing to {f'Workshop item {wids[0]}' if total == 1 else f'{total} Workshop items'} on Steam...",
        )
        carrier = _SteamClientDone()  # no parent: owned by _steam_jobs and the thread
        carrier.item.connect(self._on_steam_subscribe_item, Qt.ConnectionType.QueuedConnection)
        carrier.done.connect(self._on_steam_subscribe_done, Qt.ConnectionType.QueuedConnection)
        thread = threading.Thread(
            target=_subscribe_workshop_items,
            args=(_steam_ops_for(self.app_root, self.game_dir), wids, rows_by_wid, carrier),
            name=f"steam-subscribe-{wids[0]}" if total == 1 else f"steam-subscribe-{total}-items",
            daemon=True,
        )
        self._steam_jobs[carrier] = thread
        thread.start()
        log(f"steam subscribe batch: background run started (thread {thread.name})")

    @Slot(object)
    def _on_steam_subscribe_item(self, item: dict) -> None:
        """One item of a Steam-client Subscribe batch landed (on the GUI
        thread, via a queued connection; {"wid", "rows"}): its rows stop
        "downloading" (App.jsx subscribeViaSteamworks's per-item
        setDownloading). The rescan waits for the whole batch
        (_on_steam_subscribe_done)."""
        self.downloading.difference_update(item["rows"])
        self._refresh_workshop_rows()

    @Slot(object)
    def _on_steam_subscribe_done(self, result: dict) -> None:
        """A Steam-client Subscribe batch finished (on the GUI thread, via a
        queued connection): every row stops "downloading", one rescan keeping
        the on-screen Active list swaps each row whose item Steam installed
        for the real mod (mod_list_io.reconcile_active), and the outcome is
        shown (App.jsx subscribeViaSteamworks's three messages): a notice
        when every item is subscribed and installed; for a single item that
        failed, a warning with the reason and its Workshop page; for a batch
        with failures, how many made it, the first failure's reason, and that
        the rest stay pending (Subscribe on a row retries one)."""
        wids, failed, failure = result["wids"], result["failed"], result["failure"]
        self._steam_jobs.pop(result.get("carrier"), None)
        self.downloading.difference_update(result["rows"])
        self.rescan()  # _scan + _show_lists(on-screen Active) + load-order state; warns itself if the scan fails
        self._refresh_workshop_rows()  # the downloading look is gone even if the scan failed
        if failure:
            self._warn("Subscribe", failure)
            return
        total = len(wids)
        ok = total - len(failed)
        log(f"steam subscribe batch: {ok} of {total} subscribed and installed, {len(failed)} failed")
        if not failed:
            self._notice(
                "Subscribe",
                f"Subscribed to Workshop item {wids[0]} and Steam finished downloading it." if total == 1
                else f"Subscribed to all {total} Workshop items on Steam and Steam finished downloading them.",
            )
        elif total == 1:
            self._warn(
                "Subscribe",
                f"Couldn't subscribe to Workshop item {wids[0]}: {failed[0]['error']}. You can open its Workshop page in "
                f"Steam instead: {steam_ops.workshop_page(wids[0])}",
            )
        else:
            self._warn(
                "Subscribe",
                f"Subscribed to {ok} of {total} Workshop items on Steam; {len(failed)} couldn't be ({failed[0]['error']}) "
                "and stay pending (Subscribe on a row retries it; the log has each one's reason).",
            )

    def _download_via_steamcmd(self, row_ids: list[str], start_text: str | None = None) -> None:
        """App.jsx downloadViaSteamCmd (Settings > Steam modes 'steamcmd' -
        the default - and 'gog'): ONE steam_cmd.download_items call (one
        anonymous SteamCMD run) for every given not-found Workshop row - a
        single Subscribe; all of a collection import's pending rows; Check
        for missing Workshop mods; a Resume (start_text: its
        own notice instead of the default "Downloading ...") - into VOLT's
        own folder, then <game>/Mods. Off the GUI thread (a big collection
        can take minutes and the UI stays usable meanwhile): a daemon
        threading.Thread runs _download_workshop_items, whose
        _SteamCmdDownloadDone.done lands in _on_steamcmd_download_done on
        the GUI thread - the community-rules pattern, the one way this
        screen does "background op, report to GUI" - and whose `progress`
        events land in _on_steamcmd_progress for the footer's download row,
        which this call also opens (or merges into: _dl is one row for
        every run in flight, download_state.start_download). The copies'
        marker records the mode in effect ('gog' = permanent, else
        'steamcmd' = temporary until Sync to Steam). SteamCMD's own per-item
        report is only a hint; the rescan afterwards decides: a row is done
        once its mod is on disk. Anything still missing stays pending, its
        Subscribe button (or the row's Resume) the retry."""
        rows = list(dict.fromkeys(
            i for i in row_ids if mod_list_io.not_found_workshop_id(i, self._mods) and i not in self.downloading
        ))
        if not rows:
            return
        if self.game_dir is None:  # a pending row can't be on screen without a game, but never trust the caller
            self._warn("Subscribe", "RimWorld install folder is not set.")
            return
        wids = list(dict.fromkeys(mod_list_io.not_found_workshop_id(i, self._mods) for i in rows))
        via = effective_acquire_via(self._settings.get()["steam_acquire_via"], self._game_source)
        mode = "gog" if via == "gog" else "steamcmd"
        mods_dir = self.game_dir / "Mods"
        self.downloading.update(rows)
        self._refresh_workshop_rows()
        self._dl = download_state.start_download(self._dl, rows, wids)
        self._render_download_bar()
        self._notice(
            "Subscribe",
            start_text or
            f"Downloading {f'Workshop item {wids[0]}' if len(wids) == 1 else f'{len(wids)} Workshop items'} with SteamCMD...",
        )
        log(f"steamcmd download: {len(wids)} item(s) requested (mode {mode}, into {mods_dir}): {', '.join(wids)} "
            f"(rows {clip(rows)})")
        carrier = _SteamCmdDownloadDone()  # no parent: owned by _steamcmd_jobs and the thread
        carrier.done.connect(self._on_steamcmd_download_done, Qt.ConnectionType.QueuedConnection)
        carrier.progress.connect(self._on_steamcmd_progress, Qt.ConnectionType.QueuedConnection)
        thread = threading.Thread(
            target=_download_workshop_items,
            args=(self.app_root, wids, mods_dir, mode, rows, carrier),
            name=f"steamcmd-{wids[0]}" if len(wids) == 1 else f"steamcmd-{len(wids)}-items",
            daemon=True,
        )
        self._steamcmd_jobs[carrier] = thread
        thread.start()
        log(f"steamcmd download: background run started (thread {thread.name})")

    @Slot(object)
    def _on_steamcmd_download_done(self, result: dict) -> None:
        """A SteamCMD download run finished (on the GUI thread, via a queued
        connection): the rows stop "downloading", a rescan keeping the
        on-screen Active list swaps each row whose mod is on disk now for
        the real mod (mod_list_io.reconcile_active - the real answer,
        SteamCMD's report being a hint), and the outcome is shown: a notice
        when everything is on disk, else a warning saying what's still
        missing and why (App.jsx downloadViaSteamCmd's messages). A run
        cancelled by Pause with something still missing is "paused" instead:
        a notice, and the footer's row flips to Paused (its button Resume)
        once every run in flight has settled (download_state.settle_download,
        the JS's `finally`); otherwise the row goes away with the last run."""
        rows, wids, report, failure = result["rows"], result["wids"], result["report"], result["failure"]
        self._steamcmd_jobs.pop(result.get("carrier"), None)
        self.downloading.difference_update(rows)
        paused = False  # cancelled by Pause with something still missing
        try:
            paused = self._report_steamcmd_download(wids, report, failure)
        finally:
            # Paused only once the call has really settled cancelled (never on
            # the click itself: the run may finish on its own meanwhile).
            self._dl = download_state.settle_download(self._dl, paused)
            self._render_download_bar()

    def _report_steamcmd_download(self, wids: list[str], report: dict | None, failure: str | None) -> bool:
        """_on_steamcmd_download_done's rescan + outcome message (App.jsx
        downloadViaSteamCmd's second `try`). True when the run was paused:
        cancelled by the user with something still missing."""
        self.rescan()  # _scan + _show_lists(on-screen Active) + load-order state; warns itself if the scan fails
        self._refresh_workshop_rows()  # the downloading look is gone even if the scan failed
        on_disk = {w for w in map(mods.workshop_id, self._mods.values()) if w}
        missing = [w for w in wids if w not in on_disk]
        results = report["results"] if report else []
        for w in wids:
            r = next((x for x in results if x["id"] == w), None)
            reported = "no result" if r is None else "nothing" if r["ok"] is None else "ok" if r["ok"] else "failed"
            detail = f": {r['message']}" if r and r.get("message") else ""
            log(f"steamcmd download {w}: {'on disk after rescan' if w in on_disk else 'STILL MISSING, stays pending'} "
                f"(SteamCMD reported {reported}{detail})")
        done = len(wids) - len(missing)
        log(f"steamcmd download: {done} of {len(wids)} on disk{' (paused by the user)' if report and report.get('cancelled') else ''}")
        if report and report.get("cancelled") and missing:
            self._notice(
                "Subscribe",
                f"SteamCMD download paused: {done} of {len(wids)} Workshop item{'' if len(wids) == 1 else 's'} on disk. "
                "Resume continues it.",
            )
            return True
        if not missing:
            self._notice(
                "Subscribe",
                f"Downloaded Workshop item {wids[0]} with SteamCMD." if len(wids) == 1
                else f"Downloaded all {len(wids)} Workshop items with SteamCMD.",
            )
            return False
        why = failure or next((r["message"] for r in results if r["id"] in missing and r.get("message")), None) \
            or (report["error"] if report else None)
        if len(wids) == 1:
            text = f"Couldn't download Workshop item {wids[0]} with SteamCMD"
        else:
            text = (f"Downloaded {done} of {len(wids)} Workshop items with SteamCMD; {len(missing)} couldn't be "
                    "downloaded and stay pending (Subscribe on a row retries it)")
        text += f" ({why})" if why else ""
        text += "."
        if len(wids) == 1:
            text += f" You can open its Workshop page in Steam instead: https://steamcommunity.com/sharedfiles/filedetails/?id={wids[0]}"
        self._warn("Subscribe", text)
        return False

    @Slot(object)
    def _on_steamcmd_progress(self, ev: dict) -> None:
        """A live SteamCMD event (steam_cmd.create_progress_parser's
        "progress" / "item-done" dicts) on the GUI thread, via a queued
        connection: folded into the footer's row (lists.js
        applyDownloadEvent - the current item's percent and speed, the
        finished items, the failed ones) and the row redrawn. Nothing to do
        when no row is shown (an event that outlived its row)."""
        if self._dl is None:
            return
        self._dl = download_state.apply_download_event(self._dl, ev)
        self._render_download_bar()

    def _render_download_bar(self) -> None:
        """The footer's download row follows _dl: hidden when None, else
        redrawn from it (screens/download_bar.py DownloadBar.render)."""
        if self._dl is None:
            self.download_bar.setVisible(False)
            self.download_bar.clear()
            return
        self.download_bar.render(self._dl, self.workshop_titles)
        self.download_bar.setVisible(True)

    def _toggle_download_pause(self) -> None:
        """The download row's pause / resume button (App.jsx
        onToggleDownloadPause). Paused: Resume re-runs the same rows through
        _download_via_steamcmd (SteamCMD's cache skips what already
        finished) - or, when none of them is still pending (resolved some
        other way meanwhile), just drops the row. Downloading: Pause
        disables the button (`pausing`) and kills the run
        (steam_cmd.cancel_current); the run's own settling flips the row to
        Paused (_on_steamcmd_download_done), never this click - unless
        nothing was running, in which case the button is re-enabled at
        once. Ignored while a Pause is already waiting."""
        dl = self._dl
        if dl is None or dl.pausing:
            return
        if dl.paused:
            log(f"steamcmd download: resume requested for {len(dl.rows)} row(s): {', '.join(dl.rows)}")
            if not any(mod_list_io.not_found_workshop_id(i, self._mods) for i in dl.rows):
                log("steamcmd download: nothing left to resume (every row resolved meanwhile), row dismissed")
                self._dl = None
                self._render_download_bar()
                return
            n = len(dl.wids)
            self._download_via_steamcmd(
                list(dl.rows), f"Resuming the SteamCMD download ({n} Workshop item{'' if n == 1 else 's'})..."
            )
            return
        log("steamcmd download: pause requested")
        self._dl = replace(dl, pausing=True)
        self._render_download_bar()
        try:
            stopped = steam_cmd.cancel_current()
        except Exception as err:  # never expected (cancel_current logs and swallows its own failures); the JS catches too
            log(f"steamcmd download: cancel FAILED - {err!r}")
            if self._dl is not None:
                self._dl = replace(self._dl, pausing=False)
                self._render_download_bar()
            self._warn("Pause download", str(err) or repr(err))
            return
        log(f"steamcmd download: cancel {'sent' if stopped else 'found nothing running'}")
        if not stopped and self._dl is not None:
            self._dl = replace(self._dl, pausing=False)
            self._render_download_bar()

    # ---- Unsubscribe (App.jsx onUnsubscribe / unsubscribeNow / removeDownloadNow) ----
    def _unsubscribe(self, mod_id: str) -> None:
        """Unsubscribe from an installed Workshop mod (the context menu):
        destructive, so it confirms first (_confirm, Electron's wording per
        kind). steam_ops.unsubscribe_kind decides how: a SteamCMD download
        (source 'steamcmd' / 'gog') was never subscribed on Steam, so it only
        has its folder deleted (steam_cmd.delete_item, best effort, no Steam
        call - synchronous under the busy cursor, as this screen's other file
        operations; _remove_download); a real subscription (source
        'workshop') gets the unsubscribe-verify-delete flow on a daemon
        thread (_unsubscribe_workshop_item -> _on_unsubscribe_done). Either
        way a rescan follows, so the lists update by themselves (Electron
        asked for a Rescan instead)."""
        mod = self._mods.get(mod_id)
        kind = steam_ops.unsubscribe_kind(mod)
        if kind is None or mod_id in self._unsubscribing:
            log(f"unsubscribe: {mod_id} is not a Workshop mod (or its Unsubscribe is already running), nothing to do")
            return
        wid = mods.workshop_id(mod)
        name, path = mod["name"], mod["path"]
        if kind == "delete":
            if not self._confirm(
                f"Remove {name}?",
                f"This mod was downloaded with SteamCMD and isn't subscribed on Steam, so this only deletes its folder "
                f"from RimWorld's Mods folder ({path}).\n\n"
                "Removing files is best-effort: a file that's locked or in use is skipped rather than failing the "
                "whole operation.",
                confirm_label="Remove",
            ):
                return
            self._remove_download(path, name)
            return
        if not self._confirm(
            f"Unsubscribe from {name}?",
            f"This unsubscribes you from the mod on Steam, then also removes any files left in its own Workshop "
            f"folder ({path}).\n\n"
            "Removing files is best-effort: a file that's locked or in use is skipped rather than failing the "
            "whole operation.",
            confirm_label="Unsubscribe",
        ):
            return
        if self.game_dir is None:  # a scanned mod can't be on screen without a game, but never trust the caller
            self._warn("Unsubscribe", "RimWorld install folder is not set.")
            return
        available, reason = self._refresh_steam()
        if not available:
            log(f"unsubscribe {wid} ({name}): refused - Steam isn't available ({reason})")
            self._warn("Unsubscribe", reason)
            return
        self._unsubscribing.add(mod_id)
        self._notice("Unsubscribe", f"Unsubscribing from {name}...")
        carrier = _SteamClientDone()  # no parent: owned by _steam_jobs and the thread
        carrier.done.connect(self._on_unsubscribe_done, Qt.ConnectionType.QueuedConnection)
        thread = threading.Thread(
            target=_unsubscribe_workshop_item,
            args=(_steam_ops_for(self.app_root, self.game_dir), self.game_dir, mod_id, wid, name, carrier),
            name=f"steam-unsubscribe-{wid}",
            daemon=True,
        )
        self._steam_jobs[carrier] = thread
        thread.start()
        log(f"unsubscribe {wid} ({name}): background run started (thread {thread.name})")

    def _remove_download(self, path, name: str) -> None:
        """Unsubscribe's 'delete' kind (App.jsx removeDownloadNow): delete the
        SteamCMD download's folder, nothing else. steam_cmd.delete_item is
        best effort and doesn't raise for a locked file, so `gone` is the
        only real answer: False = the folder is still there, not removed (the
        marker is kept, so this can be retried). Then a rescan."""
        log(f"remove download {path} ({name}): starting")
        try:
            r = self._busy(lambda: steam_cmd.delete_item(self.game_dir / "Mods" if self.game_dir else None, path))
        except (ValueError, OSError) as err:  # not a SteamCMD folder directly under Mods (a stale scan), or the marker read
            log(f"remove download {path} ({name}): FAILED - {err}")
            self._warn("Remove", str(err))
            return
        left = len(r["skipped"])
        if r["gone"]:
            log(f"remove download {r['path']} ({name}): removed")
        else:
            skipped = "; ".join(f"{s['path']} ({s['error']})" for s in r["skipped"])
            log(f"remove download {r['path']} ({name}): NOT removed - folder still on disk, {left} item(s) couldn't be "
                f"deleted: {skipped}")
        self.rescan()
        if r["gone"]:
            self._notice("Remove", f"Removed {name}'s SteamCMD download.")
        else:
            why = (f"{left} item{' was' if left == 1 else 's were'} locked or in use" if left
                   else "its folder couldn't be deleted")
            self._warn(
                "Remove",
                f"Couldn't fully remove {name}'s SteamCMD download: {why}, so it's still in {r['path']}. Close whatever "
                "is using it (the game, say) and remove it again.",
            )

    @Slot(object)
    def _on_unsubscribe_done(self, result: dict) -> None:
        """An Unsubscribe ('steam' kind) finished (on the GUI thread, via a
        queued connection): the mod's menu entry is usable again, a rescan
        (its Workshop folder is gone, or partly), and the outcome (App.jsx
        unsubscribeNow's messages): a notice when Steam dropped it and its
        folder is gone, a warning naming what was left behind, or the failure
        (still subscribed after the verify checks: its files were left alone)."""
        self._steam_jobs.pop(result.get("carrier"), None)
        self._unsubscribing.discard(result["mod_id"])
        wid, name, r, failure = result["wid"], result["name"], result["result"], result["failure"]
        if failure:
            self._warn("Unsubscribe", failure)
            return
        left = len(r["skipped"])
        log(f"unsubscribe {wid}: verified; Workshop folder {r['path']} "
            f"{'removed' if r['gone'] else f'partly removed, {left} item(s) left'}")
        self.rescan()
        text = f"Unsubscribed from {name}" + (
            " and removed its Workshop folder." if r["gone"]
            else f". {left} item{' was' if left == 1 else 's were'} locked or in use and left behind in {r['path']}." if left
            else "."
        )
        if left:
            self._warn("Unsubscribe", text)
        else:
            self._notice("Unsubscribe", text)

    # ---- Sync to Steam (App.jsx syncToSteam) ----
    def _sync_to_steam(self) -> None:
        """The actions column's Sync button (only it, never Save): make every
        SteamCMD-downloaded mod (source 'steamcmd' with a Workshop id - never
        a permanent 'gog' copy) a real Steam subscription, then drop its
        SteamCMD copy once Steam's own download is on disk
        (steam_ops.sync_steamcmd_mods, two passes, on a daemon thread running
        _sync_to_steam_run -> _on_sync_done). Refused while one is running
        (`_syncing`; the button reads "Syncing..."), with Steam unavailable,
        or with nothing to sync. Past those, the heads-up dialog
        (_confirm_sync; skipped once "Don't ask me again" stored
        skip_sync_confirm) - Cancel there aborts. Progress: Electron showed a
        running "X/N remaining" in the status bar; this port's status text
        isn't wired yet, so that goes to volt.log, and the screen shows one
        notice at the start and one summary at the end."""
        if self._syncing:
            log("sync: refused - a Sync to Steam is already running")
            self._notice("Sync to Steam", "A Sync to Steam is already running.")
            return
        if self.game_dir is None:
            self._warn("Sync to Steam", "RimWorld install folder is not set.")
            return
        count = sum(1 for m in self._mods.values() if m["source"] == "steamcmd" and mods.workshop_id(m))
        available, reason = self._refresh_steam()
        if not available:
            log(f"sync: refused - Steam isn't available ({reason}); {count} SteamCMD mod(s) would have been synced")
            self._warn(
                "Sync to Steam",
                "Steam isn't available (not a Steam install, or the Steamworks library isn't installed), so nothing "
                "was synced." + (f"\n\n{reason}" if reason else ""),
            )
            return
        if not count:
            log("sync: nothing to sync (no SteamCMD-downloaded mod with a Workshop id)")
            self._notice("Sync to Steam", "Nothing to sync: every Workshop mod is already subscribed on Steam.")
            return
        if self._settings.get()["skip_sync_confirm"]:
            log("sync: confirmation skipped (skip_sync_confirm set)")
        elif not self._confirm_sync():
            log(f"sync: cancelled at the confirmation; {count} SteamCMD mod(s) not synced")
            return
        self._syncing = True
        self._apply_load_order_state()  # the Sync button: disabled, "Syncing..."
        self._notice("Sync to Steam", f"Syncing {count} SteamCMD-downloaded mod{'' if count == 1 else 's'} to Steam...")
        carrier = _SteamClientDone()  # no parent: owned by _steam_jobs and the thread
        carrier.done.connect(self._on_sync_done, Qt.ConnectionType.QueuedConnection)
        thread = threading.Thread(
            target=_sync_to_steam_run,
            args=(_steam_ops_for(self.app_root, self.game_dir, self.game_dir / "Mods"), dict(self._mods), carrier),
            name="steam-sync",
            daemon=True,
        )
        self._steam_jobs[carrier] = thread
        thread.start()
        log(f"sync: background run started for {count} SteamCMD mod(s) (thread {thread.name})")

    @Slot(object)
    def _on_sync_done(self, result: dict) -> None:
        """A Sync to Steam finished (on the GUI thread, via a queued
        connection): the button is a plain Sync again; a rescan when anything
        was synced or is pending (a pending copy can have changed on disk
        too - a partly deleted one); then App.jsx syncToSteam's summary: how
        many of the total synced, that Steam has them and the copies are gone,
        how many are pending (subscribed but the download unconfirmed or the
        copy locked - the next sync finishes them) and how many couldn't be
        subscribed (the first reason) - a notice when everything synced, a
        warning otherwise."""
        self._steam_jobs.pop(result.get("carrier"), None)
        self._syncing = False
        self._apply_load_order_state()
        r, failure = result["result"], result["failure"]
        if failure:
            self._warn("Sync to Steam", failure)
            return
        n, pending, failed, total = len(r["synced"]), len(r["pending"]), len(r["failed"]), r["total"]
        if n or pending:
            self.rescan()
        text = f"Synced {n} of {total} mod{'' if total == 1 else 's'} to Steam."
        if n:
            text += " Steam downloaded them into its Workshop folder and their SteamCMD copies were removed."
        if pending:
            text += (
                f" {pending} {'is' if pending == 1 else 'are'} subscribed on Steam but still "
                f"{'has its SteamCMD copy' if pending == 1 else 'have their SteamCMD copies'} (Steam didn't confirm the "
                f"download within {SUBSCRIBE_TIMEOUT_S:g} seconds, or a file in the copy was locked or in use - the log "
                f"says which); the next sync finishes {'it' if pending == 1 else 'them'}."
            )
        if failed:
            text += (f" {failed} couldn't be subscribed ({r['failed'][0]['error']}) and stay as SteamCMD downloads until "
                     "the next sync.")
        if failed or pending:
            self._warn("Sync to Steam", text)
        else:
            self._notice("Sync to Steam", text)

    def _subscribe_tooltip(self) -> str:
        """The Subscribe button's title (ModList.jsx .row-subscribe), by the
        acquisition mode in effect (lists.js usesSteamCmd) and, in the Steam-
        client mode, whether Steam is available (the button is disabled when
        not - _subscribe_ready)."""
        if steam_ops.uses_steam_cmd(self._acquire_via()):
            return "Download this mod with SteamCMD"
        if self._steam_available:
            return "Subscribe on Steam and download this mod"
        return "Steam isn't available (not a Steam install, or the Steamworks library didn't load)"

    def _check_missing_workshop(self, parent: QWidget | None = None) -> None:
        """Settings > Steam > Check for missing Workshop mods (App.jsx
        checkMissingWorkshop): every not-found Workshop row of the Active
        list not already downloading (mod_list_io.missing_workshop_rows),
        fetched through _acquire_pending - the same path Subscribe and a
        collection import's pending rows take (one SteamCMD run, or
        Steam-client subscribes with their own Steam-unavailable message),
        so its notices / warnings are Subscribe's. Deliberately not
        Electron's bespoke version (its checkingMissing flag, one-at-a-time
        Steam-client loop and "Checked N missing mods" wording): the rows
        join self.downloading synchronously before any thread starts, so a
        second click finds nothing left to fetch. `parent` (the Settings
        window, SettingsWindow's on_check_missing(parent) shape) is unused:
        every message here is the screen's own."""
        rows = [
            i for i in mod_list_io.missing_workshop_rows(self.active_list.mod_ids(), self._mods)
            if i not in self.downloading
        ]
        log(f"check missing workshop mods: {len(rows)} row(s): {clip(rows)}")
        if not rows:
            self._notice(
                "Check for missing Workshop mods", "Nothing to check: every Workshop mod in the active list is installed."
            )
            return
        self._acquire_pending(rows)

    def _refresh_workshop_rows(self) -> None:
        """workshop_titles or downloading changed: both panes re-read their
        rows (names, decorations, tooltips) and the details panel re-shows
        the selection (a title may have arrived). The one call the Steam
        Workshop port makes after changing either."""
        for pane in (self.inactive_list, self.active_list):
            pane.mod_model.refresh_decorations()
        self._show_details(self.active_list.selected_mod_id() or self.inactive_list.selected_mod_id())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for notice in self.findChildren(_Notice):
            self._place_notice(notice)

    # ---- header row 1: .paths-bar (PathsBar.jsx) ----
    def _build_paths_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(BAR_SIDE, 8, BAR_SIDE, 0)
        row.setSpacing(GAP)

        self.settings_button = _button("Settings")
        row.addWidget(self.settings_button)
        row.addSpacing(16 - GAP)  # .settings-btn margin-right: 16px

        row.addWidget(_label("Paths:", muted=True))
        # Disabled until a path is known (PathsBar: disabled={!value}).
        self.game_link = _button("Game", variant="link")
        self.mods_link = _button("Mods", variant="link")
        self.config_link = _button("Config", variant="link")
        row.addWidget(self.game_link)
        row.addWidget(_label("/", muted=True))
        row.addWidget(self.mods_link)
        row.addWidget(_label("/", muted=True))
        row.addWidget(self.config_link)
        # Plain gap, not "/": the load order's folder isn't nested under the
        # game folder like the three above, it's under VOLT's own load-orders/.
        row.addSpacing(16 - GAP)
        self.load_order_link = _button("Load order", variant="link")  # disabled with no load order open
        row.addWidget(self.load_order_link)
        row.addSpacing(16 - GAP)  # .path-link-last margin-right: 16px

        self.storefront_tag = QLabel("Steam")
        self.storefront_tag.setProperty("role", "tag")
        row.addWidget(self.storefront_tag)
        self.version_label = _label(f"V. O. L. T. v{version('volt-py')}", muted=True)
        self.version_label.setProperty("role", "wordmark")  # theme.py: the Circuit wordmark
        row.addWidget(self.version_label)
        row.addStretch(1)
        self.help_button = _button("Help")  # far right: the Help window (_show_help)
        row.addWidget(self.help_button)
        return bar

    # ---- header row 2: .loadorder-bar (LoadOrderBar.jsx) ----
    def _build_load_order_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("loadOrderBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(BAR_SIDE, 6, BAR_SIDE, 6)
        row.setSpacing(GAP)

        row.addWidget(QLabel("Load order"))
        self.load_order_picker = QComboBox()
        self.load_order_picker.setMinimumWidth(260)
        self.load_order_picker.setEnabled(False)
        # Right-click: Delete the selected load order (_show_load_order_menu).
        self.load_order_picker.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.load_order_picker.customContextMenuRequested.connect(self._show_load_order_menu)
        row.addWidget(self.load_order_picker)
        self.new_button = _button("New load order...")
        self.copy_button = _button("Copy to new...")
        row.addWidget(self.new_button)
        row.addWidget(self.copy_button)

        # Only shown while there are unsaved changes (_apply_load_order_state).
        self.dirty_label = QLabel("Unsaved changes")
        self.dirty_label.setProperty("role", "dirty")
        self.dirty_label.setVisible(False)
        row.addWidget(self.dirty_label)
        self.undo_button = _button("↺")  # ↺
        self.undo_button.setObjectName("undoButton")
        self.undo_button.setFixedSize(24, 24)
        self.undo_button.setToolTip("Undo the most recent change to the active list (Ctrl+Z)")
        self.undo_button.setVisible(False)
        row.addWidget(self.undo_button)

        row.addStretch(1)
        self.game_version_label = _label("Game version: —", muted=True)
        row.addWidget(self.game_version_label)
        return bar

    # ---- .content-row: .main grid + .actions-column ----
    def _build_content_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(BAR_SIDE, 8, BAR_SIDE, 8)
        row.setSpacing(GAP)

        # The 3-col grid, or (no install found) the center message in its place.
        self._grid = QWidget()
        grid = QHBoxLayout(self._grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(GAP)
        inactive_pane, self.inactive_search, self.inactive_eye, self.inactive_list = self._build_pane("Inactive")
        # Drag-reorder: Active only (its order is the load order); moving
        # between panes stays double-click only. The model changes once, at
        # the drop (ModListView / ModListModel.move_row); while dragging, the
        # other rows slide aside (animated preview, mod_list.SlideAnimation).
        # Off while the pane's search hides rows, like the Electron app (a
        # drag across hidden rows would reorder around them); dim mode keeps
        # it (ModListView.drag_enabled).
        active_pane, self.active_search, self.active_eye, self.active_list = self._build_pane(
            "Active", draggable=True, issue_icons=True, subscribe=True
        )
        columns = (self._build_details_panel(), inactive_pane, active_pane)
        for column, stretch, min_width in zip(columns, GRID_STRETCH, GRID_MIN_WIDTH):
            # Ignored horizontal policy: width follows the stretch ratio alone
            # (like the grid's fr units), never the widgets' size hints;
            # the minimum width is still honored (the minmax() floor).
            column.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            column.setMinimumWidth(min_width)
            grid.addWidget(column, stretch)
        row.addWidget(self._grid, 1)
        self._no_game = self._build_no_game_message()
        row.addWidget(self._no_game, 1)

        actions = self._build_actions_column()
        row.addWidget(actions)
        # Circuit panel shadows (painters.py: a cached 9-slice this screen
        # paints behind the four panels; the lists themselves are untouched)
        # and the dot grid inside the empty details pane.
        painters.install_shadows(self, (self.details_panel, self.inactive_list, self.active_list, actions))
        panel = self.details_panel
        painters.install_empty_grid(panel, lambda: panel.details_empty.isVisibleTo(panel), over_default=True)
        return row

    # .center-message (App.jsx no-game branch). The text's first sentence
    # (why there's no game folder) is set by _apply_paths.
    def _build_no_game_message(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setSpacing(GAP)
        layout.addStretch(1)
        self._no_game_text = _label("", muted=True)
        for label in (_label("Couldn't find RimWorld"), self._no_game_text):
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
        # .button-row, centered; the same actions as Settings > General's
        # Browse... (game) and Autodetect paths.
        locate = QPushButton("Locate RimWorld folder...")
        locate.setProperty("variant", "primary")
        locate.clicked.connect(lambda: self._browse_path("game"))
        retry = QPushButton("Try autodetect again")
        retry.clicked.connect(lambda: self._autodetect_paths())
        buttons = QHBoxLayout()
        buttons.setSpacing(GAP)
        buttons.addStretch(1)
        buttons.addWidget(locate)
        buttons.addWidget(retry)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return box

    # .details (DetailsPanel.jsx)
    def _build_details_panel(self) -> QFrame:
        # DetailsPanel.jsx; its preview follows the panel's own size.
        self.details_panel = DetailsPanel()
        return self.details_panel

    def _mod_color(self, mod_id: str) -> str | None:
        """A mod's '#rrggbb' color (settings mod_colors), or None."""
        return self._settings.get()["mod_colors"].get(mod_id)

    # ---- right-click menu (ModList.jsx menuItems) ----
    def _show_mod_menu(self, pane: ModListView, search: QLineEdit, pos) -> None:
        """The row's context menu. Right-click also selects the row. Unusable
        items are disabled, never left out. Below a divider, Subscribe:
        enabled on a pending row not already downloading, in a mode that can
        run it (ModList.jsx: canSubscribe && notFoundWorkshopId &&
        !downloading.has(id); _subscribe_ready), _subscribe; then Unsubscribe
        (steam_ops.unsubscribe_kind): a real Steam subscription (source
        'workshop') needs Steam available, a SteamCMD download (source
        'steamcmd' / 'gog') was never subscribed, so it only deletes its
        files and needs no Steam; disabled while that mod's own Unsubscribe
        is still running, _unsubscribe."""
        index = pane.indexAt(pos)
        mod_id = pane.mod_model.id_at(index.row()) if index.isValid() else None
        if mod_id is None:
            return
        pane.setCurrentIndex(index)
        mod = self._mods.get(mod_id)  # None: a not-found row (e.g. a pending Workshop id)
        pending = mod_list_io.not_found_workshop_id(mod_id, self._mods) is not None
        urls = mods.workshop_urls(mod)
        color = self._mod_color(mod_id)
        pkg = mod["package_id"] if mod else mod_id  # a not-found mod's id is its lowercased packageId
        kind = steam_ops.unsubscribe_kind(mod)  # None | 'delete' | 'steam'
        log(f"context menu: {mod_id} in {self._pane_name(pane)} (workshop={bool(urls)}, color={color}, "
            f"pending={pending}, unsubscribe={kind})")

        menu = QMenu(pane)

        def item(target: QMenu, label: str, enabled, fn) -> None:
            action = target.addAction(label)
            action.setEnabled(bool(enabled))
            action.triggered.connect(lambda: fn())

        item(menu, "Open folder", mod, lambda: self._open_folder(mod["path"]))
        item(menu, "Open URL in browser", urls, lambda: self._open_url(urls["web"]))
        item(menu, "Open URL in Steam", urls, lambda: self._open_url(urls["steam"]))
        sub = menu.addMenu("Filter by")
        item(sub, "This mod author", mod and mod["authors"], lambda: search.setText(mod["authors"][0]))
        item(sub, "This mod color", color, lambda: pane.set_color_filter(color))
        sub = menu.addMenu("Copy to clipboard")
        item(sub, "Copy URL", urls, lambda: self._copy_text(urls["web"], "Copied the Workshop URL."))
        item(sub, "Copy PackageId", pkg, lambda: self._copy_text(pkg, f'Copied "{pkg}".'))
        sub = menu.addMenu("Mod color")
        item(sub, "Change mod color", True, lambda: self._pick_mod_color(mod_id, color))
        item(sub, "Discolor mod", color, lambda: self._set_mod_color(mod_id, None))
        sub = menu.addMenu("Rules...")
        item(sub, "Create rule", True, lambda: self._create_rule(pkg))
        item(sub, "Show rules", True, lambda: self._show_rules())
        menu.addSeparator()
        item(menu, "Subscribe", pending and mod_id not in self.downloading and self._subscribe_ready(),
             lambda: self._subscribe(mod_id))
        item(menu, "Unsubscribe",
             kind is not None and mod_id not in self._unsubscribing and (kind == "delete" or self._steam_available),
             lambda: self._unsubscribe(mod_id))
        menu.exec(pane.viewport().mapToGlobal(pos))
        menu.deleteLater()

    # ---- user Sort rules (screens/rules_window.py) ----
    def _create_rule(self, pkg: str) -> None:
        """Rules... > Create rule: always a new entry for this mod (never
        reuses one already naming it), saved at once, then shown selected."""
        try:
            entry = self._settings.add_user_rule(mod=pkg)
        except (OSError, ValueError) as err:
            log(f"rules: create rule for {pkg} FAILED: {err!r}")
            self._warn("Couldn't create rule", str(err))
            return
        log(f"rules: created rule {entry['id']} for {pkg} (saved to settings)")
        self._show_rules(select_id=entry["id"])

    def _show_rules(self, select_id: str | None = None) -> None:
        """Rules... > Show rules (and after Create rule). The window reads
        user_rules fresh from settings and saves every edit itself; nothing
        here is part of the load order's unsaved-changes state."""
        log(f"rules window opened: {len(self._settings.get()['user_rules'] or [])} rules, select {select_id}")
        RulesWindow(self._settings, self._mods, self._warn, select_id=select_id, parent=self).exec()
        log(f"rules window closed: {len(self._settings.get()['user_rules'] or [])} rules")
        self._apply_load_order_state()  # validation reads the user rules (_update_validation)

    def _open_url(self, url: str) -> None:
        """Electron's shell.openExternal: os.startfile opens a URL (https:// or
        steam://) with its registered handler, as it opens a file."""
        try:
            paths.open_path(url)
        except OSError as err:
            log(f"open url {url}: the OS refused: {err!r}")
            self._warn("Couldn't open URL", str(err))
            return
        log(f"open url {url}: opened")

    def _copy_text(self, text: str, done: str) -> None:
        QGuiApplication.clipboard().setText(text)
        log(f"copied to clipboard: {text}")
        self._notice("Clipboard", done)

    def _pick_mod_color(self, mod_id: str, color: str | None) -> None:
        """Change mod color: Qt's own (non-native, so app-themed) color dialog,
        opened at the cursor and kept on screen, starting from the mod's color
        (else white, like the Electron color input). Saved on OK only."""
        dialog = QColorDialog(QColor(color or "#ffffff"), self)
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        dialog.setWindowTitle("Mod color")
        pos, size = QCursor.pos(), dialog.sizeHint()
        screen = QGuiApplication.screenAt(pos)
        if screen is not None:
            area = screen.availableGeometry()
            pos.setX(max(area.left(), min(pos.x(), area.right() - size.width())))
            pos.setY(max(area.top(), min(pos.y(), area.bottom() - size.height())))
        dialog.move(pos)
        if dialog.exec():
            self._set_mod_color(mod_id, dialog.selectedColor().name())
        else:
            log(f"mod color for {mod_id}: dialog cancelled, unchanged")

    def _set_mod_color(self, mod_id: str, color: str | None) -> None:
        """Saves (None: clears) a mod's color, then refreshes both panes'
        swatches and any color filter (a recolored mod can leave it)."""
        try:
            self._settings.set_mod_color(mod_id, color)
        except (OSError, ValueError) as err:
            log(f"mod color for {mod_id} -> {color}: FAILED: {err!r}")
            self._warn("Couldn't save mod color", str(err))
            return
        log(f"mod color for {mod_id}: {color or 'cleared'} (saved to settings)")
        for pane in (self.inactive_list, self.active_list):
            pane.mod_model.refresh_colors()
            if pane.search.color_filter:
                pane.set_search()

    def _mod_matches(self, mod_id: str, q: str) -> bool:
        """A pane's search matcher (lists.js modMatches over the scanned mods)."""
        return mod_matches(self._mods, mod_id, q)

    # .pane (ModList.jsx): title with count, search + eye toggle, list
    def _build_pane(
        self, title: str, *, draggable: bool = False, issue_icons: bool = False, subscribe: bool = False
    ) -> tuple[QWidget, QLineEdit, QAction, ModListView]:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = painters.TerminalLabel(title)  # a Circuit terminal label (role pane-title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        search = QLineEdit()
        search.setPlaceholderText("Search name, author or package ID")
        # Dim/hide eye toggle docked inside the input's right edge
        # (.pane-search-wrap + button.search-eye). Both enabled with a game (_apply_paths).
        eye = search.addAction(_eye_icon(False), QLineEdit.ActionPosition.TrailingPosition)
        eye.setToolTip(_EYE_TOOLTIP[False])
        eye.setEnabled(False)
        search.setEnabled(False)
        layout.addWidget(search)

        # .pane-hint.pane-color-filter: "Only mods colored [swatch] [Clear]",
        # while a color filter is set (on_search_changed).
        color_hint = QWidget()
        hint_row = QHBoxLayout(color_hint)
        hint_row.setContentsMargins(0, 0, 0, 0)
        hint_row.setSpacing(6)
        hint_row.addWidget(_label("Only mods colored", muted=True))
        color_swatch = QLabel()
        color_swatch.setFixedSize(10, 10)
        hint_row.addWidget(color_swatch)
        hint_row.addStretch(1)
        clear_color = QPushButton("Clear")
        clear_color.clicked.connect(lambda: mod_list.set_color_filter(None))
        hint_row.addWidget(clear_color)
        color_hint.setVisible(False)
        layout.addWidget(color_hint)

        def on_search_changed() -> None:
            # ModList.jsx: "{title} [{filtered ? matches/total : total}]", and the eye's state.
            s = mod_list.search
            title_label.setText(f"{title} [{s.count_text()}]")
            eye.setIcon(_eye_icon(s.dim))
            eye.setToolTip(_EYE_TOOLTIP[s.dim])
            # .list-empty, filtered case only (no general emptyText yet).
            no_matches.setVisible(s.no_matches)
            color_hint.setVisible(s.color_filter is not None)
            if s.color_filter:
                # .row-color
                color_swatch.setStyleSheet(
                    f"background: {s.color_filter}; border: 1px solid rgba(0, 0, 0, 0.5); border-radius: 2px;"
                )
            # {sortable && hiding && .pane-hint}: exactly when drag is off.
            if drag_hint is not None:
                drag_hint.setVisible(s.hiding)

        mod_list = ModListView(
            self._mod_display_name,
            draggable=draggable,
            name=title,
            matches=self._mod_matches,
            color=self._mod_color,
            on_search_changed=on_search_changed,
            decor=self._row_decor,
            tooltip=self._row_tooltip,
            # The Active rows' issue icons (ModList.jsx issuesByMod / onShowIssue).
            issues=(lambda mod_id: self._issues_by_mod.get(mod_id, [])) if issue_icons else None,
            on_show_issue=(lambda key: self._show_validation(key=key)) if issue_icons else None,
            scanned_mods=(lambda: self._mods) if issue_icons else None,
            # The pending rows' Subscribe button (ModList.jsx onSubscribe).
            on_subscribe=self._subscribe if subscribe else None,
            subscribe_tooltip=self._subscribe_tooltip if subscribe else None,
            subscribe_enabled=self._subscribe_ready if subscribe else None,  # ModList.jsx canSubscribe
        )
        mod_list.setEnabled(False)
        mod_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        mod_list.customContextMenuRequested.connect(lambda pos: self._show_mod_menu(mod_list, search, pos))
        # the dot grid inside the list while it shows no rows (painters.py)
        painters.install_empty_grid(mod_list.viewport(), lambda: painters.list_is_empty(mod_list))
        # .list-empty (absolute, inset 12px, centered, --muted) over the list:
        # both in one grid cell, the label on top and click-through.
        list_cell = QGridLayout()
        list_cell.setContentsMargins(0, 0, 0, 0)
        list_cell.addWidget(mod_list, 0, 0)
        no_matches = _label("No matches", muted=True)
        no_matches.setContentsMargins(12, 12, 12, 12)
        no_matches.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        no_matches.setVisible(False)
        list_cell.addWidget(no_matches, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(list_cell, 1)
        # .pane-hint below the list, sortable (Active) pane only.
        drag_hint = None
        if draggable:
            drag_hint = _label("Clear the filter to drag-reorder.", muted=True)
            drag_hint.setVisible(False)
            layout.addWidget(drag_hint)
        # Per pane, never persisted (ModList.jsx useState).
        search.textChanged.connect(lambda text: mod_list.set_search(query=text))
        eye.triggered.connect(lambda: mod_list.set_search(dim=not mod_list.search.dim))
        on_search_changed()  # "{title} [0]" until the first scan fills the pane
        return pane, search, eye, mod_list

    # .actions-column (ActionsColumn.jsx)
    def _build_actions_column(self) -> QFrame:
        column = _panel()
        column.setFixedWidth(ACTIONS_WIDTH)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        self.import_button = _button("Import...")
        self.import_button.setToolTip(
            "Replace the active list with one from the clipboard, a RimPy .xml file, a rentry.co page or a save. "
            "Undoable; not saved until you Save."
        )
        self.export_button = _button("Export...")
        self.export_button.setToolTip(
            "Share the active list: copy it in RimSort/rentry.co format, or save it as a RimPy .xml file."
        )
        layout.addLayout(self._group(self.import_button, self.export_button))

        self.rescan_button = _button("Rescan")
        layout.addLayout(self._group(self.rescan_button))

        self.sort_button = _button("Sort")
        self.save_button = _button("Save")
        self.sync_button = _button("Sync")
        layout.addLayout(self._group(self.sort_button, self.save_button, self.sync_button))

        layout.addStretch(1)  # .spacer

        # "N scan issues" (shown only while there are any - _update_scan_issues_button),
        # then the merged warnings/errors button - hidden at 0/0, as in the real app.
        self.scan_issues_button = _button("", variant="issue-count")
        self.scan_issues_button.setProperty("scan", True)
        self.scan_issues_button.setToolTip("Show scan issues")
        self.scan_issues_button.setEnabled(True)
        self.scan_issues_button.setVisible(False)
        self.issues_button = self._build_issue_count_button()
        self.issues_button.setVisible(False)
        layout.addLayout(self._group(self.scan_issues_button, self.issues_button))

        self.push_button = _button("Push", variant="accent-outline")
        self.run_button = _button("Run", variant="primary")
        layout.addLayout(self._group(self.push_button, self.run_button))
        return column

    @staticmethod
    def _group(*buttons: QPushButton) -> QVBoxLayout:
        group = QVBoxLayout()  # .actions-group
        group.setSpacing(8)
        for button in buttons:
            group.addWidget(button)
        return group

    @staticmethod
    def _build_issue_count_button() -> QPushButton:
        # QPushButton can't color parts of its text, so the colored
        # "⚠ N · ✕ M" is a rich-text label laid over an empty button
        # (_update_issues_button sets the live counts).
        button = _button("", variant="issue-count")
        button.setToolTip("Show warnings and errors")
        button.setEnabled(True)
        label = QLabel(_issue_count_html(0, 0))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner = QHBoxLayout(button)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(label)
        return button

    # ---- footer: .action-divider + footer.statusbar (App.jsx) ----
    def _build_footer(self) -> QWidget:
        """The screen's last two rows, as App.jsx renders them: the 1px
        .action-divider (12px in from each side) over footer.statusbar - a
        row (padding 4px 12px 14px, 12px text) of the status text (flex: 1,
        one line, elided; set_status_text - App.jsx say(), Run / Push's
        success messages so far) and, docked right,
        the SteamCMD download row (DownloadBar; hidden until a download
        starts - _render_download_bar). Always present, as in Electron, so
        a download appearing doesn't move the content row by the footer's
        height (it does grow by the button's extra height, also as in
        Electron: the row is 24px tall, the text ~17px)."""
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        divider = QFrame()
        divider.setObjectName("actionDivider")
        divider.setFixedHeight(1)
        divider_row = QHBoxLayout()
        divider_row.setContentsMargins(BAR_SIDE, 0, BAR_SIDE, 0)  # .action-divider margin: 0 12px
        divider_row.addWidget(divider)
        column.addLayout(divider_row)
        footer = QFrame()
        footer.setObjectName("statusBar")
        row = QHBoxLayout(footer)
        row.setContentsMargins(BAR_SIDE, 4, BAR_SIDE, 14)  # .statusbar padding: 4px 12px 14px
        row.setSpacing(0)  # no gap: .dl-bar brings its own margin-left
        prompt = QLabel(">")  # the copper terminal prompt (design step 3.4)
        prompt.setProperty("role", "status-prompt")
        row.addWidget(prompt)
        self.status_text = _StatusText()
        row.addWidget(self.status_text, 1)
        self.download_bar = DownloadBar()
        self.download_bar.setVisible(False)
        row.addWidget(self.download_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(footer)
        return box
