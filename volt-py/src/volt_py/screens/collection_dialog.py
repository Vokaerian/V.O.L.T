"""Import from Steam Workshop dialog (port of Electron's
src/renderer/src/components/CollectionDialog.jsx, the "From Steam Workshop..."
entry of Import...). Same .modal family as the other dialogs: a URL / id
input, a preview once it resolves, then Cancel plus Add to list / Replace
list / New load order... for a collection (the chosen button's mode rides in
the payload), or a single Import for a single mod.

The input resolves by itself RESOLVE_DELAY_MS after typing / pasting stops
(Enter resolves at once), through steam_web_api.resolve_collection on a
daemon thread - the community-rules / SteamCMD pattern: a QObject carrier's
queued signal brings the reply back to the GUI thread, and a sequence number
(LookupState.seq) drops a reply for text that has changed since. The import
buttons are only enabled while the preview matches the current input; Enter
then submits the first one, the non-destructive Add to list (Import for a
single mod). Each item is matched against the scan with the same lookup the
rentry import uses (mod_list_io.resolve_workshop_placeholders): installed ->
its packageId, anything else -> a "workshop:<id>" pending placeholder. A
single mod's URL / id works too: resolve_collection returns it as a one-item
collection (single=True), shown and imported the same way.

Before the dialog accepts, `may_import(payload)` - the screen's gate - runs:
a collection's Replace list / New load order... asks to discard unsaved
changes there; declining keeps this dialog open (App.jsx onCollectionImport).
The screen reads `payload` after exec() and applies it
(RimWorldMainScreen._on_collection_import).

The pure helpers at the top (no Qt: the preview counts, the texts, the
payload, LookupState) are what tools/checks/volt_py_steam_web_api.py tests
directly; it also runs the dialog's own methods on a stub.
"""

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from volt_py import mod_list_io
from volt_py.applog import clip, log

RESOLVE_DELAY_MS = 500
WIDTH = 420  # .modal: width 420px, max-width calc(100vw - 32px)

TITLE = "Import from Steam Workshop"
INTRO = (
    "Paste a Steam Workshop collection's URL, or just its id (a single mod's link or id works too). "
    "Installed mods are added as they are; the rest are added as pending, ready to Subscribe."
)
PLACEHOLDER = "https://steamcommunity.com/sharedfiles/filedetails/?id=..."
LOOKING_UP = "Looking it up on Steam..."
MODES = (("add", "Add to list"), ("replace", "Replace list"), ("new", "New load order..."))


# ---- pure logic (no Qt) ----
def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many if many is not None else one + 's')}"


def preview_of(value: dict, mods: dict) -> dict:
    """CollectionDialog.jsx's `preview` memo over a resolved collection:
    {"ids": the import's ids (packageIds / "workshop:<id>" placeholders),
    "total", "pending", "installed", "unavailable": pending items Steam no
    longer returns (removed / private / banned) - Subscribe can't fetch
    these}."""
    items = value["items"]
    r = mod_list_io.resolve_workshop_placeholders([f"workshop:{it['id']}" for it in items], mods, keep_unmatched=True)
    pending_ids = set(r["ids"])
    return {
        "ids": r["ids"],
        "total": len(items),
        "pending": r["pending"],
        "installed": len(items) - r["pending"],
        "unavailable": sum(
            1 for it in items
            if it.get("details") and not it["details"]["found"] and f"workshop:{it['id']}" in pending_ids
        ),
    }


def preview_line(preview: dict) -> str:
    """`N items — I installed, P pending`."""
    return f"{plural(preview['total'], 'item')} — {preview['installed']} installed, {preview['pending']} pending"


