"""Import local mod dialog (THUNDERSTORE.md §8b; Import... > "Local mod
(.zip)..." on the Thunderstore/BepInEx manager screen). Modeled on
collection_dialog.py's .modal: title + intro, an input - here a native file
picker (a read-only path field + "Choose..."), not a URL box - a preview
once the picked zip validates (the package name / version / owner read from
its own manifest.json, via bepinex_load_orders.inspect_local_package), then
Cancel + a single Import. No Replace / New-load-order modes: it's always
exactly one package, installed into the open load order.

A zip that can't be installed (not a zip, no manifest.json at its root, a
manifest.json that doesn't parse or lacks name / version_number, ...) shows
the PackageError's message as the dialog's error line and Import stays
disabled - a reported problem, never a silent failure. So does a package
already in the load order (`blocked(ref)` - the screen's check). Validation
is synchronous: reading one zip's directory + manifest.json is local and
fast, unlike the collection dialog's Steam lookup. The screen reads
`payload` ({"path", "ref", "info"}) after exec() and runs the install
(BepInExMainScreen._import_local_mod).
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from volt_py.applog import log
from volt_py.bepinex_install import PackageError
from volt_py.screens.collection_dialog import WIDTH, CollectionDialog, _button, _label

TITLE = "Import local mod"
INTRO = (
    "Install a mod from a Thunderstore package zip on this computer (manifest.json at its root) into the open "
    "load order. It joins the Active list like a download, and any dependency it lists that isn't installed "
    "comes from Thunderstore. VOLT never checks a local package for updates."
)
PLACEHOLDER = "No file chosen"
FILE_FILTER = "Mod packages (*.zip);;All files (*)"
OWNER_NOTES = {
    "author": "Owner taken from manifest.json's author field.",
    "fallback": ("The file name isn't Thunderstore's Owner-Name-Version.zip and manifest.json names no author, "
                 "so it's installed as {full_name}."),
}


# ---- pure logic (no Qt) ----
def preview_texts(info: dict) -> tuple[str, str, str]:
    """(title, detail line, notes) for an inspect_local_package() result."""
    ref, m = info["ref"], info["manifest"]
    n = len(m["dependencies"])
    detail = f"{ref.full_name}  ·  by {ref.namespace}  ·  {n} dependenc{'y' if n == 1 else 'ies'}"
    notes = [m["description"]] if m["description"] else []
    if info["owner_source"] in OWNER_NOTES:
        notes.append(OWNER_NOTES[info["owner_source"]].format(full_name=ref.full_name))
    return f"{m['name']} {ref.version}", detail, " ".join(notes)


class LocalModDialog(QDialog):
    # The collection dialog's height fitting and error-line styling, unchanged.
    _fit_height = CollectionDialog._fit_height
    _set_status = CollectionDialog._set_status

    def __init__(
        self,
        inspect: Callable[[Path], dict],
        blocked: Callable[[object], str | None],
        start_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """inspect(path) -> bepinex_load_orders.inspect_local_package's dict
        (raises PackageError); blocked(ref) -> why that package can't be
        imported into the open load order (already installed), else None;
        start_dir: where the file picker opens."""
        super().__init__(parent)
        self.setObjectName("localModImport")
        self.setWindowTitle(TITLE)
        self.setModal(True)
        self._inspect = inspect
        self._blocked = blocked
        self._start_dir = start_dir
        self._info: dict | None = None
        self._path: Path | None = None
        self.payload: dict | None = None

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(_label(TITLE, role="modal-title"))
        layout.addWidget(_label(INTRO, muted=True))
        pick = QHBoxLayout()
        pick.setSpacing(8)
        self.input = QLineEdit()
        self.input.setReadOnly(True)
        self.input.setPlaceholderText(PLACEHOLDER)
        pick.addWidget(self.input, 1)
        self.choose_button = _button("Choose...")
        pick.addWidget(self.choose_button)
        layout.addLayout(pick)
        self.status_label = _label(muted=True)  # the reported problem (role modal-error)
        self.title_label = _label(role="collection-title")
        self.preview_label = _label()
        self.notes_label = _label(muted=True)
        for label in (self.status_label, self.title_label, self.preview_label, self.notes_label):
            label.setVisible(False)
            layout.addWidget(label)

        buttons = QHBoxLayout()  # .button-row.end
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.cancel_button = _button("Cancel")
        self.import_button = _button("Import", "primary")
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.import_button)
        layout.addLayout(buttons)

        self.cancel_button.clicked.connect(lambda: self.reject())
        self.choose_button.clicked.connect(lambda: self._choose())
        self.import_button.clicked.connect(lambda: self._submit())

        width = WIDTH
        if parent is not None:
            width = min(width, parent.window().width() - 32)
        self.setFixedWidth(width)
        self._show(None, None)
        self.choose_button.setFocus()

    def _choose(self) -> None:
        start = str(self._path.parent if self._path else self._start_dir or "")
        picked, _ = QFileDialog.getOpenFileName(self, "Choose a mod package", start, FILE_FILTER)
        if not picked:
            log("import local mod: file picker cancelled")
            return
        self._path = Path(picked)
        self.input.setText(str(self._path))
        try:
            info = self._inspect(self._path)
        except PackageError as err:
            log(f"import local mod: {self._path} rejected: {err.problem()}")
            self._show(None, f"Can't import {self._path.name}: {err.message}")
            return
        except OSError as err:
            log(f"import local mod: {self._path} unreadable: {err!r}")
            self._show(None, f"Can't read {self._path.name}: {err.strerror or err}")
            return
        why = self._blocked(info["ref"])
        if why:
            log(f"import local mod: {self._path} ({info['ref'].key}) blocked: {why}")
        self._show(info, why)

    def _show(self, info: dict | None, error: str | None) -> None:
        """The preview (when `info`) and the error line (when `error`);
        Import is enabled only for a valid, unblocked package."""
        self._info = info if not error else None
        if error:
            self._set_status(error, error=True)
        else:
            self.status_label.setVisible(False)
        title, detail, notes = preview_texts(info) if info else ("", "", "")
        for label, text in ((self.title_label, title), (self.preview_label, detail), (self.notes_label, notes)):
            label.setText(text)
            label.setVisible(bool(text))
        self.import_button.setEnabled(self._info is not None)
        self._fit_height()

    def _submit(self) -> None:
        if self._info is None or self._path is None:
            return
        log(f"import local mod: Import clicked for {self._path} as {self._info['ref'].key}")
        self.payload = {"path": self._path, "ref": self._info["ref"], "info": self._info}
        self.accept()
