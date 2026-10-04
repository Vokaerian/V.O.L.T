"""Rules window: the user's own Sort rules (settings.json `user_rules`,
sort.py's top rule tier). A modal dialog, a structural sibling of
scan_issues_window.py: header with Close, then a left column (New / Delete
above a rail with one entry per rule) beside the selected rule's editor:
Mod (package ID), Load Before, Load After and a live Example.

Opened from the mod rows' right-click menu, Rules... > Create rule / Show
rules (RimWorldMainScreen._create_rule / _show_rules). Visual design: the
user-approved Design mockup (PLAN.md section 8, "Mockup stage 2"); QSS in
theme.py's "Rules window" section.

No Save button: every edit (the mod field, on every keystroke; adding or
removing a Load Before/After row; New; Delete) goes straight to
SettingsStore.add/update/delete_user_rule, like the mod-color picker. A
failed save shows the screen's warning and leaves the prior value on screen.
Global settings, not part of the load order's unsaved-changes/undo state.

The pure helpers at the top (no Qt) are what tools/checks/
volt_py_rules_window.py tests directly; it also traces the window itself
over a fake PySide6.
"""

from collections import Counter
from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from volt_py import painters
from volt_py.applog import log

# Same window chrome as the Scan issues window (.modal.validation-window).
WINDOW_SIZE = (900, 600)
RAIL_WIDTH = 280  # grid-template-columns: 280px 1fr

BLANK_MOD_LABEL = "(no mod set)"  # a rule whose mod field is still empty
EMPTY_TIER_LABEL = "(none)"  # an Example tier with no mods in it
NOT_FOUND = "No mod with this package ID found."

# Load Before / Load After boxes (.rules-field-box / .rules-field-row).
MAX_VISIBLE_ROWS = 4  # the box grows row by row up to this, then scrolls
BADGE = 20  # .rules-check: 20px circle
ROW_PAD_V = 6  # .rules-field-row: padding 6px 8px
ROW_PAD_H = 8
ROW_HEIGHT = BADGE + 2 * ROW_PAD_V  # 32: the badge is the row's tallest item
ROW_GAP = 4  # .rules-field-box: gap 4px (also its rows' spacing)
CHIP_MIN_WIDTH = 240  # .rules-chip: min-width 240px


# ---- pure logic (no Qt) ----
def norm_id(pid) -> str:
    """How a typed packageId matches a scanned mod id (a mod id is its
    lowercased packageId): trimmed + lowercased, same as sort.py's lookup.
    A non-string (hand-edited settings.json) matches nothing."""
    return pid.strip().lower() if isinstance(pid, str) else ""


def validity(pid, mod_ids) -> bool | None:
    """None for a blank id (no indicator), else whether it names a scanned
    mod (Inactive or Active: `mod_ids` is every scanned mod's id)."""
    i = norm_id(pid)
    return (i in mod_ids) if i else None


def is_known(pid, mod_ids) -> bool:
    return bool(validity(pid, mod_ids))


def display_name(mods: dict, pid) -> str:
    """A rule's target mod as shown on the rail / in the Example: the scanned
    mod's current name (as a pane row shows it: name, else folder), else the
    stored packageId as-is; BLANK_MOD_LABEL for an empty one."""
    i = norm_id(pid)
    if not i:
        return BLANK_MOD_LABEL
    m = mods.get(i)
    if m:
        return m.get("name") or m.get("folder") or pid
    return pid


def rule_numbers(rules: list[dict]) -> list[int | None]:
    """Per entry, its 1-based number among the entries naming the same mod
    (matched like norm_id, in list order), or None when no other entry names
    that mod - the rail's "Rule N" line only shows when a mod has several."""
    keys = [norm_id(r.get("mod")) for r in rules]
    totals = Counter(keys)
    seen: Counter = Counter()
    numbers: list[int | None] = []
    for key in keys:
        seen[key] += 1
        numbers.append(seen[key] if totals[key] > 1 else None)
    return numbers


def rail_lines(rules: list[dict], mods: dict) -> list[tuple[str, str | None]]:
    """(name, secondary line or None) per rail entry."""
    return [
        (display_name(mods, r.get("mod")), f"Rule {n}" if n else None)
        for r, n in zip(rules, rule_numbers(rules))
    ]


