"""Offline mods... (RimWorld, 0.6.16; RIMWORLD.md PLAN item 10 stage 2): the
actions column's button under Rescan (shown only while the open load order
has its own game data on). A searchable checklist of every mod of
the open load order (Active, then Inactive, then any Offline entry neither
pane lists); a ticked row is (or becomes) Offline. Rows that can't be made
Offline (official Core / DLC, pending Workshop items, not-installed rows,
mods without a packageId, unreadable folders - offline_mods.refusal) are
shown disabled, the reason as their tooltip. A row that is Offline now can
always be unticked (= Make live again).

Columns: the mod (checkbox + name), its packageId, where it comes from
(SOURCE_LABEL), Live (an Offline row's live-changed status: Same / Changed /
Not installed / ?, 0.6.18 - "Refresh changed" re-copies every Changed one
after the screen's confirm, only with no ticks pending) and its size, measured off the GUI thread (offline_mods
.size_of, cancelled when the dialog closes; "..." until known; ticked rows
are measured first; "-" for a row that can't be made Offline). Quick
actions All active / None. The footer counts what Apply would copy (and
the total size) and make live again, plus
offline_mods.OFFLINE_RUN_TEXT. Apply (the default button; disabled with
nothing changed or while a size to copy is still being measured) runs the
screen's `confirm(to_copy, to_live, sizes)` gate - declining keeps the
dialog open, as CollectionDialog's may_import - then accepts; the screen
reads `changes` and runs the copy. Esc / Cancel closes without changes.

The pure helpers at the top (no Qt) are what tools/checks/volt_py_offline
_mods.py tests directly.
"""

import threading
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from volt_py import offline_mods
from volt_py.applog import clip, log
from volt_py.offline_mods import OFFLINE_RUN_TEXT, format_size

TITLE = "Offline mods"
INTRO = (
    "Ticked mods get this load order's own frozen copy: VOLT copies their folder into the load order, and "
    "Steam updates no longer change it. Untick an Offline mod to make it live again (its copy is deleted)."
)
SIZE = (760, 560)  # at most the parent window minus 32px
COLUMNS = ("Mod", "Package ID", "Source", "Live", "Size")  # Live: an Offline row's live-changed status (0.6.18)
SIZE_COL = 4
SOURCE_LABEL = {
    "local": "Mods", "steamcmd": "SteamCMD", "gog": "GOG", "workshop": "Workshop",
    "official": "Official", "pinned": "Offline",
}


# ---- pure logic (no Qt) ----
def plural(n: int, one: str) -> str:
    return f"{n} {one}{'' if n == 1 else 's'}"


def dialog_rows(active: list[str], inactive: list[str], mods: dict, entries: dict, live: dict | None = None) -> list[dict]:
    """One row per mod of the load order: the Active ids (list order), the
    Inactive ones, then any Offline entry neither lists. Each: {"id", "name",
    "package_id", "source" (SOURCE_LABEL / Not installed), "active",
    "offline" (an entry now), "refusal" (why it can't be ticked; None for an
    Offline row - unticking is always allowed), "folder", "path" (what to
    measure), "size" (an Offline entry's recorded size, else None), "live"
    (an Offline row's offline_mods.live_status - `live`, the screen's check;
    "unknown" until known - else None)}."""
    rows, seen = [], set()
    for mod_id, is_active in [*((i, True) for i in active), *((i, False) for i in inactive), *((i, False) for i in entries)]:
        if mod_id in seen:
            continue
        seen.add(mod_id)
        mod = mods.get(mod_id)
        entry = entries.get(mod_id)
        rows.append({
            "id": mod_id,
            "name": mod["name"] if mod else mod_id,
            "package_id": mod["package_id"] if mod else mod_id,
            "source": SOURCE_LABEL.get(mod["source"], mod["source"]) if mod else "Not installed",
            "active": is_active,
            "offline": entry is not None,
            "refusal": None if entry is not None else offline_mods.refusal(mod_id, mod, entries),
            "folder": entry["folder"] if entry else mod["folder"] if mod else None,
            "path": mod["path"] if mod else None,
            "size": entry.get("size_bytes") if entry and isinstance(entry.get("size_bytes"), int) else None,
            "live": (live or {}).get(mod_id, "unknown") if entry is not None else None,
            # an Offline entry whose copy is missing: the overlay kept the live mod (or nothing) in its place
            "missing": entry is not None and (mod is None or mod["source"] != "pinned"),
            "live_installed": mod is not None and mod["source"] != "pinned",  # (only read for a missing copy)
        })
    return rows


