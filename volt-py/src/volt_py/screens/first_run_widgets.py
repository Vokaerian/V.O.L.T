"""The first-run guidance widgets (PLAN.md §10 (c)/(f)/(g), v0.6.23; their
words and every show / tick rule live Qt-free in volt_py/first_run.py):

  EmptyStateCard  over the Active list's empty dot grid while nothing is
                  open (both managers): title, one plain paragraph, a
                  primary "Create a ..." and an accent-outline "Import one
                  someone shared" - the screen wires both to its existing
                  New and Import... actions.
  ChecklistStrip  the Thunderstore managers' get-started band under the
                  profile bar: four numbered steps (done = a drawn --ok
                  check, the next one outlined in blue) and a "Hide" link.
  WelcomePanel    game select's one-time welcome, a row above the caption.

Plain Qt widgets styled by theme.py's QSS (role / variant / panel
properties): no painting of their own and no graphics effect - each screen
shows / hides them under painters.crossfade (the Animations setting
applies). Every button is a QPushButton: hover / press come from the QSS,
the keyboard focus ring from icons.VoltStyle, like everywhere else."""

from PySide6.QtCore import QEvent, QObject, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from volt_py import first_run as fr, icons, painters, theme

CARD_MAX_WIDTH = 320  # logical px; a narrower Active pane narrows the card (_FitWidth)
CARD_INSET = 12  # logical px kept clear between the card and each side of the list
WELCOME_WIDTH = 600  # logical px, the panel's maximum (game select's content is >= ~830 at the 1000 px minimum window)
WELCOME_MIN_WIDTH = 320  # logical px: below its maximum it narrows and its text wraps onto more lines
CHECK_ICON_PX = 12  # a done step's drawn check


def _text(text: str, role: str | None = None, *, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if role:
        label.setProperty("role", role)
    if muted:
        label.setProperty("muted", True)
    return label


def _repolish(widget: QWidget) -> None:
    # a property selector isn't re-evaluated on its own after the first polish
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class _FitWidth(QObject):
    """Keeps the card CARD_INSET clear of each side of the list it sits on,
    never wider than CARD_MAX_WIDTH (the list's Resize events only)."""

    def __init__(self, view: QWidget, card: QWidget) -> None:
        super().__init__(card)
        self._card = card
        view.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            self._card.setFixedWidth(max(0, min(CARD_MAX_WIDTH, obj.width() - 2 * CARD_INSET)))
        return False


class EmptyStateCard(QFrame):
    """The empty-state card. `texts`: first_run.PROFILE_CARD / LOAD_ORDER_CARD,
    already filled; on_create / on_import: the screen's existing actions.
    The screen adds it to the Active list's grid cell (centred, above the
    list, which stays live underneath) and keeps its buttons' enabled state
    in step with New / Import...."""

    def __init__(self, texts: dict, on_create, on_import, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "first-run-card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)  # "Import one someone shared" still fits at the 240px pane minimum
        layout.setSpacing(8)
        self.title = _text(texts["title"], "first-run-title")
        self.body = _text(texts["body"], muted=True)
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        layout.addSpacing(4)
        self.create_button = QPushButton(texts["create"])
        self.create_button.setProperty("variant", "primary")
        self.import_button = QPushButton(texts["import"])
        self.import_button.setProperty("variant", "accent-outline")
        for button, fn in ((self.create_button, on_create), (self.import_button, on_import)):
            button.clicked.connect(lambda _checked=False, fn=fn: fn())
            layout.addWidget(button)
        self.setFixedWidth(CARD_MAX_WIDTH)

    def follow(self, view: QWidget) -> None:
        """Track `view`'s width (the Active list the card sits on)."""
        _FitWidth(view, self)


class ChecklistStrip(QFrame):
    """The get-started band: "GET STARTED" (a copper terminal label), the
    four steps, "Hide". actions: one callable per step (None = the
    informational fourth step, never clickable); on_hide: the screen's
    dismiss. set_state() is the only way it changes."""

    def __init__(self, game: str, actions, on_hide, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("panel", True)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(6)
        self.title = painters.TerminalLabel(fr.CHECKLIST_TITLE, rule=False)
        self.title.setMinimumWidth(1)  # the first thing to give way in a narrow window (0 would mean "unset")
        row.addWidget(self.title)
        row.addSpacing(6)
        self._labels = [s.replace("{game}", game) for s in fr.STEPS]
        self._tips = [s.replace("{game}", game) for s in fr.STEP_TIPS]
        self.steps: list[QPushButton] = []
        for fn in actions:
            button = QPushButton()
            button.setProperty("variant", "checklist-step")
            button.setIconSize(QSize(CHECK_ICON_PX, CHECK_ICON_PX))
            if fn is not None:
                button.clicked.connect(lambda _checked=False, fn=fn: fn())
            row.addWidget(button)
            self.steps.append(button)
        row.addStretch(1)
        self.hide_button = QPushButton(fr.HIDE_LABEL)
        self.hide_button.setProperty("variant", "link")
        self.hide_button.setToolTip(fr.HIDE_TIP.replace("{game}", game))
        self.hide_button.clicked.connect(lambda: on_hide())
        row.addWidget(self.hide_button)
        self.set_state((False,) * len(self.steps), 0, (False,) * len(self.steps))

    def set_state(self, done, nxt, enabled) -> None:
        """done: a bool per step; nxt: the next step's index (None = all
        done); enabled: whether each step's action can run right now. A done
        step shows the check instead of its number and isn't clickable."""
        for i, button in enumerate(self.steps):
            is_done, is_next = bool(done[i]), i == nxt
            button.setText(self._labels[i] if is_done else f"{i + 1}. {self._labels[i]}")
            button.setIcon(icons.icon("check", theme.OK, theme.OK) if is_done else QIcon())
            button.setEnabled(bool(enabled[i]) and not is_done)
            button.setToolTip(fr.STEP_DONE_TIP if is_done else self._tips[i])
            if button.property("next") != is_next:
                button.setProperty("next", is_next)
                _repolish(button)


class WelcomePanel(QFrame):
    """Game select's welcome: title, one paragraph, "Got it" (on_dismiss)."""

    def __init__(self, on_dismiss, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("panel", True)
        # width from the row (<= WELCOME_WIDTH), height from the wrapped text
        # at that width (heightForWidth via the layout) - never a fixed height
        self.setMinimumWidth(WELCOME_MIN_WIDTH)
        self.setMaximumWidth(WELCOME_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        self.title = _text(fr.WELCOME_TITLE, "first-run-title")
        self.body = _text(fr.WELCOME_BODY, muted=True)
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        row = QHBoxLayout()
        row.addStretch(1)
        self.ok_button = QPushButton(fr.WELCOME_OK)
        self.ok_button.clicked.connect(lambda: on_dismiss())
        row.addWidget(self.ok_button)
        layout.addLayout(row)
