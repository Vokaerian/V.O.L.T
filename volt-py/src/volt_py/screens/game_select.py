"""Game-selection screen: port of Electron's GameSelect.jsx (+ styles.css's
.game-select / .game-tile rules). Shown first on every launch; picking a game
emits GameSelectScreen.gameSelected(slug), which MainWindow answers by
swapping in that game's screen. One game per run, not persisted, no way back
(TODO.md #30, Electron parity). RimWorld's and Valheim's tiles are enabled so far.

Layout (top to bottom, centered, in a QScrollArea - CSS overflow-y: auto):
the "V. O. L. T." header, a 64x2 copper rule, the subtitle, the "Select a game"
caption, then the tiles in a FlowLayout (flex-wrap, centered rows, 28px gap,
1440px max row width).

Circuit (design step 3.4): the rule is copper (blue stays the hover ring),
the caption a painters.TerminalLabel with a copper rule both sides, the
Coming-soon badge mono terminal caps on a --well, the scrim over the cover
only (the name under it was 1.83:1), and every tile sits on the cached rest
shadow (painters.install_shadows on the grid's host), hidden while a tile's
own hover shadow effect runs.

GameTile draws its own card frame (background, border, hover ring) in
paintEvent so the hover state can be animated: border color, the 1px accent
ring, the drop shadow (QGraphicsDropShadowEffect) and the 3px lift all follow
one `progress` property (0 = rest, 1 = hovered/focused) that a
QPropertyAnimation drives over 150ms with CSS's `ease` curve - the port of
`transition: border-color .15s ease, box-shadow .15s ease, transform .15s ease`.
The lift needs headroom: CSS's translateY(-3px) paints outside the tile's
box, but a Qt child can't paint outside its own rect, so each tile widget is
a slightly larger "slot" (1px on every side for the ring, plus 3px on top for
the lift) with the card drawn inside it. The grid spacing / margins around
the grid subtract that slack, so resting cards sit exactly where the CSS
puts them (28px apart, 26px below the caption).

Tile width is fluid, as in the CSS (`flex: 1 1 300px; min-width: 220px;
max-width: 336px; height: 256px`): FlowLayout's flex mode wraps rows by the
300px basis, then grows/shrinks each row's tiles equally within [220, 336]
(e.g. 4+3 rows of 336px at the default 1600px window). Only the width flexes;
each tile re-crops its cover and re-lays its contents when resized. The slot
slack is a fixed pixel amount, so the flex numbers are just shifted by it
(basis/min/max + 2*RING_PX, gap - 2*RING_PX) and the flex math comes out
identical to the CSS's in card terms.
"""

from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QFocusEvent,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from volt_py import painters, theme
from volt_py.screens.flow_layout import FlowLayout

# volt_py/assets/covers/<slug>.jpg (this module is volt_py/screens/game_select.py).
# Copies of Electron's src/renderer/src/assets/covers/*.jpg.
COVERS_DIR = Path(__file__).resolve().parent.parent / "assets" / "covers"


class Game(NamedTuple):
    key: str
    name: str
    enabled: bool


# GameSelect.jsx's GAMES, same order.
GAMES: tuple[Game, ...] = (
    Game("rimworld", "RimWorld", True),
    Game("zomboid", "Project Zomboid", False),
    Game("lethal", "Lethal Company", False),
    Game("valheim", "Valheim", True),
    Game("sts2", "Slay the Spire 2", False),
    Game("repo", "R.E.P.O.", False),
    Game("palworld", "Palworld", False),
)

# ---- .game-tile geometry ----
TILE_BASIS = 300  # flex: 1 1 300px
TILE_MIN_WIDTH = 220
TILE_MAX_WIDTH = 336
TILE_HEIGHT = 256  # never flexes
COVER_HEIGHT = 190  # .game-tile-cover flex-basis; its 1px border-bottom is extra
BORDER_PX = 1
LIFT_PX = 3  # hover transform: translateY(-3px)
RING_PX = 1  # hover box-shadow: 0 0 0 1px var(--accent)

# ---- hover animation (transition: ... .15s ease) ----
HOVER_MS = theme.MOTION  # 150
SHADOW_OFFSET_Y = 10  # box-shadow: 0 10px 24px rgba(0, 0, 0, 0.55)
SHADOW_BLUR = 24
SHADOW_ALPHA = 0.55

# ---- .game-select / .game-select-grid ----
GAP = 28
GRID_MAX_WIDTH = 1440
PAD_V = 56
PAD_H = 80
CAPTION_TO_GRID = 26
CAPTION_WIDTH = 420  # the SELECT A GAME caption with its rules (step 3.4)


