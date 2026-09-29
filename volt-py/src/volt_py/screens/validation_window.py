"""Warnings and errors window (port of ValidationWindow.jsx; RIMWORLD.md
"Validation"): a scrollable rail of every validation issue
(validation.validate_active), grouped under one header per affected mod,
RimPy-style; the right side shows the selected issue's mod (the regular
details panel, screens/details_panel.py) over that issue's detail text.
Warn-only: closing it is the only action.

Opened from the actions column's merged "⚠ N · ✕ M" button (unscoped: the
first issue) or from an Active row's warning / error icon (scoped to that
issue's key) - RimWorldMainScreen._show_validation. A modal dialog, like the
Scan issues window: the load order can't change while it is open, so it
shows the issues it was given (the Electron overlay's live re-render has
nothing to follow here either - its backdrop blocks the lists too).

The copy (LABEL, RAIL_LABEL, issue_summary, blocking_rules, detail_text) is
ValidationWindow.jsx's, verbatim. issue_summary is also the tooltip of the
Active pane's per-row issue icons (screens/mod_list.py imports it, as
ModList.jsx imports issueSummary). Issues are validation.py's dicts: "key",
"mod_id", "kind", "severity", "targets", plus "rule_sources" on
order-dependency-conflict.
"""

import html

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

from volt_py import painters, theme
from volt_py.applog import log
from volt_py.screens.details_panel import DetailsPanel

LABEL = {
    "order-before": "Should be loaded before:",
    "order-after": "Should be loaded after:",
    "order-dependency": "Should be loaded after (dependencies):",
    "order-dependency-conflict": "Should be loaded after (dependencies, blocked by a load order rule):",
    "inactive": "Missing dependencies (inactive):",
    "not-found": "Missing dependencies (not installed):",
    "conflict": "Incompatible with:",
}

# Rail buttons only: the right-side detail repeats the qualifier and the full target list.
RAIL_LABEL = {
    "order-before": "Load order",
    "order-after": "Load order",
    "order-dependency": "Load order",
    "order-dependency-conflict": "Load order",
    "inactive": "Missing dependencies",
    "not-found": "Missing dependencies",
    "conflict": "Conflict",
}

# .modal.validation-window: 900 x 600, at most the viewport minus 32px.
WINDOW_SIZE = (900, 600)
RAIL_WIDTH = 280  # .validation-body: grid-template-columns: 280px 1fr
# .validation-right: .details flex 3, .validation-detail flex 2.
DETAILS_STRETCH, DETAIL_STRETCH = 3, 2
GROUP_GAP = 6  # .validation-group + .validation-group { margin-top: 6px }
LIST_INDENT = 18  # .validation-detail ul { padding-left: 18px }


def mod_name(mods: dict, mod_id: str) -> str:
    """lists.js modName: the scanned mod's name, else the id itself."""
    m = mods.get(mod_id)
    return m["name"] if m else mod_id


def issue_summary(issue: dict, mods: dict) -> str:
    """ValidationWindow.jsx issueSummary: one line per issue - its header
    label plus the target mods' names."""
    return f"{LABEL[issue['kind']]} {', '.join(mod_name(mods, t) for t in issue['targets'])}"


def blocking_rules(sources) -> str:
    """ValidationWindow.jsx blockingRules: which rules block an
    'order-dependency-conflict' (issue rule_sources)."""
    community = "community" in sources
    about = "about" in sources
    if community and about:
        return "the RimSort community rules and About.xml loadBefore/loadAfter rules"
    if community:
        return "the RimSort community rules"
    return "About.xml loadBefore/loadAfter rules"


def detail_text(issue: dict, mods: dict) -> str:
    """ValidationWindow.jsx detailText."""
    name = mod_name(mods, issue["mod_id"])
    kind = issue["kind"]
    if kind == "order-before":
        return (
            f"{name}'s own load order rules (its About.xml loadBefore, or the RimSort community rules) say it "
            "must load before these mods, but it is currently below them. Move it above them, or use Sort."
        )
    if kind == "order-after":
        return (
            f"{name}'s own load order rules (its About.xml loadAfter, or the RimSort community rules) say it "
            "must load after these mods, but it is currently above them. Move it below them, or use Sort."
        )
    if kind == "order-dependency":
        return (
            f"{name} requires these mods (modDependencies in About.xml), and they are active but currently load "
            f"after it. A dependency should load before the mods that need it - move {name} below them, or use "
            "Sort."
        )
    if kind == "order-dependency-conflict":
        return (
            f"{name} requires these mods (modDependencies in About.xml), and they are active but currently load "
            f"after it. Normally Sort would fix this, but {blocking_rules(issue.get('rule_sources') or [])} "
            "require the opposite order, so Sort leaves it as is. Resolve the conflicting rule, or reorder "
            "manually if you're sure it's safe."
        )
    if kind == "inactive":
        return (
            f"{name} requires these mods. They are installed but not active - activate them (double-click in the "
            "Inactive list) to fix this."
        )
    if kind == "not-found":
        return (
            f"{name} requires these mods, but none of the scanned folders (game Data, Mods, Steam Workshop) has "
            "them. Install or subscribe to them, then Rescan."
        )
    return (
        f"{name} and these active mods are declared incompatible (incompatibleWith in About.xml). RimWorld "
        "shouldn't run them together - deactivate one side."
    )


