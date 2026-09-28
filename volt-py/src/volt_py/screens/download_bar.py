"""The SteamCMD download row (port of DownloadBar.jsx + styles.css .dl-*),
docked at the right of the main screen's footer while a download is in
flight or paused.

Left to right, as the JSX: the pause / resume button (.dl-btn: .undo-btn's
24x24 square, the global button look; two bars while downloading, a play
triangle while paused, disabled while a Pause is waiting for the run to
stop), the "Downloading..." / "Paused" label, the progress pill (.dl-track
140x10, --panel, 1px --border, radius 5; .dl-fill = 3px --accent stripes
with 3px gaps, from the left, `width: percent%` eased over 0.3s), the
`done / total` counter and the speed (.mono.dl-num: --muted, 12px mono;
.dl-speed: 9ch wide, right-aligned, "-" while paused), and the --warn
triangle when an item failed (its tooltip names each failed item and why).

The state it paints is download_state.DownloadState (pure Python, the
screen's `_dl`); render() maps one to the widgets. Nothing here knows about
SteamCMD: the screen connects `toggled` to its pause / resume handler.

Fill stripes: CSS's repeating-linear-gradient(90deg, accent 0 3px,
transparent 3px 6px) is painted literally - one 3px accent rect every 6px
from the fill's left edge, clipped to the fill's width (a partial stripe at
the end, as the gradient gives) and to the track's rounded inner shape
(overflow: hidden at the padding edge, radius 5 - 1). Exact, and free of
the gradient lookup table's blending at a hard stop, which a
QLinearGradient with RepeatSpread would have added.
"""

import functools

from PySide6.QtCore import Property, QByteArray, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from volt_py import theme
from volt_py.download_state import (
    DownloadState, count_text, failure_summary, failure_tooltip, label_text, percent_of, speed_text, toggle_tooltip,
)

# styles.css (px)
BAR_MARGIN_LEFT = 12  # .dl-bar margin-left
BAR_GAP = 8  # .dl-bar gap
BUTTON_SIZE = 24  # .dl-btn (= .undo-btn)
BUTTON_ICON_SIZE = 12  # the JSX svg's width / height
TRACK_WIDTH, TRACK_HEIGHT = 140, 10  # .dl-track
TRACK_RADIUS = 5
TRACK_BORDER = 1
STRIPE_ON, STRIPE_PERIOD = 3, 6  # .dl-fill: accent 0-3px, transparent 3-6px, repeating
FILL_MS = 300  # .dl-fill transition: width 0.3s ease-out
SPEED_CH = 9  # .dl-speed min-width: 9ch
WARN_ICON_SIZE = 14  # the JSX svg's width / height

# DownloadBar.jsx's inline SVGs, verbatim; `currentColor` becomes the real token.
_PAUSE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 16 16" fill="{color}">'
    '<rect x="3" y="2" width="3.5" height="12" rx="1.25"/>'
    '<rect x="9.5" y="2" width="3.5" height="12" rx="1.25"/>'
    "</svg>"
)
_PLAY_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 16 16" fill="{color}">'
    '<path d="M4 2.5v11l10-5.5z"/>'
    "</svg>"
)
_WARN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16" fill="none" '
    'stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M8 1.75L15 14H1z"/>'
    '<path d="M8 6.25v3.5"/>'
    '<path d="M8 11.9v.1"/>'
    "</svg>"
)


def _render_svg(svg: str, size: int, dpr: float) -> QPixmap:
    """`svg` rasterized at `size` logical px for a device pixel ratio (crisp
    on high-DPI; the mod list's badge-icon pattern)."""
    px = max(1, round(size * dpr))
    pixmap = QPixmap(px, px)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


@functools.cache
def _toggle_icon(paused: bool, dpr: float) -> QIcon:
    """The button's glyph in --text (currentColor), with the disabled look at
    half opacity (button:disabled { opacity: 0.5 } fades the glyph with the
    button; the QSS does the same to the button's own colors)."""
    svg = _PLAY_SVG if paused else _PAUSE_SVG
    normal = _render_svg(svg.format(color=theme.TEXT), BUTTON_ICON_SIZE, dpr)
    faded = QPixmap(normal.size())
    faded.setDevicePixelRatio(dpr)
    faded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(faded)
    painter.setOpacity(0.5)
    painter.drawPixmap(0, 0, normal)
    painter.end()
    icon = QIcon()
    icon.addPixmap(normal, QIcon.Mode.Normal)
    icon.addPixmap(faded, QIcon.Mode.Disabled)
    return icon


@functools.cache
def _warn_pixmap(dpr: float) -> QPixmap:
    return _render_svg(_WARN_SVG.format(color=theme.WARN), WARN_ICON_SIZE, dpr)