def notes_line(preview: dict, value: dict) -> str:
    """The unavailable-items / skipped-nested-collections / details-error
    notes, joined with a space; "" when there's nothing to note."""
    notes = []
    if preview["unavailable"] > 0:
        notes.append(
            f"{plural(preview['unavailable'], 'item')} Steam no longer lists (removed, private or banned) "
            "can't be subscribed to."
        )
    skipped = value["skipped_collections"]
    if skipped > 0:
        notes.append(
            f"{plural(skipped, 'nested collection')} couldn't be read and {'was' if skipped == 1 else 'were'} left out."
        )
    if value["details_error"]:
        notes.append(f"Couldn't load the item names ({value['details_error']}); pending items will show their Workshop id.")
    return " ".join(notes)


def import_payload(value: dict, preview: dict, mode: str) -> dict:
    """What onImport gets: the resolved collection plus the matched ids, the
    pending count and the chosen mode ('add' | 'replace' | 'new'; a single
    mod's Import submits as 'add', the implicit default, as the JS)."""
    return {**value, "ids": preview["ids"], "pending": preview["pending"], "mode": mode}


class LookupState:
    """CollectionDialog.jsx's `res` + `seq`: status 'idle' | 'resolving' |
    'ok' (value) | 'error' (message), and the sequence number every edit or
    resolve bumps so a reply for older text is ignored."""

    def __init__(self) -> None:
        self.status = "idle"
        self.value: dict | None = None
        self.message: str | None = None
        self.seq = 0

    def edited(self, text: str) -> bool:
        """The input changed: back to idle, any reply in flight is stale.
        True when a resolve should be scheduled (the text isn't blank)."""
        self.seq += 1
        self.status, self.value, self.message = "idle", None, None
        return bool(text.strip())

    def start(self, text: str) -> tuple[int, str] | None:
        """Resolve now: (seq, query) to look up, or None for a blank input
        (which just goes idle)."""
        self.seq += 1
        q = text.strip()
        if not q:
            self.status, self.value, self.message = "idle", None, None
            return None
        self.status, self.value, self.message = "resolving", None, None
        return self.seq, q

    def finish(self, seq: int, value: dict | None = None, error: str | None = None) -> bool:
        """A reply arrived. False (ignored) when it's for an older text."""
        if seq != self.seq:
            return False
        if error is not None:
            self.status, self.value, self.message = "error", None, error
        else:
            self.status, self.value, self.message = "ok", value, None
        return True


# ---- the lookup thread ----
class _LookupDone(QObject):
    """Carries one Steam lookup's outcome from its thread to the GUI thread
    (a queued connection). Payload: {"seq", "value", "error", "carrier"}."""

    done = Signal(object)


def _lookup(resolve: Callable[[str], dict], query: str, seq: int, carrier: _LookupDone) -> None:
    """Thread body: one resolve(query), then `carrier.done`. Any exception
    becomes the error message (the thread must never die silently)."""
    value, error = None, None
    try:
        value = resolve(query)
    except Exception as err:  # SteamWebApiError / ValueError, or anything unexpected
        error = str(err) or repr(err)
    try:
        carrier.done.emit({"seq": seq, "value": value, "error": error, "carrier": carrier})
    except RuntimeError as err:  # shutting down: the Qt side is already gone
        log(f"steam workshop import: could not signal the dialog ({err!r})")


# ---- the dialog ----
def _button(text: str, variant: str | None = None) -> QPushButton:
    button = QPushButton(text)
    # No Enter-activates-default: Enter belongs to the input (returnPressed),
    # which resolves or submits the first button itself, as the JS form does.
    button.setAutoDefault(False)
    if variant:
        button.setProperty("variant", variant)
    return button


def _label(text: str = "", *, role: str | None = None, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)  # titles / error texts are data, never rich text
    label.setWordWrap(True)
    if role:
        label.setProperty("role", role)
    if muted:
        label.setProperty("muted", True)
    return label