def initial_issue(issues: list[dict], initial_key: str | None = None, initial_severity: str | None = None):
    """ValidationWindow.jsx's initial selection: the issue with `initial_key`
    (a row icon) wins over the first issue of `initial_severity` (a count
    button), else the first issue; None when there are none."""
    return (
        next((i for i in issues if i["key"] == initial_key), None)
        or next((i for i in issues if i["severity"] == initial_severity), None)
        or (issues[0] if issues else None)
    )


def group_issues(issues: list[dict]) -> list[tuple[str, list[dict]]]:
    """ValidationWindow.jsx groups: consecutive issues of the same mod under
    one header, in the given order (not re-sorted) - (mod_id, issues)."""
    groups: list[tuple[str, list[dict]]] = []
    for issue in issues:
        if groups and groups[-1][0] == issue["mod_id"]:
            groups[-1][1].append(issue)
        else:
            groups.append((issue["mod_id"], [issue]))
    return groups


def target_html(mods: dict, target: str) -> str:
    """One `<li>` of the detail's target list: "Name (packageId)" with the
    packageId part in .mono, or just the raw id (.mono) when not scanned."""
    mono = f'<span style="font-family: {theme_mono_css()}; font-size: 12px;">'
    m = mods.get(target)
    if m is not None:
        return f"{html.escape(mod_name(mods, target))} {mono}({html.escape(str(m['package_id']))})</span>"
    return f"{mono}{html.escape(target)}</span>"


def theme_mono_css() -> str:
    """--mono as a rich-text font-family list (single quotes: it goes inside
    a double-quoted style attribute)."""
    return ", ".join(f"'{f}'" for f in theme.MONO_FONTS)


def _repolish(widget: QWidget) -> None:
    # A property selector isn't re-evaluated on its own after the first polish.
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _wrapped(text: str = "", *, rich: bool = False) -> QLabel:
    label = QLabel(text)
    # Plain text unless built here as HTML: names/ids can contain '<'.
    label.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    return label


