"""Self-update UI (0.6.30, PLAN.md §12, dispatch 2; the logic is
volt_py/update.py, the words + Qt-free decisions volt_py/update_flow.py).

- UpdateDialog: one modal dialog, four states on a QStackedWidget (each
  change under painters.crossfade): (a) "VOLT X is available (you have Y)",
  the release notes (update_flow.notes_text -> help_window.TextBlocks in a
  --panel-2 well) and Update now (primary, the default: Enter) / Later (Esc)
  / Skip this version (writes skipped_tag); (b) downloading: the footer
  download bar's striped track (download_bar._Track, stretched to the
  dialog's width) + "done of total MB" + Cancel (Esc too); (c) checking and
  unpacking; (d) "Restarting VOLT..." -> write_apply_script(stage(...),
  base) -> launch_apply() -> QApplication.exit(0) at once (apply.bat waits
  for VOLT.exe to unlock; exit, not quit: Qt 6's quit() first asks every
  window to close and this dialog refuses while restarting, which would
  cancel the quit). download + stage run on one worker thread
  (start_job: a daemon threading.Thread, results over queued signals - the
  managers' _JobDone pattern). A failure is the friendly error box and the
  dialog goes back to (a), still usable.
  can_self_update False (dev run, no digest, unwritable folder, non-Windows):
  the primary button is "Open releases page" and the reason shows under the
  headline.
- Busy rule (SCOPE.md §3): VOLT can't restart while the open manager couldn't
  go back to game select (its Games button disabled: a job, a running game,
  a SteamCMD download...). Update now is then disabled, the reason (the Games
  button's own tooltip, reworded: update_flow.busy_text) is its tooltip and
  the dialog's reason line, re-read every BUSY_POLL_MS. Unsaved changes: the
  manager's own Discard confirm when Update now is pressed, before anything
  downloads.
- update_flow.startup_work + show_failed_apply / show_update: MainWindow's
  once-per-start check (a worker; silent on any failure): cleanup_leftovers()
  (its failed-copy report as a notice), then, when check_on_startup, fetch_latest() -> a
  newer, not-skipped release opens the dialog. MainWindow only opens it on
  the game select screen (held until the user goes back there).

Logging: every step logs via applog.log, which is a no-op until a manager
calls init_log - so the startup check (game select, before any game opens)
leaves no lines; the manual check from Settings does (a manager is open).
"""

import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from volt_py import app_root, painters, theme, update
from volt_py import update_flow as w
from volt_py.applog import log
from volt_py.screens.download_bar import TRACK_HEIGHT, _Track
from volt_py.screens.error_box import show_error
from volt_py.screens.help_window import TextBlocks

STARTUP_DELAY_MS = 1000  # after the first show: the check never delays the window
BUSY_POLL_MS = 1000  # a job / the game can finish while the dialog is open
RESTART_PAUSE_MS = 400  # "Restarting VOLT..." is on screen before VOLT closes
DIALOG_WIDTH = 520
NOTES_MIN_HEIGHT = 140  # the well scrolls: a short body leaves room, a long one scrolls
NOTES_MAX_HEIGHT = 260


# ---- background work ----
class _Job(QObject):
    """Carries a worker's events to the GUI thread (queued connections).
    Parented to its owner: closing the owner drops what's still to come."""

    done = Signal(object)  # {"ok": result} or {"error": exception}
    progress = Signal(object, object)  # bytes done, total (None when unknown)
    phase = Signal(str)


def start_job(owner: QObject, name: str, fn, on_done, *, on_progress=None, on_phase=None) -> _Job:
    """fn(job) on a daemon thread; on_done({"ok": result} / {"error": exc})
    on the GUI thread. Pass bound methods of `owner` (Qt drops them with it)."""
    job = _Job(owner)
    job.done.connect(on_done, Qt.ConnectionType.QueuedConnection)
    if on_progress is not None:
        job.progress.connect(on_progress, Qt.ConnectionType.QueuedConnection)
    if on_phase is not None:
        job.phase.connect(on_phase, Qt.ConnectionType.QueuedConnection)

    def run() -> None:
        try:
            payload = {"ok": fn(job)}
        except Exception as err:  # every failure reaches the GUI; nothing crashes the thread
            log(f"[update] job {name} failed: {err!r}")
            payload = {"error": err}
        try:
            job.done.emit(payload)
        except RuntimeError:  # the owner (and so the job) is gone: nobody to tell
            pass

    threading.Thread(target=run, name=name, daemon=True).start()
    log(f"[update] job {name} started")
    return job