def changed_rows(rows: list[dict]) -> list[str]:
    """Offline rows Refresh changed re-copies: the live mod changed since the
    copy, or the copy is missing while the live mod is installed (recreated)."""
    return [r["id"] for r in rows if r["offline"] and (r["live"] == "changed" or (r["missing"] and r["live_installed"]))]


def changes(rows: list[dict], ticked: set[str]) -> tuple[list[str], list[str]]:
    """(to_copy, to_live): ticked rows that aren't Offline yet, unticked rows that are - in row order."""
    return ([r["id"] for r in rows if r["id"] in ticked and not r["offline"]],
            [r["id"] for r in rows if r["id"] not in ticked and r["offline"]])


def tick_refusal(row: dict, rows: list[dict], ticked: set[str]) -> str | None:
    """Why `row` can't be ticked with these other rows ticked: its own
    refusal, or a folder name another ticked row (Offline or about to be)
    already uses - two copies can't share local-mods/<folder>."""
    if row["offline"] or row["refusal"]:
        return row["refusal"]
    folder = str(row["folder"]).casefold()
    other = next((r for r in rows if r["id"] in ticked and r["id"] != row["id"]
                  and str(r["folder"]).casefold() == folder), None)
    if other is not None:
        return f'{other["name"]} already uses the folder name "{row["folder"]}" in this load order.'
    return None


def footer_text(to_copy: list[str], to_live: list[str], sizes: dict) -> str:
    """'Copies N mods (X MB) - makes M mods live again', or 'No changes.'"""
    if not to_copy and not to_live:
        return "No changes."
    parts = []
    if to_copy:
        known = [sizes[i] for i in to_copy if sizes.get(i) is not None]
        total = format_size(sum(known)) if len(known) == len(to_copy) else "measuring size..."
        parts.append(f"Copies {plural(len(to_copy), 'mod')} ({total})")
    if to_live:
        parts.append(f"makes {plural(len(to_live), 'mod')} live again" if parts else
                     f"Makes {plural(len(to_live), 'mod')} live again")
    return " - ".join(parts) + "."


# ---- sizes, off the GUI thread ----
class _Sized(QObject):
    """Carries one measured size (mod id, bytes) to the GUI thread (queued)."""

    sized = Signal(str, object)


def _measure(queue: deque, cancel: threading.Event, carrier: _Sized) -> None:
    """Worker body: measures (id, path) pairs from the left of `queue` until
    it's empty or `cancel` is set. Holds no reference to the dialog."""
    while not cancel.is_set():
        try:
            mod_id, path = queue.popleft()
        except IndexError:
            return
        try:
            n = offline_mods.size_of(path, cancel)
        except offline_mods.Cancelled:
            return
        try:
            carrier.sized.emit(mod_id, n)
        except RuntimeError:  # the dialog is gone
            return