def clean_rules(rules) -> list[dict]:
    """The settings list minus anything the window can't address (a
    hand-edited non-dict, or an entry without a string id)."""
    return [r for r in (rules or []) if isinstance(r, dict) and isinstance(r.get("id"), str)]


def rule_mod(rule: dict) -> str:
    mod = rule.get("mod")
    return mod if isinstance(mod, str) else ""


def target_ids(rule: dict, field: str) -> list[str]:
    """A rule's load_before / load_after as a fresh list of strings (junk in
    a hand-edited file is left out)."""
    ids = rule.get(field)
    return [x for x in ids if isinstance(x, str)] if isinstance(ids, list) else []


def rows_height(rows: int) -> int:
    """Height of `rows` stacked rows (ROW_GAP between them)."""
    return rows * ROW_HEIGHT + max(rows - 1, 0) * ROW_GAP


def visible_rows(count: int) -> int:
    return min(count, MAX_VISIBLE_ROWS)


def not_found_hint(missing: int) -> str:
    if missing <= 0:
        return ""
    return NOT_FOUND if missing == 1 else f"No mod found for {missing} of these package IDs."


def next_selection(ids: list[str], removed_index: int) -> str | None:
    """After deleting the entry at removed_index (ids: what's left): the entry
    that moved into its place, else the new last one, else None."""
    if not ids:
        return None
    return ids[min(removed_index, len(ids) - 1)]


def example_tiers(rule: dict, mods: dict) -> dict:
    """The Example box's three tiers, in load order (top loads first):
    {"after": [name...], "self": name, "before": [name...]}."""
    return {
        "after": [display_name(mods, pid) for pid in target_ids(rule, "load_after")],
        "self": display_name(mods, rule_mod(rule)),
        "before": [display_name(mods, pid) for pid in target_ids(rule, "load_before")],
    }


# ---- widgets ----
def _repolish(widget: QWidget) -> None:
    # A property selector isn't re-evaluated on its own after the first polish.
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _set_prop(widget: QWidget, name: str, value) -> None:
    if widget.property(name) != value:
        widget.setProperty(name, value)
        _repolish(widget)


def _label(text: str = "", role: str | None = None) -> QLabel:
    # Plain text: package ids / mod names are user data, never rich text.
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        label.setProperty("role", role)
    return label


def _button(text: str) -> QPushButton:
    button = QPushButton(text)
    # No Enter-activates-default anywhere in this dialog: Enter in an add
    # input must only add the row (returnPressed), never click a button.
    button.setAutoDefault(False)
    return button


def _transparent_scroll(scroll: QScrollArea) -> None:
    # Let the enclosing background show through (setWidget turns autofill on).
    scroll.viewport().setAutoFillBackground(False)
    scroll.widget().setAutoFillBackground(False)


class _Badge(QLabel):
    """.rules-check: found (check on the dependent-green tint) / not found
    (X on a danger tint) circle. Hidden for a blank id, keeping its space so
    the field beside it doesn't jump."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "rules-check")
        self.setFixedSize(BADGE, BADGE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)

    def set_state(self, found: bool | None) -> None:
        self.setVisible(found is not None)
        if found is None:
            return
        self.setText("✓" if found else "✕")
        self.setToolTip("Found in your scanned mods." if found else NOT_FOUND)
        _set_prop(self, "state", "ok" if found else "err")


class _RailEntry(QPushButton):
    """A rail entry (.validation-entry): the rule's mod name over an optional
    muted "Rule N" line. Two text colors, so two labels over an empty button."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("variant", "rules-entry")
        self.setAutoDefault(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)  # padding 6px 10px
        layout.setSpacing(2)  # gap 2px
        self.name = _label()
        self.target = _label(role="rules-target")
        for label in (self.name, self.target):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(label)

    # QPushButton sizes itself from its own (empty) text; size from the labels instead.
    def sizeHint(self) -> QSize:
        return self.layout().sizeHint()

    def minimumSizeHint(self) -> QSize:
        return self.layout().minimumSize()

    def set_lines(self, name: str, secondary: str | None) -> None:
        self.name.setText(name)
        self.target.setText(secondary or "")
        self.target.setVisible(secondary is not None)
        self.updateGeometry()

    def set_selected(self, selected: bool) -> None:
        for widget in (self, self.target):
            _set_prop(widget, "selected", selected)