class CollectionDialog(QDialog):
    def __init__(
        self,
        mods: dict,
        resolve: Callable[[str], dict],
        may_import: Callable[[dict], bool],
        parent: QWidget | None = None,
    ) -> None:
        """mods: the screen's scanned mods (id -> mod), for the installed /
        pending split; never modified. resolve(query) -> steam_web_api
        .resolve_collection's dict (raises on failure); runs on a worker
        thread. may_import(payload) -> bool: the screen's gate before the
        dialog accepts (False keeps it open)."""
        super().__init__(parent)
        self.setObjectName("collectionImport")
        self.setWindowTitle(TITLE)
        self.setModal(True)
        self._mods = mods
        self._resolve = resolve
        self._may_import = may_import
        self._state = LookupState()
        self._preview: dict | None = None
        self.payload: dict | None = None
        # Each lookup in flight: its carrier (kept alive until its queued
        # `done` has been delivered) and its thread.
        self._lookups: dict[_LookupDone, threading.Thread] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RESOLVE_DELAY_MS)
        self._timer.timeout.connect(lambda: self._resolve_now())

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = _label(TITLE, role="modal-title")
        layout.addWidget(title)
        layout.addWidget(_label(INTRO, muted=True))
        self.input = QLineEdit()
        self.input.setPlaceholderText(PLACEHOLDER)
        layout.addWidget(self.input)
        self.status_label = _label(muted=True)  # "Looking it up on Steam..." / the error (role modal-error)
        self.title_label = _label(role="collection-title")
        self.preview_label = _label()
        self.notes_label = _label(muted=True)
        for label in (self.status_label, self.title_label, self.preview_label, self.notes_label):
            label.setVisible(False)
            layout.addWidget(label)

        buttons = QHBoxLayout()  # .button-row.end: right-aligned, 8px apart
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.cancel_button = _button("Cancel")
        buttons.addWidget(self.cancel_button)
        self.import_button = _button("Import", "primary")
        buttons.addWidget(self.import_button)
        self.mode_buttons: dict[str, QPushButton] = {}
        for mode, text in MODES:
            button = _button(text, "primary" if mode == "add" else None)
            button.clicked.connect(lambda _checked=False, mode=mode: self._submit(mode))
            buttons.addWidget(button)
            self.mode_buttons[mode] = button
        layout.addLayout(buttons)

        self.cancel_button.clicked.connect(lambda: self.reject())  # Esc rejects too (QDialog default)
        self.import_button.clicked.connect(lambda: self._submit("add"))
        self.input.textChanged.connect(lambda text: self._on_text_changed(text))
        self.input.returnPressed.connect(lambda: self._on_return_pressed())

        width = WIDTH
        if parent is not None:
            width = min(width, parent.window().width() - 32)
        self.setFixedWidth(width)
        self._render()
        self.input.setFocus()

    # ---- input -> lookup ----
    def _on_text_changed(self, text: str) -> None:
        """Typing / pasting: back to idle at once (any reply in flight is for
        the old text), a resolve RESOLVE_DELAY_MS after the last change."""
        if self._state.edited(text):
            self._timer.start()  # restarts the delay
        else:
            self._timer.stop()
        self._render()

    def _on_return_pressed(self) -> None:
        """Enter: with a preview, the implicit submit - the first button (Add
        to list, or Import for a single mod); before one exists, resolve now
        (unless a lookup is already running)."""
        if self._preview is not None:
            self._submit("add")
        elif self._state.status != "resolving":
            self._resolve_now()

    def _resolve_now(self) -> None:
        self._timer.stop()
        started = self._state.start(self.input.text())
        self._render()
        if started is None:
            return
        seq, query = started
        log(f"steam workshop import: resolving {query!r} (lookup {seq})")
        carrier = _LookupDone()  # no parent: owned by _lookups and the thread
        carrier.done.connect(self._on_lookup_done, Qt.ConnectionType.QueuedConnection)
        thread = threading.Thread(
            target=_lookup, args=(self._resolve, query, seq, carrier), name=f"steam-lookup-{seq}", daemon=True
        )
        self._lookups[carrier] = thread
        thread.start()

    @Slot(object)
    def _on_lookup_done(self, result: dict) -> None:
        """A lookup finished (on the GUI thread, via a queued connection)."""
        self._lookups.pop(result.get("carrier"), None)
        seq = result["seq"]
        if not self._state.finish(seq, result["value"], result["error"]):
            log(f"steam workshop import: lookup {seq} finished after the input changed, ignored")
            return
        if result["error"] is not None:
            log(f"steam workshop import: lookup {seq} failed: {result['error']}")
        else:
            v = result["value"]
            log(
                f"steam workshop import: lookup {seq} resolved {v['collection_id']} "
                f"({'single mod' if v.get('single') else 'collection'} {v['title']!r}, {len(v['items'])} items, "
                f"{v['nested_collections']} nested expanded, {v['skipped_collections']} skipped"
                f"{', details error: ' + v['details_error'] if v['details_error'] else ''})"
            )
        self._render()

    # ---- state -> widgets ----
    def _render(self) -> None:
        st = self._state
        v = st.value if st.status == "ok" else None
        self._preview = preview_of(v, self._mods) if v else None
        if st.status == "resolving":
            self._set_status(LOOKING_UP, error=False)
        elif st.status == "error":
            self._set_status(st.message or "", error=True)
        else:
            self.status_label.setVisible(False)
        has_title = bool(v and v["title"])
        self.title_label.setText(v["title"] if has_title else "")
        self.title_label.setVisible(has_title)
        if self._preview is not None:
            self.preview_label.setText(preview_line(self._preview))
            notes = notes_line(self._preview, v)
            self.notes_label.setText(notes)
            self.notes_label.setVisible(bool(notes))
        else:
            self.notes_label.setVisible(False)
        self.preview_label.setVisible(self._preview is not None)
        single = bool(v and v.get("single"))
        enabled = self._preview is not None
        self.import_button.setVisible(single)
        self.import_button.setEnabled(enabled)
        for button in self.mode_buttons.values():
            button.setVisible(not single)
            button.setEnabled(enabled)
        self._fit_height()

    def _fit_height(self) -> None:
        """The fixed width stays; the height follows the labels shown - sized
        for that width. Not adjustSize(): its height is for sizeHint()'s
        width (~80 chars, wider than WIDTH, so fewer wrapped lines), and its
        layout activation first grows the window to the minimum size, where a
        wrapped label counts as one line; on Windows Qt's own height-for-width
        correction (WM_WINDOWPOSCHANGING) then fixes either size up and logs
        "QWindowsWindow::setGeometry: Unable to set geometry ..." - harmless,
        but noise on every keystroke. Growing first, activating second keeps
        that correction idle: the window is already the height the layout
        will ask for."""
        layout = self.layout()
        w = self.width()
        h = layout.totalHeightForWidth(w) if layout.hasHeightForWidth() else layout.totalSizeHint().height()
        if h > self.height():
            self.resize(w, h)
        layout.activate()  # the new minimum before shrinking, as adjustSize() does
        self.resize(w, h)

    def _set_status(self, text: str, *, error: bool) -> None:
        """.modal p (muted) for the in-progress line, .modal p.error (--danger)
        for a failure."""
        self.status_label.setText(text)
        self.status_label.setProperty("muted", not error)
        self.status_label.setProperty("role", "modal-error" if error else "modal-text")
        self.status_label.style().unpolish(self.status_label)  # property selectors aren't re-evaluated on their own
        self.status_label.style().polish(self.status_label)
        self.status_label.setVisible(True)

    # ---- submit ----
    def _submit(self, mode: str) -> None:
        if self._preview is None or self._state.value is None:
            return
        payload = import_payload(self._state.value, self._preview, mode)
        log(
            f"steam workshop import: {mode} clicked for {payload['collection_id']} "
            f"({len(payload['ids'])} ids, {payload['pending']} pending): {clip(payload['ids'])}"
        )
        if not self._may_import(payload):
            log("steam workshop import: not applied (declined at the discard-changes prompt), dialog stays open")
            return
        self.payload = payload
        self.accept()
