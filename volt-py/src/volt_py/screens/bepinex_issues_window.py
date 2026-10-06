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

"Files missing" (0.6.27, PLAN.md §11 (f)): the screen also lists
bepinex_load_orders.files_issue's dicts (kind "files", a warning, "dep" =
the mod itself) under the mod's own header - some or all of its files are
gone from the profile folder; the detail says so and points at the row's
Reinstall (no button here).

Conflicts (troubleshooting phase 1, volt_py/bepinex_conflicts.py): four
more kinds, listed under the mod they affect, advice only (no button) -
"incompatible" (a
plugin declares the other mod incompatible, so BepInEx won't load it,
error), "two_versions" (0.6.49: two versions of one mod are both on; the
text says which one to keep; an error for a known hard clash, then "What
it means" says the game won't reach the main menu), "duplicate_plugin" and
"duplicate_file" (warnings). Their dicts carry "dep_name" (the other mod as on screen) and
"needed_by" (the mods that need this one), which the texts use.

Three sections (0.6.28, PLAN.md §11 (g)): under the heading, the detail
reads "What happened" / "What it means" / "What to try" (detail_text's
three parts), each a small terminal label (the "side" rule, as Browse
Mods' "Requires") over its text shown as help_window.TextBlocks
(paragraphs, numbered steps); the Install button and its result stay
below them.
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

from volt_py import bepinex_load_orders as lo, painters
from volt_py.applog import log
from volt_py.screens.help_window import TextBlocks

WINDOW_SIZE = (900, 600)  # the Warnings and errors / Scan issues window
RAIL_WIDTH = 280
GROUP_GAP = 6

# 0.6.24 plain words: a "dependency" is a "required mod" (a mod another mod needs to work).
RAIL_LABEL = {"missing": "Required mod missing", "inactive": "Required mod inactive", "off": "Required mod switched off",
              "files": "Files missing", "incompatible": "Incompatible mod", "two_versions": "Two versions of one mod",
              "duplicate_file": "Shared files differ", "duplicate_plugin": "Possible duplicate"}
HEADING = {
    "missing": "A mod it needs isn't installed",
    "inactive": "A mod it needs is in the Inactive list",
    "off": "A mod it needs is switched off",
    "files": "Some of its files are gone",
    "incompatible": "It won't load: another mod blocks it",
    "two_versions": "Another version of this mod is also switched on",
    "duplicate_file": "It shares files with another mod",
    "duplicate_plugin": "It may be a second copy of another mod",
}
FILES_SHOWN = 5  # duplicate_file: file names named before "and N more"
SECTIONS = ("What happened", "What it means", "What to try")
SECTION_GAP = 4  # a section label to its text (the detail's own 8px sits between sections)


def detail_text(issue: dict, name: str, dep_name: str) -> tuple[str, str, str]:
    """The selected issue as SECTIONS: what happened, what it means, what to
    try (plain text: blank lines split paragraphs, "1. " lines are steps)."""
    kind = issue["kind"]
    if kind in ("incompatible", "two_versions", "duplicate_file", "duplicate_plugin"):
        return _conflict_text(issue, name, issue.get("dep_name") or dep_name)
    if kind == "files":
        missing, total = issue["missing"], issue["total"]
        count = (f"All {total} of {name}'s files are" if missing >= total
                 else f"{missing} of {name}'s {total} files are")
        return (
            f"{count} gone from the profile folder. Something outside VOLT removed them: they may have been "
            "deleted by hand, or moved away by an antivirus program.",
            f"The game may skip {name}, or fail while loading it.",
            f"1. Right-click {name} in the list.\n"
            "2. Choose \"Reinstall\".\n\n"
            "VOLT puts the same version back. It keeps the mod's settings files, its place in the list, and "
            "whether it's on or off.",
        )
    if kind == "missing":
        return (
            f"{name} needs {dep_name} to work, and {dep_name} isn't installed in this profile.",
            f"The game will skip {name}, or {name} will fail while the game loads.",
            f"Press \"Install {dep_name}\" below. VOLT downloads the latest version of {dep_name}, with anything "
            "it needs itself, and adds it to the Active list.\n\n"
            "\"Install all missing\" at the top installs every missing mod in one go.",
        )
    if kind == "inactive":
        return (
            f"{name} needs {dep_name} to work, and {dep_name} is in the Inactive list.",
            f"Mods in the Inactive list aren't loaded, so {name} can't use {dep_name}.",
            f"1. Double-click {dep_name} in the Inactive list to move it to Active.\n"
            "2. Press \"Save\".",
        )
    return (
        f"{name} needs {dep_name} to work, and {dep_name} is switched off.",
        f"Switched-off mods aren't loaded, so {name} can't use {dep_name}.",
        f"1. Click the switch at the right of {dep_name} to turn it back on.\n"
        "2. Press \"Save\".",
    )


def _names(items: list[str], shown: int | None = None) -> str:
    """"A", "A and B", "A, B and C" (then "and N more" past `shown`)."""
    if shown is not None and len(items) > shown:
        return ", ".join(items[:shown]) + f" and {len(items) - shown} more"
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _conflict_text(issue: dict, name: str, dep: str) -> tuple[str, str, str]:
    """detail_text for bepinex_conflicts' kinds (advice only)."""
    kind = issue["kind"]
    needed = issue.get("needed_by") or []
    if kind == "incompatible":
        return (
            f"{name} says it can't be used together with {dep}, and both are switched on.",
            f"The mod loader (BepInEx) refuses to load {name}, so it does nothing in the game. {dep} still loads."
            + (f" Mods that need {name}: {_names(needed)} (they may not work properly)." if needed else ""),
            f"Choose one: switch off or remove {dep} to use {name}, or switch off {name} to keep {dep}. "
            "Then press \"Save\".",
        )
    if kind == "two_versions":
        return _two_versions_text(issue, name, dep)
    if kind == "duplicate_file":
        files = issue.get("files") or ["?"]
        listed = _names(files, FILES_SHOWN)
        return (
            f"{name} and {dep} both contain a file called {listed}, but the two copies are not identical."
            if len(files) == 1 else
            f"{name} and {dep} both contain files called {listed}, but the copies are not identical.",
            "Mods sometimes ship their own copy of a shared library, and different versions can clash. It is often "
            "harmless; if the game misbehaves, this is a place to look.",
            f"If the game crashes, or its log shows errors mentioning {listed}, switch off one of the two mods, "
            "press \"Save\" and test again.",
        )
    return (
        f"{name} and {dep} appear to be two copies of the same mod (the same internal name"
        + (f", {issue['guid']}" if issue.get("guid") else "") + ").",
        "Having both usually causes errors, or one of them is ignored. This often happens with re-uploaded "
        "versions of a mod.",
        "Keep one and remove the other, then press \"Save\".",
    )


def _two_versions_text(issue: dict, name: str, dep: str) -> tuple[str, str, str]:
    """detail_text for "two_versions": which one to keep comes from the
    issue's own evidence (bepinex_conflicts._keep): the one the other
    switched-on mods need, else the newer one."""
    files = issue.get("files") or ["?"]
    listed = _names(files, FILES_SHOWN)
    # side 0 = this mod, 1 = the other one (keyed by side: two versions can share a display name)
    names, needs = (name, dep), (issue.get("needed_by") or [], issue.get("dep_needed_by") or [])
    versions = (issue.get("version"), issue.get("dep_version"))
    if versions[0] == versions[1]:  # same package version: the plugin versions tell them apart
        versions = (issue.get("plugin_version"), issue.get("dep_plugin_version"))

    def need(who: list[str]) -> str:
        return f"{_names(who)} need{'s' if len(who) == 1 else ''}"

    asks = " ".join(f"{need(who)} {names[i]}." for i, who in enumerate(needs) if who)
    k = {issue.get("mod_id"): 0, issue.get("dep"): 1}.get(issue.get("keep"))
    keep, other = (names[k], names[1 - k]) if k is not None else (None, None)
    shown = (f" ({keep} is version {versions[k]}, {other} is version {versions[1 - k]})"
             if k is not None and versions[0] and versions[1] else "")
    if needs[0] and needs[1]:
        which = ("Which one to keep: each one is needed by a different mod, so no choice suits every mod. "
                 + (f"Try the newer one, {keep}, first{shown}. If a mod that needs {other} then stops working, "
                    f"switch {keep} off and {other} on instead, and test again. "
                    if keep else "Try one, then the other, and test each time. ")
                 + "If neither way works, this profile may need a different choice of mods: for example, leave out "
                 "one of the mods named above, or look for a newer version of it.")
    elif keep and issue.get("keep_why") == "needed":
        which = f"Which one to keep: {keep}, because {need(needs[k])} it."
    elif keep:
        which = f"Which one to keep: the newer one, {keep}{shown}. No other switched-on mod needs either one."
    else:
        which = "Which one to keep: either one. No other switched-on mod needs either one, and VOLT can't tell which is newer."
    return (
        f"{name} and {dep} are both switched on. They are two versions of the same mod: both contain "
        + (f"a file called {listed}" if len(files) == 1 else f"files called {listed}") + ", and the copies are different.",
        "The game can only use one version. "
        + ("With both on, the game will not start properly: it won't reach the main menu."
           if issue.get("severity") == "error" else  # a known hard clash (bepinex_conflicts.HARD_CLASH_PAIRS)
           "With both on, mods that use it can fail to load, or the game may not start properly.")
        + (f" {asks}" if asks else ""),
        "1. Decide which one to keep (see below).\n"
        "2. Click the switch at the right of the other one to turn it off.\n"
        "3. Press \"Save\" and start the game.\n\n" + which,
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
        self.setWindowTitle("Profile warnings and errors")
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
        self.install_all_button.setToolTip("Install every required mod listed as not installed, each at its latest version")
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
        self._empty = QLabel("No warnings or errors in the current profile.")
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
        # a copper side-rule terminal heading (design step 3.4); wraps (without
        # its rule) if ever too long for the pane
        self._heading = painters.TerminalLabel(rule="heading")
        self._heading.setTextFormat(Qt.TextFormat.PlainText)
        self._heading.setWordWrap(True)
        self._sections = []  # one TextBlocks per SECTIONS entry (0.6.28)
        self._package = _wrapped(role="scan-mono")  # the dependency's full_name, mono
        self.install_button = QPushButton("Install")
        self.install_button.setProperty("variant", "primary")
        self.install_button.setAutoDefault(False)
        self._result_label = _wrapped()
        detail.addWidget(self._heading)
        for title in SECTIONS:
            section = QVBoxLayout()
            section.setSpacing(SECTION_GAP)
            section.addWidget(painters.TerminalLabel(title, rule="side"))
            blocks = TextBlocks()
            section.addWidget(blocks)
            self._sections.append(blocks)
            detail.addLayout(section)
        detail.addWidget(self._package)
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
        self._empty.setText("No warnings or errors in the current profile."
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
        name, dep = self._display_name(sel["mod_id"]), sel["dep"]  # dep: the full_name (the conflicts' texts use dep_name)
        self._heading.setText(HEADING[sel["kind"]])
        for blocks, text in zip(self._sections, detail_text(sel, name, dep)):
            blocks.setText(text)
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
                    parts.append(f"Installed {', '.join(got)}" + (" and the mods it needs." if len(got) == 1 else " and the mods they need."))
                parts += [f"{name}: {msg}" for name, msg in res["failed"]]
                self._result, self._result_error = " ".join(parts), bool(res["failed"])
            self.refresh()  # the rows that dependency caused are gone now (the screen recomputed)

        self._install_missing(packages, done, self)

    # ---- lifecycle ----
    def done(self, result: int) -> None:
        self._closed = True
        super().done(result)
