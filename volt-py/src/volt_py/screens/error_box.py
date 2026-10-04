"""The friendly error box every screen shows a failure with (0.6.24,
PLAN.md §10 (i)): a standard QMessageBox in three parts - what happened (the
main text), what it means and what to try (the informative text) - plus a
"Copy details" button that puts the raw technical detail (exception text,
paths) on the clipboard, for whoever is helping; the same detail sits behind
Qt's own "Show Details..." toggle. OK is the default and the
escape button. Every box is logged with all its parts, details included
(ENV.md §10: the log stays rich even where the box is plain).

Shared by both managers and their windows: each screen's _warn() is a thin
wrapper over show_error().
"""

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox, QWidget

from volt_py.applog import clip, log

COPY_LABEL = "Copy details"
COPIED_LABEL = "Copied"
TRY_PREFIX = "What to try: "


def info_text(means: str = "", tryit: str = "") -> str:
    """The box's informative text: what it means, then "What to try: ..."."""
    return "\n\n".join(p for p in (means, TRY_PREFIX + tryit if tryit else "") if p)


def details_text(title: str, what: str, details: str) -> str:
    """What "Copy details" puts on the clipboard: the box's title and first
    line, then the raw detail."""
    return f"{title}\n{what}\n\n{details}\n"


def show_error(parent: QWidget | None, title: str, what: str, *, means: str = "", tryit: str = "",
               details: str = "", log_prefix: str = "") -> None:
    """A Warning box: `what` happened, what it `means`, what to `try`, and a
    Copy details button when there are `details` (no button without them)."""
    log(f"{log_prefix}warning shown: {title}: {what}"
        + (f" | means: {means}" if means else "") + (f" | try: {tryit}" if tryit else "")
        + (f" | details: {clip(details)}" if details else ""))
    box = QMessageBox(QMessageBox.Icon.Warning, title, what, QMessageBox.StandardButton.Ok, parent)
    box.setInformativeText(info_text(means, tryit))
    if details:
        box.setDetailedText(details)  # Qt's own "Show Details..." toggle: read it without pasting it anywhere
    copy = box.addButton(COPY_LABEL, QMessageBox.ButtonRole.ActionRole) if details else None
    box.setDefaultButton(QMessageBox.StandardButton.Ok)
    box.setEscapeButton(QMessageBox.StandardButton.Ok)
    # ponytail: QMessageBox closes on every button, Copy details included; the box is shown again after a copy
    # (one frame's flicker) rather than a hand-built dialog. Swap for a QDialog if the flicker ever bothers anyone.
    while True:
        box.exec()
        if copy is None or box.clickedButton() is not copy:
            break
        QGuiApplication.clipboard().setText(details_text(title, what, details))
        copy.setText(COPIED_LABEL)
        log(f"{log_prefix}warning {title}: details copied to the clipboard")