def _css_ease() -> QEasingCurve:
    """CSS `ease` = cubic-bezier(0.25, 0.1, 0.25, 1)."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.25, 0.1), QPointF(0.25, 1.0), QPointF(1.0, 1.0))
    return curve


def _lerp_color(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
    )


def _spaced_label(text: str, role: str, letter_spacing: float) -> QLabel:
    """QLabel styled by `role` in theme.py. QSS has no letter-spacing, so it's
    set on the widget's font; the QSS rule's size/weight still apply on top
    (a QSS font rule only overrides the attributes it names)."""
    label = QLabel(text)
    label.setProperty("role", role)
    font = QFont()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    label.setFont(font)
    return label


def _load_cover(slug: str) -> QPixmap | None:
    """The slug's source cover (loaded once per tile, re-cropped on every
    resize). None if the file is missing - the cover area then shows the
    label's plain --panel background, like a broken <img alt="">."""
    source = QPixmap(str(COVERS_DIR / f"{slug}.jpg"))
    return None if source.isNull() else source


def _cover_pixmap(source: QPixmap, size: QSize, radius: float, dpr: float) -> QPixmap:
    """`source` scaled to fill `size` and center-cropped (CSS
    `object-fit: cover`), with its top corners rounded to `radius` (the
    tile's overflow: hidden + border-radius clip, which QSS can't apply to a
    child)."""
    target = QSize(round(size.width() * dpr), round(size.height() * dpr))
    scaled = source.scaled(
        target, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
    )
    cropped = scaled.copy(
        (scaled.width() - target.width()) // 2,
        (scaled.height() - target.height()) // 2,
        target.width(),
        target.height(),
    )
    result = QPixmap(target)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = radius * dpr
    clip = QPainterPath()
    # Rounded rect extended past the bottom edge: only the top corners round.
    clip.addRoundedRect(QRectF(0, 0, target.width(), target.height() + r), r, r)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    result.setDevicePixelRatio(dpr)
    return result