# ---- the busy rule (the managers' Games button, SCOPE.md §3) ----
def find_manager(widget: QWidget | None):
    """The open manager screen (it has games_button + _confirm_discard) at or
    above `widget`, or the main window's central one; None on game select."""
    while widget is not None:
        if hasattr(widget, "games_button") and hasattr(widget, "_confirm_discard"):
            return widget
        if isinstance(widget, QMainWindow):
            central = widget.centralWidget()
            return central if hasattr(central, "games_button") and hasattr(central, "_confirm_discard") else None
        widget = widget.parentWidget()
    return None


def block_reason(manager) -> str | None:
    if manager is None:
        return None
    try:
        if manager.games_button.isEnabled():
            return None
        return w.busy_text(manager.games_button.toolTip())
    except RuntimeError:  # the screen was deleted
        return None


def _label(text: str = "", *, role: str | None = None, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if role:
        label.setProperty("role", role)
    if muted:
        label.setProperty("muted", True)
    return label


def _button(text: str, *, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    if primary:
        button.setProperty("variant", "primary")
    button.setAutoDefault(primary)  # only the primary takes Enter, wherever the focus is
    return button


def _work(release: update.Release, cancel: threading.Event):
    def fn(job: _Job):
        if not w.CLEANUP_DONE.wait(w.CLEANUP_WAIT_S):
            log("[update] startup cleanup still running after "
                f"{w.CLEANUP_WAIT_S}s; downloading anyway")
        zip_path = update.download(release, progress_cb=job.progress.emit, cancel_event=cancel)
        if zip_path is None:
            return None
        job.phase.emit("unpack")
        return update.stage(zip_path)
    return fn


class UpdateDialog(QDialog):
    """See the module docstring. source: "startup" / "manual" (logs only)."""

    def __init__(self, release: update.Release, parent: QWidget | None = None, *, source: str = "manual") -> None:
        super().__init__(parent)
        self.setObjectName("update")
        self.setWindowTitle(w.TITLE)
        self.setModal(True)
        self._release = release
        self._source = source
        self._current = update.current_version()
        self._manager = find_manager(parent)
        self._can, self._why_not = update.can_self_update(release)
        self._cancel: threading.Event | None = None
        self._phase = "offer"  # offer / download / unpack / restart
        self._job: _Job | None = None

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel(w.TITLE)
        title.setProperty("role", "modal-title")
        layout.addWidget(title)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_offer())
        self._stack.addWidget(self._build_progress())
        layout.addWidget(self._stack, 1)
        self.setFixedWidth(DIALOG_WIDTH)

        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(BUSY_POLL_MS)
        self._busy_timer.timeout.connect(self._apply_busy)
        self._apply_busy()
        self._busy_timer.start()
        self.update_button.setFocus()
        log(f"[update] dialog opened ({source}): {release.tag} offered, running {self._current}, "
            f"can self-update: {self._can}{'' if self._can else ' - ' + self._why_not}")

    # ---- pages ----
    def _build_offer(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        col.addWidget(_label(w.headline(self._release.version, self._current), role="first-run-title"))
        self.reason = _label(muted=True)
        col.addWidget(self.reason)
        col.addSpacing(4)
        col.addWidget(painters.TerminalLabel(w.NOTES_HEADING, rule="side"))
        notes = QScrollArea()
        notes.setObjectName("updateNotes")
        notes.setWidgetResizable(True)
        notes.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        box = QVBoxLayout(inner)
        box.setContentsMargins(12, 10, 12, 10)
        text = w.notes_text(self._release.notes)
        body = TextBlocks(muted=not text)
        body.setText(text or w.NO_NOTES)
        box.addWidget(body)
        box.addStretch(1)
        notes.setWidget(inner)
        notes.viewport().setAutoFillBackground(False)  # the QSS well shows through (help_window._transparent)
        inner.setAutoFillBackground(False)
        notes.setMinimumHeight(NOTES_MIN_HEIGHT)
        notes.setMaximumHeight(NOTES_MAX_HEIGHT)
        col.addWidget(notes, 1)

        self.skip_button = _button(w.SKIP)
        self.later_button = _button(w.LATER)
        self.update_button = _button(w.UPDATE_NOW if self._can else w.OPEN_PAGE, primary=True)
        self.update_button.setDefault(True)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.skip_button)
        row.addStretch(1)
        row.addWidget(self.later_button)
        row.addWidget(self.update_button)
        col.addSpacing(4)
        col.addLayout(row)
        self.skip_button.clicked.connect(self._skip)
        self.later_button.clicked.connect(self.reject)  # Esc too (reject)
        self.update_button.clicked.connect(self._update_now)
        return page

    def _build_progress(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        self.progress_title = _label(role="first-run-title")
        col.addWidget(self.progress_title)
        self.track = _Track()
        self.track.setAccessibleName("Update download progress")
        self.track.setMinimumWidth(0)
        self.track.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX: the full dialog width, not the footer's 140px
        self.track.setFixedHeight(TRACK_HEIGHT)
        self.track.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        col.addWidget(self.track)
        self.progress_detail = _label(muted=True)
        col.addWidget(self.progress_detail)
        col.addStretch(1)
        self.cancel_button = _button(w.CANCEL)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.cancel_button)
        col.addLayout(row)
        self.cancel_button.clicked.connect(self._request_cancel)
        return page

    # ---- state ----
    def _show_page(self, index: int) -> None:
        if self._stack.currentIndex() != index:
            painters.crossfade(self, lambda: self._stack.setCurrentIndex(index), theme.MOTION)

    def _apply_busy(self) -> None:
        """Update now's enabled state + the reason line, from can_self_update
        and the busy rule (re-read every BUSY_POLL_MS while offering)."""
        if self._phase != "offer":
            return
        why = None if not self._can else block_reason(self._manager)
        enabled = why is None
        if self.update_button.isEnabled() != enabled:
            log(f"[update] dialog: Update now {'enabled' if enabled else 'disabled - ' + why}")
        self.update_button.setEnabled(enabled)
        self.update_button.setToolTip(why or ("" if self._can else update.RELEASES_PAGE))
        text = self._why_not if not self._can else (why or "")
        if self.reason.text() != text or self.reason.isVisibleTo(self) != bool(text):
            self.reason.setText(text)
            self.reason.setVisible(bool(text))
            # A top-level window doesn't follow a wrapped label's height-for-width on its own: re-fit
            # the height (the width is fixed) so a 2-3 line reason is never clipped.
            self.adjustSize()

    def _to_offer(self) -> None:
        self._phase = "offer"
        self._job = None
        self._apply_busy()
        self._show_page(0)
        self.update_button.setFocus()

    def _set_phase(self, phase: str) -> None:
        self._phase = phase
        titles = {"download": w.downloading(self._release.version), "unpack": w.UNPACKING, "restart": w.RESTARTING}
        def swap() -> None:
            self.progress_title.setText(titles[phase])
            if phase == "download":
                self.track.set_percent(0, animate=False)
                self.progress_detail.setText(w.progress_text(0, self._release.asset_size))
            elif phase == "unpack":
                self.track.set_percent(100, animate=False)
                self.progress_detail.setText(w.UNPACKING_DETAIL)
            else:
                self.progress_detail.setText(w.RESTARTING_DETAIL)
            self.cancel_button.setText(w.CANCEL)
            self.cancel_button.setEnabled(phase == "download")
            self.cancel_button.setVisible(phase == "download")
            self._stack.setCurrentIndex(1)
        if self._stack.currentIndex() == 1:
            painters.crossfade(self, swap, theme.MOTION_FAST)
        else:
            painters.crossfade(self, swap, theme.MOTION)

    # ---- actions ----
    def _skip(self) -> None:
        log(f"[update] dialog: Skip this version ({self._release.tag})")
        try:
            update.save_state({"skipped_tag": self._release.tag})
        except OSError as err:
            log(f"[update] couldn't save skipped_tag {self._release.tag}: {err!r} (it will be offered again)")
        super().reject()  # the plain close (this class's reject() is Esc / Later)

    def _update_now(self) -> None:
        if not self._can:
            log(f"[update] dialog: Open releases page ({update.RELEASES_PAGE}); reason: {self._why_not}")
            QDesktopServices.openUrl(QUrl(update.RELEASES_PAGE))
            self.accept()
            return
        why = block_reason(self._manager)
        if why:
            log(f"[update] dialog: Update now refused: {why}")
            self._apply_busy()
            return
        if self._manager is not None and not self._manager._confirm_discard():
            log("[update] dialog: Update now cancelled at the unsaved-changes confirm")
            return
        log(f"[update] dialog: Update now - downloading {self._release.tag} ({self._release.asset_size} bytes)")
        self._cancel = threading.Event()
        self._set_phase("download")
        self.cancel_button.setFocus()
        self._job = start_job(self, "update-download", _work(self._release, self._cancel), self._on_done,
                              on_progress=self._on_progress, on_phase=self._on_phase)

    def _request_cancel(self) -> None:
        if self._phase != "download" or self._cancel is None or self._cancel.is_set():
            return
        log("[update] dialog: Cancel pressed - stopping the download")
        self._cancel.set()
        self.cancel_button.setText(w.CANCELLING)
        self.cancel_button.setEnabled(False)

    def _on_progress(self, done, total) -> None:
        if self._phase != "download":
            return
        self.track.set_percent(w.percent(done, total))
        self.progress_detail.setText(w.progress_text(done, total))

    def _on_phase(self, phase: str) -> None:
        if phase == "unpack" and self._phase == "download":
            log("[update] dialog: download verified, unpacking")
            self._set_phase("unpack")

    def _on_done(self, payload: dict) -> None:
        if "error" in payload:
            err = payload["error"]
            known = isinstance(err, update.UpdateError)
            log(f"[update] dialog: update failed: {err!r}")
            self._to_offer()
            show_error(self, w.ERROR_TITLE, str(err) if known else "The update stopped because of an unexpected error.",
                       means="" if known else "Nothing was changed. VOLT is still the version you have.",
                       tryit="" if known else "Try again. If it keeps happening, use the releases page instead.",
                       details=f"{err!r}" + (f"\ncaused by {err.__cause__!r}" if err.__cause__ else ""),
                       log_prefix="[update] ")
            return
        app_dir = payload["ok"]
        if app_dir is None:
            log("[update] dialog: download cancelled; back to the offer")
            self._to_offer()
            return
        why = block_reason(self._manager)
        if why:  # something started while the download ran (a game launched before the dialog opened, say)
            log(f"[update] dialog: ready to restart but refused: {why}")
            self._to_offer()
            show_error(self, w.ERROR_TITLE, "The update is downloaded, but VOLT can't restart right now.",
                       means=why, tryit="Press \"Update now\" again once that's finished.", log_prefix="[update] ")
            return
        self._set_phase("restart")
        QTimer.singleShot(RESTART_PAUSE_MS, lambda: self._apply(app_dir))

    def _apply(self, app_dir) -> None:
        base = app_root.resolve_base_root()
        try:
            bat = update.write_apply_script(app_dir, base)
            update.launch_apply(bat)
        except OSError as err:
            log(f"[update] dialog: couldn't start the update copy: {err!r}")
            self._to_offer()
            show_error(self, w.ERROR_TITLE, "VOLT couldn't start copying the update.",
                       means="Nothing was changed. VOLT is still the version you have.",
                       tryit="Try again. If it keeps happening, use the releases page instead.",
                       details=f"{err!r}", log_prefix="[update] ")
            return
        log(f"[update] dialog: restarting into {self._release.tag} - quitting VOLT now")
        QApplication.exit(0)  # every event loop (this dialog's, Settings', the main one) ends; aboutToQuit still runs

    # ---- closing ----
    def reject(self) -> None:
        """Esc / the window's X: Later while offering, Cancel while
        downloading, nothing once unpacking / restarting."""
        if self._phase == "download":
            self._request_cancel()
            return
        if self._phase != "offer":
            return
        log(f"[update] dialog: Later ({self._release.tag})")
        super().reject()

    def done(self, result: int) -> None:
        self._busy_timer.stop()
        super().done(result)


# ---- startup check (MainWindow; the work itself: update_flow.startup_work) ----
def show_failed_apply(parent: QWidget, report: str) -> None:
    what, means, tryit = w.failed_apply(report)
    show_error(parent, w.FAILED_APPLY_TITLE, what, means=means, tryit=tryit, details=report.strip(),
               log_prefix="[update] ")


def show_update(parent: QWidget, release: update.Release, source: str) -> None:
    UpdateDialog(release, parent, source=source).exec()
    log("[update] dialog closed")