class _TargetRow(QFrame):
    """.rules-field-row: packageId | badge | x (remove). A not-found row gets
    the warn outline and danger text (.rules-field-row.error)."""

    def __init__(self, pid: str, found: bool) -> None:
        super().__init__()
        self.setProperty("role", "rules-row")
        self.setProperty("error", not found)
        self.setFixedHeight(ROW_HEIGHT)
        layout = QHBoxLayout(self)
        # padding 6px 8px, less the 1px (transparent unless error) border.
        layout.setContentsMargins(ROW_PAD_H - 1, ROW_PAD_V - 1, ROW_PAD_H - 1, ROW_PAD_V - 1)
        layout.setSpacing(8)
        self.text = _label(pid, "rules-row-text")
        self.text.setProperty("error", not found)
        self.text.setToolTip(pid)
        self.text.setMinimumWidth(1)  # a long id is clipped, never widens the window
        self.badge = _Badge()
        self.badge.set_state(found)
        self.remove_button = _button("×")
        self.remove_button.setProperty("variant", "rules-remove")
        self.remove_button.setFixedSize(BADGE, BADGE)
        self.remove_button.setToolTip("Remove")
        layout.addWidget(self.text, 1)
        layout.addWidget(self.badge)
        layout.addWidget(self.remove_button)