class GameTile(QWidget):
    """One game's card (.game-tile). Enabled: pointing-hand cursor, keyboard
    focusable, activated by a left click (press + release inside, like a
    button) or Enter/Space; hover and keyboard focus (:hover /
    :focus-visible) animate the highlight. Disabled: not-allowed cursor, no
    focus, no feedback, a scrim with a "Coming soon" badge."""

    activated = Signal(str)

    def __init__(self, game: Game, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.game = game
        self._progress = 0.0  # 0 = rest, 1 = fully highlighted
        self._target = 0.0
        self._hovered = False
        self._has_focus = False
        self._focus_visible = False  # focus came from the keyboard (Tab/Backtab)
        self._pressed = False
        self._shadow: QGraphicsDropShadowEffect | None = None

        self._cover_source = _load_cover(game.key)
        self._cover_width = -1  # inner width the cover pixmap was last cut for
        self._scrim: QFrame | None = None

        self.setAccessibleName(game.name)

        # Card contents, inside the (self-painted) 1px border. Positioned by
        # hand in _relayout() (no QLayout: nothing here should impose a
        # minimum width, e.g. a QLabel's pixmap-sized minimumSizeHint).
        self._body = QWidget(self)

        self._cover = QLabel(self._body)
        self._cover.setProperty("role", "game-tile-cover")
        self._cover.setAlignment(Qt.AlignmentFlag.AlignCenter)

        name = QLabel(game.name, self._body)
        name.setProperty("role", "game-tile-label")
        name.setProperty("soon", not game.enabled)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        self._name = name

        if game.enabled:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self._shadow = QGraphicsDropShadowEffect(self)
            self._shadow.setOffset(0, SHADOW_OFFSET_Y)
            self._shadow.setBlurRadius(SHADOW_BLUR)
            self._shadow.setEnabled(False)  # off at rest: no offscreen render cost
            self.setGraphicsEffect(self._shadow)
            self._animation = QPropertyAnimation(self, b"progress", self)
            self._animation.setEasingCurve(_css_ease())
        else:
            self.setCursor(Qt.CursorShape.ForbiddenCursor)  # cursor: not-allowed
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            # .game-tile-scrim: over the cover only (step 3.4; inside the
            # border, above the cover's rule); sized in _relayout().
            scrim = QFrame(self._body)
            scrim.setProperty("role", "game-tile-scrim")
            self._scrim = scrim
            scrim_layout = QVBoxLayout(scrim)
            scrim_layout.setContentsMargins(0, 0, 0, 0)
            badge = QLabel("Coming soon")  # COMING SOON: caps + spacing on the terminal font
            badge.setProperty("role", "game-tile-badge")
            badge.setFont(painters.terminal_font(10, painters.TERMINAL_SPACING))
            scrim_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignCenter)
            scrim.raise_()

        # The slot: card + ring on every side + lift headroom on top. Height
        # is fixed; width flexes (FlowLayout sets it), within the slot
        # equivalents of min-width/max-width. Set only now, once every child
        # _relayout() touches exists, so no resize can reach it half-built.
        self.setFixedHeight(TILE_HEIGHT + 2 * RING_PX + LIFT_PX)
        self.setMinimumWidth(TILE_MIN_WIDTH + 2 * RING_PX)
        self.setMaximumWidth(TILE_MAX_WIDTH + 2 * RING_PX)
        # Start at the basis width; FlowLayout resizes it (resizeEvent ->
        # _relayout) once the grid is laid out.
        self.resize(self.sizeHint())
        self._relayout()

    # ---- width-dependent geometry ----

    def sizeHint(self) -> QSize:
        return QSize(TILE_BASIS + 2 * RING_PX, TILE_HEIGHT + 2 * RING_PX + LIFT_PX)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        """Fit the card's contents to the current width: the body, cover,
        name and scrim geometry, and (only when the width actually changed)
        a fresh cover crop. Height-wise nothing changes."""
        card = self._card_rect()
        inner_w = card.width() - 2 * BORDER_PX
        inner_h = card.height() - 2 * BORDER_PX
        self._body.resize(inner_w, inner_h)
        cover_h = COVER_HEIGHT + 1  # + its border-bottom
        self._cover.setGeometry(0, 0, inner_w, cover_h)
        self._name.setGeometry(0, cover_h, inner_w, inner_h - cover_h)
        if self._scrim is not None:
            self._scrim.setGeometry(0, 0, inner_w, COVER_HEIGHT)
        if inner_w != self._cover_width and self._cover_source is not None:
            self._cover_width = inner_w
            self._cover.setPixmap(
                _cover_pixmap(
                    self._cover_source,
                    QSize(inner_w, COVER_HEIGHT),
                    theme.RADIUS - BORDER_PX,
                    self.devicePixelRatioF(),
                )
            )
        self._place_body()

    # ---- highlight state (the animated `progress` property) ----

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        was_resting = self._progress == 0
        self._progress = value
        host = self.parentWidget()
        if was_resting != (value == 0) and host is not None:
            # the rest shadow (painted by the host) hides while the hover
            # effect's shadow shows, and comes back at rest
            reach = painters.RAISED_REACH
            host.update(self.geometry().adjusted(-reach, -reach, reach, reach))
        self._place_body()
        if self._shadow is not None:
            color = QColor(Qt.GlobalColor.black)
            color.setAlphaF(SHADOW_ALPHA * value)
            self._shadow.setColor(color)
            self._shadow.setEnabled(value > 0)
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def rest_shadow_target(self) -> QWidget | None:
        """The card's body for the host's rest shadow, None while the tile is
        (partly) highlighted - its QGraphicsDropShadowEffect shows then."""
        return self._body if self._progress == 0 else None

    def _card_rect(self) -> QRect:
        """The card's outer box (border included) at the current lift."""
        return QRect(
            RING_PX,
            RING_PX + round(LIFT_PX * (1.0 - self._progress)),
            self.width() - 2 * RING_PX,
            TILE_HEIGHT,
        )

    def _place_body(self) -> None:
        card = self._card_rect()
        self._body.move(card.x() + BORDER_PX, card.y() + BORDER_PX)

    def _sync_highlight(self) -> None:
        if not self.game.enabled:
            return
        target = 1.0 if self._hovered or (self._has_focus and self._focus_visible) else 0.0
        if target == self._target:
            return
        self._target = target
        self._animation.stop()
        distance = abs(target - self._progress)
        if distance == 0:
            return
        if not theme.animations_enabled():  # Settings > Animations / Windows' Animation effects off
            self._set_progress(target)
            return
        # Reversing mid-transition takes proportionally less time, as CSS's
        # reversed transitions do.
        self._animation.setDuration(max(1, round(HOVER_MS * distance)))
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(target)
        self._animation.start()

    # ---- painting: card background, border, hover ring ----

    def paintEvent(self, event: QPaintEvent) -> None:
        t = self._progress
        outer = QRectF(self._card_rect())
        radius = float(theme.RADIUS)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.PANEL_2))
        painter.drawRoundedRect(outer, radius, radius)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # border-color: --border -> --accent
        painter.setPen(QPen(_lerp_color(theme.BORDER, theme.ACCENT, t), BORDER_PX))
        painter.drawRoundedRect(outer.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)
        if t > 0:
            # box-shadow: 0 0 0 1px var(--accent) - a ring just outside the border.
            ring = QColor(theme.ACCENT)
            ring.setAlphaF(t)
            painter.setPen(QPen(ring, RING_PX))
            painter.drawRoundedRect(outer.adjusted(-0.5, -0.5, 0.5, 0.5), radius + 0.5, radius + 0.5)
        painter.end()

    # ---- interaction (enabled tiles only) ----

    def _activate(self) -> None:
        if self.game.enabled:
            self.activated.emit(self.game.key)

    def enterEvent(self, event: QEnterEvent) -> None:
        super().enterEvent(event)
        self._hovered = True
        self._sync_highlight()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._sync_highlight()

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self._has_focus = True
        reason = event.reason()
        # :focus-visible: only keyboard focus shows the highlight. Window
        # re-activation restores whatever the tile had before.
        if reason in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason):
            self._focus_visible = True
        elif reason != Qt.FocusReason.ActiveWindowFocusReason:
            self._focus_visible = False
        self._sync_highlight()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self._has_focus = False
        if event.reason() != Qt.FocusReason.ActiveWindowFocusReason:
            self._focus_visible = False
        self._sync_highlight()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.game.enabled and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            event.accept()
            if self.rect().contains(event.position().toPoint()):
                self._activate()  # last: the screen may be swapped out from here
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            self.game.enabled
            and not event.isAutoRepeat()
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
        ):
            event.accept()
            self._activate()
            return
        super().keyPressEvent(event)