class ValidationWindow(QDialog):
    def __init__(
        self,
        issues: list[dict],
        mods: dict,
        parent: QWidget | None = None,
        *,
        initial_key: str | None = None,
        initial_severity: str | None = None,
    ) -> None:
        """`issues` / `mods`: validate_active's issues and the scanned mods
        (id -> mod). Opens on initial_issue(issues, initial_key,
        initial_severity)."""
        super().__init__(parent)
        self.setObjectName("validation")
        self.setWindowTitle("Load order warnings and errors")  # the overlay's aria-label
        self.setModal(True)
        self._issues = list(issues)
        self._mods = mods
        first = initial_issue(self._issues, initial_key, initial_severity)
        self._sel_key: str | None = first["key"] if first else None
        self._entries: list[tuple[dict, QPushButton]] = []

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()  # .validation-head: h2 ... Close (space-between)
        title = QLabel("Warnings and errors")
        title.setProperty("role", "modal-title")
        header.addWidget(title, 1)
        self.close_button = QPushButton("Close")
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(lambda: self.reject())  # Esc rejects too (QDialog default)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        if self._issues:
            body = QHBoxLayout()  # .validation-body: rail | right
            body.setSpacing(8)
            body.addWidget(self._build_rail())
            right = QVBoxLayout()  # .validation-right: details over the issue detail
            right.setSpacing(8)
            self.details = DetailsPanel()
            right.addWidget(self.details, DETAILS_STRETCH)
            right.addWidget(self._build_detail(), DETAIL_STRETCH)
            body.addLayout(right, 1)
            layout.addLayout(body, 1)
        else:
            empty = QLabel("No warnings or errors in the current load order.")
            empty.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            layout.addWidget(empty, 1)

        width, height = WINDOW_SIZE
        if parent is not None:
            bounds = parent.window().size()
            width, height = min(width, bounds.width() - 32), min(height, bounds.height() - 32)
        self.resize(width, height)
        if self._issues:
            self._render()
        self.close_button.setFocus()
        sel = self._sel()
        log(
            f"validation window: {len(self._issues)} issues, opened on "
            f"{sel['key'] if sel else 'nothing'} (key {initial_key}, severity {initial_severity})"
        )

    # ---- layout ----
    def _build_rail(self) -> QScrollArea:
        # .validation-rail: --panel-2, border, radius, padding 4px 0, scrolls.
        scroll = QScrollArea()
        scroll.setObjectName("validationRail")
        scroll.setFixedWidth(RAIL_WIDTH)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        rail = QVBoxLayout(inner)
        rail.setContentsMargins(0, 4, 0, 4)
        rail.setSpacing(0)
        for n, (mod_id, items) in enumerate(group_issues(self._issues)):
            if n:
                rail.addSpacing(GROUP_GAP)
            header = QLabel(mod_name(self._mods, mod_id))  # .validation-mod
            header.setTextFormat(Qt.TextFormat.PlainText)
            header.setProperty("role", "validation-mod")
            rail.addWidget(header)
            for issue in items:
                entry = QPushButton(RAIL_LABEL[issue["kind"]])  # .validation-entry.<severity>
                entry.setProperty("variant", "validation-entry")
                entry.setProperty("severity", issue["severity"])
                entry.setAutoDefault(False)
                entry.clicked.connect(lambda _=False, key=issue["key"]: self._select(key))
                rail.addWidget(entry)
                self._entries.append((issue, entry))
        rail.addStretch(1)
        scroll.setWidget(inner)
        # Let the rail's background show through (setWidget turns autofill on).
        scroll.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        return scroll

    def _build_detail(self) -> QScrollArea:
        # section.validation-detail: --panel, border (3px --warn / --danger on
        # the left, by severity), radius, padding 10px, scrolls.
        scroll = self._detail = QScrollArea()
        scroll.setObjectName("validationDetail")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        detail = QVBoxLayout(inner)
        detail.setContentsMargins(10, 10, 10, 10)
        detail.setSpacing(0)  # .modal p { margin: 0 }
        # h3 as a copper side-rule terminal heading (design step 3.4); a
        # heading too long for the pane wraps (then without its rule)
        self._heading = painters.TerminalLabel(rule="heading")
        self._heading.setTextFormat(Qt.TextFormat.PlainText)
        self._heading.setWordWrap(True)
        self._heading.setContentsMargins(0, 0, 0, 6)  # h3 margin: 0 0 6px
        self._text = _wrapped()
        detail.addWidget(self._heading)
        detail.addWidget(self._text)
        # The target list (ul), rebuilt per selection (_render).
        self._detail_layout = detail
        self._targets = QWidget()
        detail.addWidget(self._targets)
        detail.addStretch(1)
        scroll.setWidget(inner)
        scroll.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        return scroll

    # ---- state ----
    def _sel(self) -> dict | None:
        """The selected issue (falls back to the first, as the JS does for a
        key that went away)."""
        return next((i for i in self._issues if i["key"] == self._sel_key), None) or (
            self._issues[0] if self._issues else None
        )

    def _select(self, key: str) -> None:
        self._sel_key = key
        log(f"validation window: selected {key}")
        self._render()

    def _render(self) -> None:
        sel = self._sel()
        if sel is None:
            return
        for issue, entry in self._entries:
            selected = issue is sel
            if entry.property("selected") != selected:
                entry.setProperty("selected", selected)
                _repolish(entry)
        self.details.show_mod(self._mods.get(sel["mod_id"]))
        if self._detail.property("severity") != sel["severity"]:
            self._detail.setProperty("severity", sel["severity"])
            _repolish(self._detail)
        self._heading.setText(LABEL[sel["kind"]])
        self._text.setText(detail_text(sel, self._mods))
        # ul: margin-top 6px, padding-left 18px; one row per target (disc | text).
        targets = QWidget()
        rows = QVBoxLayout(targets)
        rows.setContentsMargins(0, 6, 0, 0)
        rows.setSpacing(0)
        for target in sel["targets"]:
            row = QHBoxLayout()
            row.setSpacing(0)
            bullet = QLabel("\u2022")  # the <li> disc, inside the ul's 18px padding
            bullet.setFixedWidth(LIST_INDENT)
            bullet.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            row.addWidget(bullet)
            row.addWidget(_wrapped(target_html(self._mods, target), rich=True), 1)
            rows.addLayout(row)
        self._detail_layout.replaceWidget(self._targets, targets)
        self._targets.deleteLater()
        self._targets = targets
