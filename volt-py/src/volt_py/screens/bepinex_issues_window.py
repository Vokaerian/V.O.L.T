"""Warnings and errors window for the Thunderstore/BepInEx manager
(THUNDERSTORE.md §3's dependency presence; the "⚠ N · ✕ M" button of
screens/bepinex_main_screen.py). The same shape as RimWorld's Warnings
and errors window (screens/validation_window.py) and the Scan issues
window: a modal dialog, 16px padding, a header with the title and Close,
a 280px rail of entries grouped under one header per mod (the
validation-entry look, warning / error tinted) beside a detail pane for
the selected issue (the validation-detail frame, the severity's left bar)
- the theme's existing `validation` rules, no new QSS.

The issues are bepinex_load_orders.dependency_issues' dicts, read live
through `issues()` so the window follows the screen: kind "missing" (an
error: the dependency isn't installed), "inactive" and "off" (warnings:
it's installed but not in Active / switched off). What the window adds
over RimWorld's: a way to fix the errors in place -
  - the selected "missing" issue's detail carries an "Install <dep>"
    button: the screen's _install_missing (install_mod: the latest
    version plus its own dependencies, appended to Active, the panes
    refreshed) runs as the screen's busy job; the window re-reads the
    issues when it lands, so every row that dependency caused disappears
    together, and shows a failure (offline, a package Thunderstore no
    longer has) in the detail pane, the row staying;
  - "Install all missing" in the header (shown while there is at least
    one missing dependency) installs every missing package once (deduped
    across mods) in one job; per-package failures are listed, the rest
    still install.
Inactive / switched-off dependencies aren't installs: their detail says
what to do (activate / switch on) and has no button. The framework
package never appears here (dependency_issues skips it). Esc closes.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from volt_py import bepinex_load_orders as lo
from volt_py.applog import log

WINDOW_SIZE = (900, 600)  # the Warnings and errors / Scan issues window
RAIL_WIDTH = 280
GROUP_GAP = 6

RAIL_LABEL = {"missing": "Missing dependency", "inactive": "Dependency inactive", "off": "Dependency switched off"}
HEADING = {
    "missing": "Missing dependency (not installed)",
    "inactive": "Dependency installed but inactive",
    "off": "Dependency switched off",
}


def detail_text(issue: dict, name: str, dep_name: str) -> str:
    """What the selected issue means and what fixes it."""
    kind = issue["kind"]
    if kind == "missing":
        return (
            f"{name} requires {dep_name}, which isn't installed in this load order. BepInEx will skip {name} "
            f"(or it will fail while loading). Install {dep_name} below - VOLT downloads its latest version, "
            "with anything it needs itself, and adds it to the Active list."
        )
    if kind == "inactive":
        return (
            f"{name} requires {dep_name}, which is installed but in the Inactive list, so it isn't loaded. "
            f"Double-click {dep_name} in the Inactive list to activate it, then Save."
        )
    return (
        f"{name} requires {dep_name}, which is in the Active list but switched off, so it isn't loaded. "
        f"Switch {dep_name} back on with its toggle, then Save."
    )


def group_issues(issues: list[dict]) -> list[tuple[str, list[dict]]]:
    """Consecutive issues of the same mod under one header, in order."""
    groups: list[tuple[str, list[dict]]] = []
    for issue in issues:
        if groups and groups[-1][0] == issue["mod_id"]:
            groups[-1][1].append(issue)
        else:
            groups.append((issue["mod_id"], [issue]))
    return groups


def issue_key(issue: dict) -> tuple[str, str]:
    return issue["mod_id"], issue["dep"]


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _wrapped(text: str = "", *, role: str | None = None, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    if role:
        label.setProperty("role", role)
    if muted:
        label.setProperty("muted", True)
    return label


class BepInExIssuesWindow(QDialog):
    def __init__(self, issues: Callable[[], list[dict]], display_name: Callable[[str], str],
                 install_missing, *, is_busy: Callable[[], bool], parent: QWidget | None = None) -> None:
        """`issues()`: the screen's live dependency_issues list; `display_name
        (full_name)`; `install_missing(packages, on_done, parent)`: the
        screen's job; `is_busy()`: its lock."""
        super().__init__(parent)
        self.setObjectName("validation")  # the Warnings and errors window's frame (theme.py)
        self.setWindowTitle("Load order warnings and errors")
        self.setModal(True)
        self._issues_source = issues
        self._display_name = display_name
        self._install_missing = install_missing
        self._is_busy = is_busy
        self._issues: list[dict] = []
        self._sel_key: tuple[str, str] | None = None
        self._entries: list[tuple[dict, QPushButton]] = []
        self._installing: list[str] = []  # packages in flight (their rows read Installing...)
        self._result: str | None = None  # the last install's outcome, shown in the detail pane
        self._result_error = False
        self._closed = False

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Warnings and errors")
        title.setProperty("role", "modal-title")
        header.addWidget(title, 1)
        self.install_all_button = QPushButton("Install all missing")
        self.install_all_button.setProperty("variant", "accent-outline")
        self.install_all_button.setAutoDefault(False)
        self.install_all_button.setToolTip("Install every dependency listed as not installed, each at its latest version")
        header.addWidget(self.install_all_button)
        self.close_button = QPushButton("Close")
        self.close_button.setAutoDefault(False)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        self._body = QWidget()
        body = QHBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        body.addWidget(self._build_rail())
        body.addWidget(self._build_detail(), 1)
        layout.addWidget(self._body, 1)
        self._empty = QLabel("No warnings or errors in the current load order.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._empty, 1)

        self.install_all_button.clicked.connect(lambda _=False: self._install_all())
        self.install_button.clicked.connect(lambda _=False: self._install_selected())
        self.close_button.clicked.connect(lambda _=False: self.reject())  # Esc rejects too (QDialog default)

        width, height = WINDOW_SIZE
        if parent is not None:
            bounds = parent.window().size()
            width, height = min(width, bounds.width() - 32), min(height, bounds.height() - 32)
        self.resize(width, height)
        self.refresh()
        self.close_button.setFocus()

    # ---- layout ----
    def _build_rail(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("validationRail")
        scroll.setFixedWidth(RAIL_WIDTH)
        scroll.setWidgetResizable(True)
        self._rail_inner = QWidget()
        self._rail = QVBoxLayout(self._rail_inner)
        self._rail.setContentsMargins(0, 4, 0, 4)
        self._rail.setSpacing(0)
        self._rail.addStretch(1)
        scroll.setWidget(self._rail_inner)
        scroll.viewport().setAutoFillBackground(False)
        self._rail_inner.setAutoFillBackground(False)
        return scroll

    def _build_detail(self) -> QScrollArea:
        scroll = self._detail = QScrollArea()
        scroll.setObjectName("validationDetail")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        detail = QVBoxLayout(inner)
        detail.setContentsMargins(10, 10, 10, 10)
        detail.setSpacing(8)
        self._heading = QLabel()
        self._heading.setTextFormat(Qt.TextFormat.PlainText)
        self._heading.setWordWrap(True)
        self._heading.setProperty("role", "validation-heading")
        self._text = _wrapped()
        self._package = _wrapped(role="scan-mono")  # the dependency's full_name, mono
        self.install_button = QPushButton("Install")
        self.install_button.setProperty("variant", "primary")
        self.install_button.setAutoDefault(False)
        self._result_label = _wrapped()
        for widget in (self._heading, self._text, self._package):
            detail.addWidget(widget)
        detail.addWidget(self.install_button, 0, Qt.AlignmentFlag.AlignLeft)
        detail.addWidget(self._result_label)
        detail.addStretch(1)
        scroll.setWidget(inner)
        scroll.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        return scroll

    # ---- state ----
    def refresh(self) -> None:
        """Re-reads the screen's issues and rebuilds the rail; the selection
        survives when its issue still exists, else the first issue."""
        self._issues = list(self._issues_source())
        for _issue, entry in self._entries:
            entry.hide()
            entry.deleteLater()
        self._entries = []
        while self._rail.count() > 1:  # keep the trailing stretch
            item = self._rail.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for n, (mod_id, items) in enumerate(group_issues(self._issues)):
            if n:
                self._rail.insertSpacing(self._rail.count() - 1, GROUP_GAP)
            header = QLabel(self._display_name(mod_id))
            header.setTextFormat(Qt.TextFormat.PlainText)
            header.setProperty("role", "validation-mod")
            self._rail.insertWidget(self._rail.count() - 1, header)
            for issue in items:
                entry = QPushButton(RAIL_LABEL[issue["kind"]])
                entry.setProperty("variant", "validation-entry")
                entry.setProperty("severity", issue["severity"])
                entry.setAutoDefault(False)
                entry.clicked.connect(lambda _=False, key=issue_key(issue): self._select(key))
                self._rail.insertWidget(self._rail.count() - 1, entry)
                self._entries.append((issue, entry))
        keys = [issue_key(i) for i in self._issues]
        if self._sel_key not in keys:
            self._sel_key = keys[0] if keys else None
        self._render()

    def _sel(self) -> dict | None:
        return next((i for i in self._issues if issue_key(i) == self._sel_key), None)

    def _select(self, key: tuple[str, str]) -> None:
        self._sel_key = key
        self._result = None
        log(f"issues window: selected {key}")
        self._render()

    def _render(self) -> None:
        sel = self._sel()
        missing = lo.missing_packages(self._issues)
        busy = bool(self._installing) or self._is_busy()
        self.install_all_button.setVisible(bool(missing))
        self.install_all_button.setEnabled(not busy)
        self.install_all_button.setText(
            f"Installing {len(self._installing)}..." if self._installing and len(self._installing) > 1
            else f"Install all missing ({len(missing)})" if missing else "Install all missing")
        self._body.setVisible(sel is not None)
        self._empty.setVisible(sel is None)
        self._empty.setText("No warnings or errors in the current load order."
                            + (f"\n\n{self._result}" if self._result and sel is None else ""))
        for issue, entry in self._entries:
            selected = issue is sel
            if entry.property("selected") != selected:
                entry.setProperty("selected", selected)
                _repolish(entry)
        if sel is None:
            return
        if self._detail.property("severity") != sel["severity"]:
            self._detail.setProperty("severity", sel["severity"])
            _repolish(self._detail)
        name, dep = self._display_name(sel["mod_id"]), sel["dep"]
        self._heading.setText(HEADING[sel["kind"]])
        self._text.setText(detail_text(sel, name, dep))
        self._package.setText(dep)
        is_missing = sel["kind"] == "missing"
        self.install_button.setVisible(is_missing)
        if is_missing:
            installing = dep in self._installing
            self.install_button.setText(f"Installing {dep}..." if installing else f"Install {dep}")
            self.install_button.setEnabled(not busy)
        self._result_label.setText(self._result or "")
        self._result_label.setVisible(bool(self._result))
        role = "scan-error" if self._result_error else None
        if self._result_label.property("role") != role:
            self._result_label.setProperty("role", role)
            self._result_label.setProperty("muted", not self._result_error)
            _repolish(self._result_label)

    # ---- installs ----
    def _install_selected(self) -> None:
        sel = self._sel()
        if sel is not None and sel["kind"] == "missing":
            self._start([sel["dep"]])

    def _install_all(self) -> None:
        self._start(lo.missing_packages(self._issues))

    def _start(self, packages: list[str]) -> None:
        if not packages or self._installing or self._is_busy():
            log(f"issues window: install {packages} ignored ({'busy' if self._installing or self._is_busy() else 'nothing'})")
            return
        self._installing = list(packages)
        self._result = None
        log(f"issues window: installing {packages}")
        self._render()

        def done(payload: dict) -> None:
            if self._closed:
                return
            asked = self._installing
            self._installing = []
            if "error" in payload:
                self._result, self._result_error = payload["error"], True
            else:
                res = payload["ok"]
                failed = dict(res["failed"])
                got = [p for p in asked if p not in failed]
                parts = []
                if got:
                    parts.append(f"Installed {', '.join(got)}" + (" and its dependencies." if len(got) == 1 else " and their dependencies."))
                parts += [f"{name}: {msg}" for name, msg in res["failed"]]
                self._result, self._result_error = " ".join(parts), bool(res["failed"])
            self.refresh()  # the rows that dependency caused are gone now (the screen recomputed)

        self._install_missing(packages, done, self)

    # ---- lifecycle ----
    def done(self, result: int) -> None:
        self._closed = True
        super().done(result)