class GameSelectScreen(QWidget):
    """The whole screen. Emits gameSelected(slug) when an enabled tile is
    activated (GameSelect.jsx's onSelect)."""

    gameSelected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        slack_top = RING_PX + LIFT_PX  # tile slot space above its resting card

        content = QWidget()
        column = QVBoxLayout(content)
        # padding: 56px 80px, less the slots' ring slack at the sides/bottom
        # (the slack above the first row comes off CAPTION_TO_GRID instead).
        column.setContentsMargins(PAD_H - RING_PX, PAD_V, PAD_H - RING_PX, PAD_V - RING_PX)
        column.setSpacing(0)

        # .game-select-header
        column.addWidget(_spaced_label("V. O. L. T.", "game-select-title", 11), 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(16)
        accent_bar = QFrame()
        accent_bar.setProperty("role", "game-select-accent-bar")
        accent_bar.setFixedSize(64, 2)
        column.addWidget(accent_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(14)
        # text-transform: uppercase in the CSS; typed pre-uppercased here.
        subtitle = _spaced_label("VOKAERIAN'S OMNI-GAME LOAD-ORDER TOOL", "game-select-subtitle", 3)
        column.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignHCenter)

        column.addSpacing(44)
        caption = painters.TerminalLabel("Select a game", rule="both")
        caption.setFixedWidth(CAPTION_WIDTH)
        column.addWidget(caption, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(CAPTION_TO_GRID - slack_top)

        # .game-select-grid + .game-tile's flex sizing, every width shifted by
        # the slot slack (2 * RING_PX per slot, taken back off the gap and
        # added to the row cap) so the flex math, in card terms, is exactly
        # the CSS's: basis 300, [220, 336], gap 28, max row 1440.
        grid = FlowLayout(
            horizontal_spacing=GAP - 2 * RING_PX,
            vertical_spacing=GAP - 2 * RING_PX - LIFT_PX,
            max_row_width=GRID_MAX_WIDTH + 2 * RING_PX,
            item_basis_width=TILE_BASIS + 2 * RING_PX,
            item_min_width=TILE_MIN_WIDTH + 2 * RING_PX,
            item_max_width=TILE_MAX_WIDTH + 2 * RING_PX,
        )
        # Installed before the tiles are added, and each tile parented to
        # `content` up front, so no tile is ever briefly a top-level window
        # (the enabled tile carries a QGraphicsEffect).
        column.addLayout(grid)
        tiles = []
        for game in GAMES:
            tile = GameTile(game, content)
            if game.enabled:
                tile.activated.connect(self.gameSelected)
            grid.addWidget(tile)
            tiles.append(tile)
        painters.install_shadows(content, lambda: [b for b in (t.rest_shadow_target() for t in tiles) if b is not None])
        column.addStretch(1)  # content stays top-aligned in a tall window

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        # Let the main window's --bg show through (setWidget turns autofill on).
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