def _label(text: str = "", *, role: str | None = None, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if role:
        label.setProperty("role", role)
    if muted:
        label.setProperty("muted", True)
    return label


class OfflineModsDialog(QDialog):
    def __init__(self, rows: list[dict], confirm: Callable[[list[str], list[str], dict], bool],
                 parent: QWidget | None = None, lo_name: str = "",
                 confirm_refresh: Callable[[list[str]], bool] | None = None) -> None:
        """rows: dialog_rows(...). confirm(to_copy, to_live, sizes) -> bool:
        the screen's gate before accepting (False keeps the dialog open).
        confirm_refresh(ids) -> bool: Refresh changed's gate; when it says
        yes the dialog closes with `refresh` = ids (no tick changes)."""
        super().__init__(parent)
        self.setObjectName("offlineMods")
        self.setWindowTitle(f"{TITLE} - {lo_name}" if lo_name else TITLE)
        self.setModal(True)
        self._rows = rows
        self._confirm = confirm
        self._ticked = {r["id"] for r in rows if r["offline"]}
        self.sizes = {r["id"]: r["size"] for r in rows if r["size"] is not None}
        self._items: dict[str, QTreeWidgetItem] = {}
        self._filling = False
        self.changes: tuple[list[str], list[str]] = ([], [])  # (to_copy, to_live) once accepted
        self.refresh: list[str] = []  # Refresh changed: the Offline mods to re-copy, once accepted that way
        self._confirm_refresh = confirm_refresh
        # self.sizes: mod id -> bytes measured so far (Offline rows: their recorded size); read by the screen too

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(_label(TITLE, role="modal-title"))
        layout.addWidget(_label(INTRO, muted=True))
        top = QHBoxLayout()
        top.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mods...")
        self.search.setClearButtonEnabled(True)
        top.addWidget(self.search, 1)
        self.all_active_button = QPushButton("All active")
        self.all_active_button.setToolTip("Tick every Active mod that can be made Offline")
        self.none_button = QPushButton("None")
        self.none_button.setToolTip("Untick everything (Offline mods become live again on Apply)")
        # Refresh changed (0.6.18): re-copy every Offline mod whose live copy changed - only with no ticks pending
        self.refresh_button = QPushButton("Refresh changed")
        for b in (self.all_active_button, self.none_button, self.refresh_button):
            b.setAutoDefault(False)
            top.addWidget(b)
        layout.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setObjectName("offlineModsList")
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setMouseTracking(True)  # hover feedback on rows
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._fill()
        layout.addWidget(self.tree, 1)

        self.status_label = _label(role="modal-error")  # a refused tick's reason
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)
        self.footer_label = _label()
        layout.addWidget(self.footer_label)
        layout.addWidget(_label(OFFLINE_RUN_TEXT, muted=True))

        buttons = QHBoxLayout()  # .button-row.end: right-aligned, 8px apart
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setAutoDefault(False)
        buttons.addWidget(self.cancel_button)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setProperty("variant", "primary")
        self.apply_button.setDefault(True)  # Enter = Apply (when enabled); Esc rejects (QDialog default)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)

        self.cancel_button.clicked.connect(lambda: self.reject())
        self.apply_button.clicked.connect(lambda: self._apply())
        self.all_active_button.clicked.connect(lambda: self._set_ticked(
            self._ticked | {r["id"] for r in rows if r["active"] and not r["refusal"]}))
        self.none_button.clicked.connect(lambda: self._set_ticked(set()))
        self.refresh_button.clicked.connect(lambda: self._refresh_changed())
        self.search.textChanged.connect(lambda text: self._filter(text))
        self.tree.itemChanged.connect(lambda item, column: self._on_item_changed(item, column))

        w, h = SIZE
        if parent is not None:
            w, h = min(w, parent.window().width() - 32), min(h, parent.window().height() - 32)
        self.resize(w, h)

        # Sizes: ticked rows first, then Active, then the rest; rows that can't be made Offline (Core / DLC...) never.
        self._cancel = threading.Event()
        self._queue = deque((r["id"], r["path"]) for r in sorted(
            rows, key=lambda r: (r["id"] not in self._ticked, not r["active"]))
            if r["path"] and not r["refusal"] and r["id"] not in self.sizes)
        self._carrier = _Sized()  # no parent: owned by self and the thread
        self._carrier.sized.connect(self._on_sized, Qt.ConnectionType.QueuedConnection)
        threading.Thread(target=_measure, args=(self._queue, self._cancel, self._carrier), name="offline-sizes",
                         daemon=True).start()
        self._render()
        self.search.setFocus()

    # ---- rows ----
    def _fill(self) -> None:
        self._filling = True
        try:
            for r in self._rows:
                size = "-" if r["refusal"] else format_size(self.sizes.get(r["id"]))
                live = ("" if not r["offline"] else "Copy missing" if r["missing"]
                        else offline_mods.LIVE_LABEL.get(r["live"], ""))
                item = QTreeWidgetItem([r["name"], r["package_id"], r["source"], live, size])
                item.setData(0, Qt.ItemDataRole.UserRole, r["id"])
                item.setTextAlignment(SIZE_COL, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
                if not r["refusal"]:
                    flags |= Qt.ItemFlag.ItemIsEnabled
                item.setFlags(flags)
                item.setCheckState(0, Qt.CheckState.Checked if r["id"] in self._ticked else Qt.CheckState.Unchecked)
                tip = r["refusal"] or (f"{r['name']} is Offline in this load order. Untick it to make it live again."
                                       if r["offline"] else f"{r['name']}\n{r['package_id']}")
                for col in range(len(COLUMNS)):
                    item.setToolTip(col, tip)
                self.tree.addTopLevelItem(item)
                self._items[r["id"]] = item
        finally:
            self._filling = False

    def _filter(self, text: str) -> None:
        q = text.strip().casefold()
        for r in self._rows:
            self._items[r["id"]].setHidden(bool(q) and q not in r["name"].casefold() and q not in r["id"])

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._filling or column != 0:
            return
        mod_id = item.data(0, Qt.ItemDataRole.UserRole)
        row = next(r for r in self._rows if r["id"] == mod_id)
        if item.checkState(0) == Qt.CheckState.Checked:
            why = tick_refusal(row, self._rows, self._ticked)
            if why:
                self._show_status(why)
                self._filling = True
                item.setCheckState(0, Qt.CheckState.Unchecked)
                self._filling = False
                return
            self._ticked.add(mod_id)
            if mod_id not in self.sizes and row["path"]:
                self._queue.appendleft((mod_id, row["path"]))  # measure it next
        else:
            self._ticked.discard(mod_id)
        self._show_status(None)
        self._render()

    def _set_ticked(self, ticked: set[str]) -> None:
        """All active / None: every enabled row follows `ticked` (a clash of
        folder names is refused row by row, as a click would be)."""
        new: set[str] = set()
        for r in self._rows:
            if r["id"] in ticked and (r["offline"] or not tick_refusal(r, self._rows, new)):
                new.add(r["id"])
        self._ticked = new
        self._filling = True
        try:
            for r in self._rows:
                self._items[r["id"]].setCheckState(0, Qt.CheckState.Checked if r["id"] in new else Qt.CheckState.Unchecked)
        finally:
            self._filling = False
        for r in self._rows:
            if r["id"] in new and r["id"] not in self.sizes and r["path"]:
                self._queue.appendleft((r["id"], r["path"]))
        self._show_status(None)
        self._render()

    @Slot(str, object)
    def _on_sized(self, mod_id: str, size) -> None:
        if mod_id in self.sizes:
            return
        self.sizes[mod_id] = size
        item = self._items.get(mod_id)
        if item is not None:
            item.setText(SIZE_COL, format_size(size))
        self._render()

    def _show_status(self, text: str | None) -> None:
        self.status_label.setText(text or "")
        self.status_label.setVisible(bool(text))

    def _render(self) -> None:
        to_copy, to_live = changes(self._rows, self._ticked)
        self.footer_label.setText(footer_text(to_copy, to_live, self.sizes))
        measuring = any(self.sizes.get(i) is None for i in to_copy)
        self.apply_button.setEnabled(bool(to_copy or to_live) and not measuring)
        self.apply_button.setToolTip("Nothing changed" if not (to_copy or to_live)
                                     else "Waiting for the sizes to be measured" if measuring else "")
        stale = changed_rows(self._rows)
        pending = bool(to_copy or to_live)
        self.refresh_button.setEnabled(bool(stale) and not pending and self._confirm_refresh is not None)
        self.refresh_button.setToolTip(
            "Apply or undo your ticks first" if stale and pending
            else f"Copy the live mod afresh into {len(stale)} Offline cop{'y' if len(stale) == 1 else 'ies'} "
                 "whose live mod has changed or whose copy is missing" if stale
            else "No Offline mod's live copy has changed")

    def _refresh_changed(self) -> None:
        stale = changed_rows(self._rows)
        if not stale or any(changes(self._rows, self._ticked)) or self._confirm_refresh is None:
            return
        log(f"offline mods dialog: Refresh changed - {clip(stale)}")
        if not self._confirm_refresh(stale):
            log("offline mods dialog: refresh cancelled at the confirm, dialog stays open")
            return
        self.refresh = stale
        self.accept()

    # ---- apply / close ----
    def _apply(self) -> None:
        to_copy, to_live = changes(self._rows, self._ticked)
        if not (to_copy or to_live) or any(self.sizes.get(i) is None for i in to_copy):
            return
        log(f"offline mods dialog: Apply - copy {clip(to_copy)}, make live {clip(to_live)}")
        if not self._confirm(to_copy, to_live, dict(self.sizes)):
            log("offline mods dialog: not applied (cancelled at the confirm), dialog stays open")
            return
        self.changes = (to_copy, to_live)
        self.accept()

    def done(self, result: int) -> None:
        self._cancel.set()  # the size worker stops at its next folder
        super().done(result)