class _TargetBox(QFrame):
    """.rules-field-box: one row per packageId, growing downward row by row up
    to MAX_VISIBLE_ROWS, then scrolling; a not-found hint under the rows; and
    an add input (Enter or Add) pinned at the bottom, always visible."""

    def __init__(self, on_add: Callable[[str], bool], on_remove: Callable[[int], None]) -> None:
        super().__init__()
        self.setProperty("role", "rules-box")
        self._on_add = on_add
        self._on_remove = on_remove
        self.rows: list[_TargetRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)  # padding 6px (the 1px border sits outside this)
        layout.setSpacing(ROW_GAP)

        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self._rows = QVBoxLayout(inner)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(ROW_GAP)
        self._rows.addStretch(1)
        self.scroll.setWidget(inner)
        _transparent_scroll(self.scroll)
        layout.addWidget(self.scroll)

        self.hint = _label(role="rules-hint")  # .rules-field-hint
        layout.addWidget(self.hint)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self.add_edit = QLineEdit()
        self.add_edit.setProperty("mono", True)
        self.add_edit.setPlaceholderText("Add a package ID")
        self.add_button = _button("Add")
        add_row.addWidget(self.add_edit, 1)
        add_row.addWidget(self.add_button)
        layout.addLayout(add_row)

        self.add_edit.returnPressed.connect(lambda: self._add())
        self.add_button.clicked.connect(lambda: self._add())

    def _add(self) -> None:
        text = self.add_edit.text().strip()
        if text and self._on_add(text):
            self.add_edit.clear()

    def set_items(self, ids: list[str], mod_ids, *, scroll_to_end: bool = False) -> None:
        for row in self.rows:
            self._rows.removeWidget(row)
            row.deleteLater()
        self.rows = []
        missing = 0
        for n, pid in enumerate(ids):
            found = is_known(pid, mod_ids)
            missing += not found
            row = _TargetRow(pid, found)
            row.remove_button.clicked.connect(lambda _=False, n=n: self._on_remove(n))
            self._rows.insertWidget(n, row)  # before the trailing stretch
            self.rows.append(row)
        shown = visible_rows(len(ids))
        self.scroll.setVisible(shown > 0)
        self.scroll.setFixedHeight(rows_height(shown))
        self.hint.setText(not_found_hint(missing))
        self.hint.setVisible(missing > 0)
        if scroll_to_end:
            # After the new row is laid out: show it (the box may be scrolling).
            QTimer.singleShot(0, self, self._scroll_to_end)

    def _scroll_to_end(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


class RulesWindow(QDialog):
    def __init__(
        self,
        settings,
        mods: dict,
        warn: Callable[[str, str, QWidget], None],
        select_id: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """settings: the screen's SettingsStore (user_rules is read fresh here,
        on every open). mods: the screen's scanned mods (id -> mod), for names
        and found/not-found; never modified. warn(title, what, ..., parent=): the
        screen's _warn. select_id: the entry to select (Create rule's new
        entry; the Load Before input gets focus), else the first entry."""
        super().__init__(parent)
        self.setObjectName("rules")
        self.setWindowTitle("Rules")
        self.setModal(True)
        self._settings = settings
        self._mods = mods
        self._mod_ids = set(mods)  # every scanned mod: Inactive + Active
        self._warn = warn
        self._rules: list[dict] = clean_rules(settings.get()["user_rules"])
        self._sel_id: str | None = None
        self._entries: list[_RailEntry] = []
        self._example_widgets: list[QWidget] = []
        self._self_chip: QLabel | None = None

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()  # .validation-head: h2 | Close
        header.setSpacing(8)
        title = QLabel("Rules")
        title.setProperty("role", "modal-title")
        header.addWidget(title, 1)
        self.close_button = _button("Close")
        header.addWidget(self.close_button)
        layout.addLayout(header)

        body = QHBoxLayout()  # 280px | 1fr, gap 8px
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        body.addWidget(self._build_left())
        body.addWidget(self._build_right(), 1)
        layout.addLayout(body, 1)

        self.new_button.clicked.connect(lambda: self._new())
        self.delete_button.clicked.connect(lambda: self._delete())
        self.close_button.clicked.connect(lambda: self.reject())  # Esc rejects too (QDialog default)
        self.mod_edit.textEdited.connect(lambda text: self._edit_mod(text))

        width, height = WINDOW_SIZE
        if parent is not None:
            bounds = parent.window().size()
            width, height = min(width, bounds.width() - 32), min(height, bounds.height() - 32)
        self.resize(width, height)

        self._rebuild_rail()
        ids = [r["id"] for r in self._rules]
        self._select(select_id if select_id in ids else (ids[0] if ids else None))
        if self._rule() is not None and select_id in ids:
            self.before_box.add_edit.setFocus()
        else:
            self.close_button.setFocus()

    # ---- layout ----
    def _build_left(self) -> QWidget:
        # .rules-rail-col: New | Delete above the rail, gap 8px.
        column = QWidget()
        column.setFixedWidth(RAIL_WIDTH)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        actions = QHBoxLayout()  # .rules-rail-actions: two equal buttons, gap 8px
        actions.setSpacing(8)
        self.new_button = _button("New")
        self.delete_button = _button("Delete")
        actions.addWidget(self.new_button, 1)
        actions.addWidget(self.delete_button, 1)
        layout.addLayout(actions)

        # .validation-rail: --panel-2, border, radius, padding 4px, gap 4px, scrolls.
        scroll = self._rail_scroll = QScrollArea()
        scroll.setObjectName("rulesRail")
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._rail = QVBoxLayout(inner)
        self._rail.setContentsMargins(4, 4, 4, 4)
        self._rail.setSpacing(4)
        self._empty = _label("No rules yet.")
        self._empty.setProperty("muted", True)
        self._empty.setContentsMargins(10, 6, 10, 6)  # lines up with an entry's text
        self._rail.addWidget(self._empty)
        self._rail.addStretch(1)
        scroll.setWidget(inner)
        _transparent_scroll(scroll)
        layout.addWidget(scroll, 1)
        return column

    def _build_right(self) -> QScrollArea:
        # .rules-right: a gap-14px column that scrolls when it outgrows the window.
        scroll = self._right = QScrollArea()
        scroll.setObjectName("rulesRight")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        right = QVBoxLayout(inner)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(14)

        # .rules-mod-field: label, then input | badge (gap 8px).
        self.mod_edit = QLineEdit()
        self.mod_edit.setProperty("mono", True)
        self.mod_badge = _Badge()
        mod_row = QHBoxLayout()
        mod_row.setSpacing(8)
        mod_row.addWidget(self.mod_edit, 1)
        mod_row.addWidget(self.mod_badge)
        right.addLayout(self._field("Mod (package ID)", mod_row))

        self.before_box = _TargetBox(
            lambda text: self._add_target("load_before", text), lambda n: self._remove_target("load_before", n)
        )
        self.after_box = _TargetBox(
            lambda text: self._add_target("load_after", text), lambda n: self._remove_target("load_after", n)
        )
        right.addLayout(self._field("Load Before", self.before_box))
        right.addLayout(self._field("Load After", self.after_box))

        # .rules-example: "Example", then the centered three-tier stack (gap 4px).
        example = QFrame()
        example.setProperty("role", "rules-example")
        example_layout = QVBoxLayout(example)
        example_layout.setContentsMargins(12, 12, 12, 12)
        example_layout.setSpacing(0)
        example_layout.addWidget(painters.TerminalLabel("Example", rule="heading"))  # a terminal heading (step 3.4)
        example_layout.addSpacing(8)  # .rules-example-label: margin-bottom 8px
        self._example = QVBoxLayout()
        self._example.setSpacing(4)
        example_layout.addLayout(self._example)
        right.addWidget(example)
        right.addStretch(1)

        scroll.setWidget(inner)
        _transparent_scroll(scroll)
        return scroll

    @staticmethod
    def _field(title: str, content) -> QVBoxLayout:
        # label { display: block; margin-bottom: 6px } - a copper side-rule
        # terminal heading (design step 3.4; was a 600 sans label)
        group = QVBoxLayout()
        group.setSpacing(6)
        group.addWidget(painters.TerminalLabel(title, rule="heading"))
        if isinstance(content, QWidget):
            group.addWidget(content)
        else:
            group.addLayout(content)
        return group

    # ---- state ----
    def _index(self, rule_id: str | None) -> int | None:
        return next((n for n, r in enumerate(self._rules) if r["id"] == rule_id), None)

    def _rule(self, rule_id: str | None = None) -> dict | None:
        n = self._index(self._sel_id if rule_id is None else rule_id)
        return None if n is None else self._rules[n]

    def _replace(self, updated: dict) -> None:
        n = self._index(updated["id"])
        if n is not None:
            self._rules[n] = updated

    def _box(self, field: str) -> _TargetBox:
        return self.before_box if field == "load_before" else self.after_box

    def _rebuild_rail(self) -> None:
        for entry in self._entries:
            self._rail.removeWidget(entry)
            entry.deleteLater()
        self._entries = []
        for n, rule in enumerate(self._rules):
            entry = _RailEntry()
            entry.clicked.connect(lambda _=False, rid=rule["id"]: self._select(rid))
            self._rail.insertWidget(n + 1, entry)  # after the empty label, before the stretch
            self._entries.append(entry)
        self._refresh_rail()

    def _refresh_rail(self) -> None:
        """Every entry's name / Rule N line (one entry's mod change can add or
        drop another's Rule N) and the selection, in place."""
        for entry, rule, (name, secondary) in zip(self._entries, self._rules, rail_lines(self._rules, self._mods)):
            entry.set_lines(name, secondary)
            entry.set_selected(rule["id"] == self._sel_id)
        self._empty.setVisible(not self._rules)

    def _select(self, rule_id: str | None) -> None:
        self._sel_id = rule_id if self._rule(rule_id) is not None else None
        self._refresh_rail()
        rule = self._rule()
        self.delete_button.setEnabled(rule is not None)
        self._right.setVisible(rule is not None)
        if rule is None:
            return
        self.mod_edit.setText(rule_mod(rule))  # setText: no textEdited, so no save
        self.mod_badge.set_state(validity(rule_mod(rule), self._mod_ids))
        for field in ("load_before", "load_after"):
            self._box(field).add_edit.clear()
            self._box(field).set_items(target_ids(rule, field), self._mod_ids)
        self._render_example(rule)
        QTimer.singleShot(0, self, self._scroll_rail_to_selected)

    def _scroll_rail_to_selected(self) -> None:
        n = self._index(self._sel_id)
        if n is not None and n < len(self._entries):
            self._rail_scroll.ensureWidgetVisible(self._entries[n])

    def _render_example(self, rule: dict) -> None:
        """loads first (After) / After chips / this mod / Before chips / loads
        last (Before). No arrows between the tiers (dropped in the mockup)."""
        for widget in self._example_widgets:
            self._example.removeWidget(widget)
            widget.deleteLater()
        self._example_widgets = []
        tiers = example_tiers(rule, self._mods)

        def add(widget: QWidget) -> QWidget:
            self._example.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
            self._example_widgets.append(widget)
            return widget

        def chips(names: list[str], tier: str, pids: list[str]) -> None:
            if not names:
                add(_label(EMPTY_TIER_LABEL)).setProperty("muted", True)
            for name, pid in zip(names, pids):
                add(self._chip(name, tier, pid))

        add(_label("loads first (After)", "rules-caption"))
        chips(tiers["after"], "after", target_ids(rule, "load_after"))
        self._self_chip = add(self._chip(tiers["self"], "self", rule_mod(rule)))
        chips(tiers["before"], "before", target_ids(rule, "load_before"))
        add(_label("loads last (Before)", "rules-caption"))

    @staticmethod
    def _chip(name: str, tier: str, pid: str) -> QLabel:
        chip = _label(name, "rules-chip")
        chip.setProperty("tier", tier)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setMinimumWidth(CHIP_MIN_WIDTH)
        if pid.strip():
            chip.setToolTip(pid)
        return chip

    # ---- actions (each saves at once) ----
    def _save_failed(self, title: str, what: str, err: Exception) -> None:
        log(f"rules: {what} FAILED: {err!r}")
        self._warn(title, "VOLT couldn't save your rules.", means="The last change wasn't kept.",
                   tryit="Make sure VOLT's folder isn't read-only or full, then try again.",
                   details=str(err), parent=self)

    def _edit_mod(self, text: str) -> None:
        rule = self._rule()
        if rule is None:
            return
        try:
            updated = self._settings.update_user_rule(rule["id"], mod=text)
        except (OSError, ValueError) as err:
            self._save_failed("Couldn't save rule", f"rule {rule['id']} mod -> {text!r}", err)
            self.mod_edit.setText(rule_mod(rule))  # back to the saved value
            return
        self._replace(updated)
        log(f"rules: rule {rule['id']} mod -> {text!r} (saved)")
        self.mod_badge.set_state(validity(text, self._mod_ids))
        self._refresh_rail()
        if self._self_chip is not None:
            self._self_chip.setText(display_name(self._mods, text))
            self._self_chip.setToolTip(text if text.strip() else "")

    def _add_target(self, field: str, text: str) -> bool:
        """Appends a row to Load Before/After. True if saved (the add input is
        cleared); False leaves the typed text in place."""
        rule = self._rule()
        if rule is None:
            return False
        ids = target_ids(rule, field) + [text]
        try:
            updated = self._settings.update_user_rule(rule["id"], **{field: ids})
        except (OSError, ValueError) as err:
            self._save_failed("Couldn't save rule", f"rule {rule['id']} {field} add {text!r}", err)
            return False
        self._replace(updated)
        log(f"rules: rule {rule['id']} {field} add {text!r} -> {ids} (saved)")
        self._box(field).set_items(target_ids(updated, field), self._mod_ids, scroll_to_end=True)
        self._render_example(updated)
        return True

    def _remove_target(self, field: str, n: int) -> None:
        rule = self._rule()
        if rule is None:
            return
        ids = target_ids(rule, field)
        if not 0 <= n < len(ids):
            return
        removed = ids.pop(n)
        try:
            updated = self._settings.update_user_rule(rule["id"], **{field: ids})
        except (OSError, ValueError) as err:
            self._save_failed("Couldn't save rule", f"rule {rule['id']} {field} remove {removed!r}", err)
            return
        self._replace(updated)
        log(f"rules: rule {rule['id']} {field} remove {removed!r} -> {ids} (saved)")
        self._box(field).set_items(target_ids(updated, field), self._mod_ids)
        self._render_example(updated)

    def _new(self) -> None:
        """New: a blank entry (empty mod field, focused), added and selected."""
        try:
            entry = self._settings.add_user_rule(mod="")
        except (OSError, ValueError) as err:
            self._save_failed("Couldn't create rule", "new rule", err)
            return
        self._rules.append(entry)
        log(f"rules: new blank rule {entry['id']} (saved); {len(self._rules)} rules")
        self._rebuild_rail()
        self._select(entry["id"])
        self.mod_edit.setFocus()

    def _delete(self) -> None:
        rule = self._rule()
        if rule is None:
            return
        n = self._index(rule["id"])
        try:
            self._settings.delete_user_rule(rule["id"])
        except (OSError, ValueError) as err:
            self._save_failed("Couldn't delete rule", f"delete rule {rule['id']}", err)
            return
        del self._rules[n]
        log(
            f"rules: deleted rule {rule['id']} (mod {rule_mod(rule)!r}, before {target_ids(rule, 'load_before')}, "
            f"after {target_ids(rule, 'load_after')}); {len(self._rules)} rules left"
        )
        self._rebuild_rail()
        self._select(next_selection([r["id"] for r in self._rules], n))