def _css_ease_out() -> QEasingCurve:
    """CSS `ease-out` = cubic-bezier(0, 0, 0.58, 1)."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.0, 0.0), QPointF(0.58, 1.0), QPointF(1.0, 1.0))
    return curve


class _Track(QWidget):
    """.dl-track + .dl-fill: the 140x10 pill and its striped fill, painted.
    set_percent() eases the fill's width over FILL_MS like the CSS
    transition (restarted from the current width on every change, so a
    steady stream of progress events glides instead of stepping); the first
    value after a show is set outright (no transition on mount)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(TRACK_WIDTH, TRACK_HEIGHT)
        self.setAccessibleName("SteamCMD download progress")  # the JSX's aria-label
        self._fill = 0.0  # the width painted right now, 0-100
        self._target = 0.0  # where the animation is heading
        self._animation = QPropertyAnimation(self, b"fill", self)
        self._animation.setEasingCurve(_css_ease_out())
        self._animation.setDuration(FILL_MS)

    def _get_fill(self) -> float:
        return self._fill

    def _set_fill(self, value: float) -> None:
        self._fill = value
        self.update()

    fill = Property(float, _get_fill, _set_fill)

    def set_percent(self, percent: float, *, animate: bool = True) -> None:
        target = min(100.0, max(0.0, float(percent)))
        if animate and target == self._target:
            return  # already there, or already heading there
        self._animation.stop()
        self._target = target
        if not animate:
            self._set_fill(target)
            return
        self._animation.setStartValue(self._fill)
        self._animation.setEndValue(target)
        self._animation.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(self.rect())
        # background: var(--panel); border: 1px solid var(--border); border-radius: 5px
        painter.setPen(QPen(QColor(theme.BORDER), TRACK_BORDER))
        painter.setBrush(QColor(theme.PANEL))
        half = TRACK_BORDER / 2
        painter.drawRoundedRect(outer.adjusted(half, half, -half, -half), TRACK_RADIUS - half, TRACK_RADIUS - half)
        # .dl-fill: absolute inside the padding box (left: 0; top: 0; bottom: 0),
        # width: percent% of it, clipped by overflow: hidden (the inner radius).
        inner = outer.adjusted(TRACK_BORDER, TRACK_BORDER, -TRACK_BORDER, -TRACK_BORDER)
        width = inner.width() * self._fill / 100
        if width <= 0:
            painter.end()
            return
        clip = QPainterPath()
        clip.addRoundedRect(inner, TRACK_RADIUS - TRACK_BORDER, TRACK_RADIUS - TRACK_BORDER)
        painter.setClipPath(clip)
        painter.setClipRect(QRectF(inner.left(), inner.top(), width, inner.height()), Qt.ClipOperation.IntersectClip)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.ACCENT))
        x = inner.left()
        while x < inner.left() + width:
            painter.drawRect(QRectF(x, inner.top(), STRIPE_ON, inner.height()))
            x += STRIPE_PERIOD
        painter.end()


class DownloadBar(QWidget):
    """The .dl-bar row. render(state, titles) paints a DownloadState;
    `toggled` is the pause / resume button's click."""

    toggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("downloadBar")
        self._state: DownloadState | None = None
        row = QHBoxLayout(self)
        row.setContentsMargins(BAR_MARGIN_LEFT, 0, 0, 0)
        row.setSpacing(BAR_GAP)

        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("downloadToggle")  # theme.py: padding 0, as #undoButton
        self.toggle_button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
        self.toggle_button.setIconSize(QSize(BUTTON_ICON_SIZE, BUTTON_ICON_SIZE))
        self.toggle_button.clicked.connect(lambda: self.toggled.emit())
        row.addWidget(self.toggle_button)

        self.label = QLabel()
        row.addWidget(self.label)

        self.track = _Track()
        row.addWidget(self.track)

        self.count_label = QLabel()
        self.count_label.setProperty("role", "dl-num")
        row.addWidget(self.count_label)

        self.speed_label = QLabel()
        self.speed_label.setProperty("role", "dl-num")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # min-width: 9ch - nine "0" advances in the label's (mono, QSS-set) font.
        self.speed_label.ensurePolished()
        self.speed_label.setMinimumWidth(SPEED_CH * self.speed_label.fontMetrics().horizontalAdvance("0"))
        row.addWidget(self.speed_label)

        self.warn_icon = QLabel()
        self.warn_icon.setFixedSize(WARN_ICON_SIZE, WARN_ICON_SIZE)
        self.warn_icon.setVisible(False)
        row.addWidget(self.warn_icon)

        # Width from its content, never stretched by the footer row.
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    def render(self, state: DownloadState, titles: dict[str, str]) -> None:
        """Paint `state` (the screen's _dl; titles = its workshop_titles, for
        the failure tooltip). The first render after a clear() sets the fill
        outright; later ones ease it."""
        first = self._state is None
        self._state = state
        dpr = self.devicePixelRatioF()
        self.toggle_button.setIcon(_toggle_icon(state.paused, dpr))
        tooltip = toggle_tooltip(state)
        self.toggle_button.setToolTip(tooltip)
        self.toggle_button.setAccessibleName(tooltip)
        self.toggle_button.setEnabled(not state.pausing)
        self.label.setText(label_text(state))
        self.track.set_percent(percent_of(state), animate=not first)
        self.count_label.setText(count_text(state))
        self.speed_label.setText(speed_text(state))
        if state.failed:
            self.warn_icon.setPixmap(_warn_pixmap(dpr))
            self.warn_icon.setToolTip(failure_tooltip(state, titles))
            self.warn_icon.setAccessibleName(failure_summary(state))
            self.warn_icon.setVisible(True)
        else:
            self.warn_icon.setVisible(False)
            self.warn_icon.setToolTip("")

    def clear(self) -> None:
        """The row went away (state None): forget the last state so the next
        render starts fresh (no easing from the old fill)."""
        self._state = None
        self.track.set_percent(0.0, animate=False)

    def state(self) -> DownloadState | None:
        return self._state
