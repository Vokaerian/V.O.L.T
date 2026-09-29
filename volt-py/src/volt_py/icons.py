"""VOLT's drawn icons (design phase 2, memory/DESIGN.md §4) and the app's
style (VoltStyle): line icons drawn by Qt itself from QPainterPath - no
emoji, no asset, no icon font - in theme.py token colors, rendered on
demand at the exact device size (a QIconEngine: crisp at 100/125/150/200%,
never a scaled bitmap).

- icon(name, color, disabled): a QIcon for buttons / labels / actions, with
  its own Disabled-mode color (Qt picks it whenever the widget is disabled).
- pixmap(name, color, size, dpr): one cached pixmap (delegate painting).
- inline(name, color, size): an <img> for a rich-text QLabel (a data: URL -
  QTextDocument decodes those), sized in logical px, rendered at the app's
  device pixel ratio.
- VoltStyle: Fusion + the drawn QMessageBox icons (standardIcon), the drawn
  radio / check box indicators (drawPrimitive, step 3.4) + the app-wide
  polish hooks: the keyboard focus ring on every QPushButton, the terminal
  font on every modal title (painters.py), long tooltips wrapped, and the
  Windows 11 title bar / popup border colours (step 3.4).

Every icon is drawn on a 16-unit grid (the mockup's 16px SVG viewBox),
stroked at 1.5 units rounded to whole device px.
"""

import base64
import functools
import math
import sys

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QObject, QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QInputDialog, QLabel, QProxyStyle, QPushButton, QStyle, QWidget

from volt_py import painters, theme

STROKE = 1.5  # grid units (1.5px at 16px)
GRID = 16.0


def _stroke_path(p: QPainter, path: QPainterPath, color: QColor, unit: float) -> None:
    width = max(1.0, round(STROKE * unit)) / unit  # whole device px, in grid units
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _fill(p: QPainter, path: QPainterPath, color: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(path)


def _lines(*points_lists) -> QPainterPath:
    path = QPainterPath()
    for points in points_lists:
        path.moveTo(*points[0])
        for pt in points[1:]:
            path.lineTo(*pt)
    return path


def _dot(x: float, y: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(x, y), r, r)
    return path


def _draw_download(p, c, u):  # ⬇ downloads: an arrow into a tray
    _stroke_path(p, _lines([(8, 2.5), (8, 10.5)], [(4.5, 7), (8, 10.5), (11.5, 7)], [(3, 13.5), (13, 13.5)]), c, u)


def _draw_arrow_down(p, c, u):  # ↓ will be pulled in
    _stroke_path(p, _lines([(8, 2.5), (8, 13)], [(4, 9), (8, 13), (12, 9)]), c, u)


def _draw_check(p, c, u):  # ✓
    _stroke_path(p, _lines([(3, 8.5), (6.5, 12), (13, 4.5)]), c, u)


def _draw_box(p, c, u):  # an unchecked check box (Browse Mods' toggles, 3.2): a 13-unit hollow square, 1.5 stroke
    path = QPainterPath()
    path.addRoundedRect(QRectF(2.25, 2.25, 11.5, 11.5), 2.25, 2.25)
    _stroke_path(p, path, c, u)


def _draw_box_checked(p, c, u):  # the checked one: a filled 13-unit square in `c`, an --ink check in it
    box = QPainterPath()
    box.addRoundedRect(QRectF(1.5, 1.5, 13, 13), 3, 3)
    _fill(p, box, c)
    _stroke_path(p, _lines([(4.85, 8.2), (6.9, 10.25), (11.15, 5.75)]), QColor(theme.INK), u)


def _draw_radio(p, c, u):  # an unchecked radio button (step 3.4): a 12.5-unit ring, 1.5 stroke
    _stroke_path(p, _dot(8, 8, 6.25), c, u)


def _draw_radio_on(p, c, u):  # the checked one: the ring and a 6.4-unit dot, both in `c`
    _stroke_path(p, _dot(8, 8, 6.25), c, u)
    _fill(p, _dot(8, 8, 3.2), c)


def _draw_x(p, c, u):  # ✕ (close, error)
    _stroke_path(p, _lines([(4, 4), (12, 12)], [(12, 4), (4, 12)]), c, u)


def _draw_warn(p, c, u):  # ⚠ outline triangle + !
    tri = _lines([(8, 1.9), (14.6, 13.6), (1.4, 13.6), (8, 1.9)])
    tri.closeSubpath()
    _stroke_path(p, tri, c, u)
    _stroke_path(p, _lines([(8, 6.2), (8, 9.4)]), c, u)
    _fill(p, _dot(8, 11.6, 0.95), c)


def _star_path(cx: float, cy: float, outer: float, inner: float) -> QPainterPath:
    path = QPainterPath()
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        a = -math.pi / 2 + i * math.pi / 5
        pt = (cx + r * math.cos(a), cy + r * math.sin(a))
        path.moveTo(*pt) if i == 0 else path.lineTo(*pt)
    path.closeSubpath()
    return path


def _draw_star(p, c, u):  # ★ ratings: a filled star
    _fill(p, _star_path(8, 8.6, 6.8, 2.9), c)


def _draw_people(p, c, u):  # 👥 the author / team
    head = QPainterPath()
    head.addEllipse(QPointF(6, 5.2), 2.4, 2.4)
    body = QPainterPath()
    body.moveTo(1.6, 13.8)
    body.cubicTo(1.6, 10.8, 3.5, 9.4, 6, 9.4)
    body.cubicTo(8.5, 9.4, 10.4, 10.8, 10.4, 13.8)
    back = QPainterPath()
    back.moveTo(10.2, 3.1)
    back.cubicTo(11.9, 3.0, 13.0, 4.1, 13.0, 5.4)
    back.cubicTo(13.0, 6.7, 12.0, 7.7, 10.6, 7.8)
    back.moveTo(12.0, 9.6)
    back.cubicTo(13.6, 10.0, 14.6, 11.3, 14.6, 13.6)
    for part in (head, body, back):
        _stroke_path(p, part, c, u)


def _draw_link(p, c, u):  # 🔗 website: two chain links on a diagonal
    for cx, cy in ((5.6, 10.4), (10.4, 5.6)):
        link = QPainterPath()
        link.addRoundedRect(QRectF(-4, -1.9, 8, 3.8), 1.9, 1.9)
        t = QTransform()
        t.translate(cx, cy)
        t.rotate(-45)
        _stroke_path(p, t.map(link), c, u)
    _stroke_path(p, _lines([(6.4, 9.6), (9.6, 6.4)]), c, u)


def _draw_copy(p, c, u):  # ⧉ copy
    front = QPainterPath()
    front.addRoundedRect(QRectF(5.5, 5.5, 8, 8), 1.5, 1.5)
    back = QPainterPath()
    back.moveTo(2.5, 10.5)
    back.lineTo(2.5, 4)
    back.quadTo(2.5, 2.5, 4, 2.5)
    back.lineTo(10.5, 2.5)
    _stroke_path(p, front, c, u)
    _stroke_path(p, back, c, u)


# Dialog icons (QMessageBox): their own token colors, whatever `c` is.
def _draw_dlg_question(p, c, u):
    _draw_ring_glyph(p, u, "?")


def _draw_dlg_info(p, c, u):
    _draw_ring_glyph(p, u, "i")


def _draw_ring_glyph(p, u, glyph: str) -> None:
    ring = _dot(8, 8, 6.9)
    width = max(1.0, round(1.2 * u)) / u
    pen = QPen(QColor(theme.MUTED), width)
    p.setPen(pen)
    p.setBrush(QColor(theme.PANEL_2))
    p.drawPath(ring)
    text = QColor(theme.TEXT)
    if glyph == "i":
        _fill(p, _dot(8, 4.9, 0.95), text)
        _stroke_path(p, _lines([(8, 7.3), (8, 11.6)]), text, u)
    else:
        q = QPainterPath()
        q.moveTo(5.9, 6.1)
        q.cubicTo(5.9, 4.8, 6.9, 4.0, 8.05, 4.0)
        q.cubicTo(9.25, 4.0, 10.15, 4.8, 10.15, 5.9)
        q.cubicTo(10.15, 7.3, 8.05, 7.6, 8.05, 9.2)
        _stroke_path(p, q, text, u)
        _fill(p, _dot(8.05, 11.7, 0.95), text)


def _draw_dlg_warning(p, c, u):
    tri = _lines([(8, 1.2), (15.2, 14.2), (0.8, 14.2), (8, 1.2)])
    tri.closeSubpath()
    p.setPen(QPen(QColor(theme.WARN), 1.0 / u * 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QColor(theme.WARN))
    p.drawPath(tri)
    ink = QColor(theme.INK)
    _stroke_path(p, _lines([(8, 5.8), (8, 9.6)]), ink, u)
    _fill(p, _dot(8, 11.9, 1.0), ink)


def _draw_dlg_critical(p, c, u):
    _fill(p, _dot(8, 8, 7.2), QColor(theme.DANGER))
    _stroke_path(p, _lines([(5.4, 5.4), (10.6, 10.6)], [(10.6, 5.4), (5.4, 10.6)]), QColor(theme.INK), u)


DRAW = {
    "download": _draw_download,
    "arrow-down": _draw_arrow_down,
    "check": _draw_check,
    "box": _draw_box,
    "box-checked": _draw_box_checked,
    "radio": _draw_radio,
    "radio-on": _draw_radio_on,
    "x": _draw_x,
    "warn": _draw_warn,
    "star": _draw_star,
    "people": _draw_people,
    "link": _draw_link,
    "copy": _draw_copy,
    "dialog-question": _draw_dlg_question,
    "dialog-info": _draw_dlg_info,
    "dialog-warning": _draw_dlg_warning,
    "dialog-critical": _draw_dlg_critical,
}


def device_side(logical: float, dpr: float) -> int:
    """An icon's side in device px (never below 1)."""
    return max(1, round(logical * dpr))


def draw(painter: QPainter, name: str, box: QRectF, color: str) -> None:
    """Draw icon `name` into `box` (painter units = device px for crispness)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = min(box.width(), box.height())
    unit = side / GRID
    painter.translate(box.x() + (box.width() - side) / 2, box.y() + (box.height() - side) / 2)
    painter.scale(unit, unit)
    DRAW[name](painter, QColor(color), unit)
    painter.restore()


@functools.lru_cache(maxsize=512)
def _pixmap(name: str, color: str, width: int, height: int, dpr: float) -> QPixmap:
    pm = QPixmap(max(1, round(width * dpr)), max(1, round(height * dpr)))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    draw(painter, name, QRectF(0, 0, pm.width(), pm.height()), color)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def pixmap(name: str, color: str, size: int, dpr: float) -> QPixmap:
    """A cached `size` x `size` logical px pixmap of icon `name` at `dpr`."""
    return _pixmap(name, color, size, size, round(dpr, 3))


class _Engine(QIconEngine):
    """Draws the icon at whatever size and scale Qt asks for (cached)."""

    def __init__(self, name: str, color: str, disabled: str, on: tuple[str, str] | None = None) -> None:
        super().__init__()
        self._name, self._color, self._disabled = name, color, disabled
        self._on = on  # (name, color) drawn for QIcon.State.On (a checked button), or None

    def _look(self, mode, state) -> tuple[str, str]:
        name, color = self._on if self._on is not None and state == QIcon.State.On else (self._name, self._color)
        return name, (self._disabled if mode == QIcon.Mode.Disabled else color)

    def paint(self, painter, rect, mode, state) -> None:
        scale = painter.device().devicePixelRatioF() if painter.device() else 1.0
        painter.drawPixmap(rect, _pixmap(*self._look(mode, state), rect.width(), rect.height(), round(scale, 3)))

    def pixmap(self, size, mode, state):
        return QPixmap(_pixmap(*self._look(mode, state), size.width(), size.height(), 1.0))

    def scaledPixmap(self, size, mode, state, scale):
        return QPixmap(_pixmap(*self._look(mode, state), size.width(), size.height(), round(scale, 3)))

    def actualSize(self, size, mode, state):
        return QSize(size)

    def clone(self):
        return _Engine(self._name, self._color, self._disabled, self._on)

    def key(self) -> str:
        return "volt-drawn"

    def isNull(self) -> bool:
        return False


@functools.lru_cache(maxsize=128)
def icon(name: str, color: str = theme.TEXT, disabled: str = theme.MUTED) -> QIcon:
    """A QIcon of drawn icon `name`: `color` normally, `disabled` when the
    widget showing it is disabled (both theme.py tokens)."""
    return QIcon(_Engine(name, color, disabled))


@functools.lru_cache(maxsize=1)
def checkbox_icon() -> QIcon:
    """A check box for a checkable QPushButton (Browse Mods' Show deprecated /
    Show NSFW, 3.2): hollow --muted box when off, --accent box with an --ink
    check when on - Qt picks the state from the button's checked state, so
    the checked state no longer rests on the fill alone."""
    return QIcon(_Engine("box", theme.MUTED, theme.MUTED, on=("box-checked", theme.ACCENT)))


def app_dpr() -> float:
    """The device pixel ratio inline icons render at: the app's (the highest
    of its screens'), 1.0 before a QGuiApplication exists."""
    app = QGuiApplication.instance()
    return app.devicePixelRatio() if app is not None else 1.0


@functools.lru_cache(maxsize=128)
def _inline(name: str, color: str, size: int, dpr: float) -> str:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pm = QPixmap(_pixmap(name, color, size, size, dpr))
    pm.setDevicePixelRatio(1.0)
    pm.save(buffer, "PNG")
    data = base64.b64encode(bytes(QByteArray(buffer.data()))).decode("ascii")
    return (f'<img src="data:image/png;base64,{data}" width="{size}" height="{size}" '
            f'style="vertical-align: middle">')


def inline(name: str, color: str, size: int = 14) -> str:
    """Icon `name` as a rich-text <img> (a QLabel with RichText): `size`
    logical px, rendered at app_dpr() device px. HTML-safe as is."""
    return _inline(name, color, size, round(app_dpr(), 3))


# ---- the app style ----

_DIALOG_ICONS = {
    QStyle.StandardPixmap.SP_MessageBoxQuestion: "dialog-question",
    QStyle.StandardPixmap.SP_MessageBoxInformation: "dialog-info",
    QStyle.StandardPixmap.SP_MessageBoxWarning: "dialog-warning",
    QStyle.StandardPixmap.SP_MessageBoxCritical: "dialog-critical",
}


# The radio / check box indicators (step 3.4, §3b approved): (off, on) icons.
_INDICATORS = {
    QStyle.PrimitiveElement.PE_IndicatorRadioButton: ("radio", "radio-on"),
    QStyle.PrimitiveElement.PE_IndicatorCheckBox: ("box", "box-checked"),
}


def indicator_color(on: bool, enabled: bool, hovered: bool, pressed: bool) -> str:
    """An indicator's token colour: --muted off (5.7:1 on --panel-2, 6.4 on
    --panel) / --text hovered, --accent on (--accent-hover hovered), a
    pressed one previews --accent (--accent-pressed when on); disabled:
    --border-hi off, DISABLED_FILL on (disabled parts are exempt from 3:1)."""
    if not enabled:
        return theme.DISABLED_FILL if on else theme.BORDER_HI
    if pressed:
        return theme.ACCENT_PRESSED if on else theme.ACCENT
    if on:
        return theme.ACCENT_HOVER if hovered else theme.ACCENT
    return theme.TEXT if hovered else theme.MUTED


def _draw_indicator(painter: QPainter, name: str, color: str, rect) -> None:
    """Icon `name` centred in logical `rect`, drawn as a device-size pixmap on
    whole device px (the painter's own transform included), so its stroke is
    a crisp whole number of device px at 125% too."""
    painter.save()
    box = painter.deviceTransform().mapRect(QRectF(rect))
    scale, _fx, _fy, ox, oy = painters.device_space(painter)
    side = max(1, round(min(box.width(), box.height())))
    x = round(box.x() + (box.width() - side) / 2) - ox
    y = round(box.y() + (box.height() - side) / 2) - oy
    painter.drawPixmap(QPoint(x, y), _pixmap(name, color, side, side, 1.0))
    painter.restore()


# Long tooltips wrap (step 3.4): a plain-text tip with a line longer than
# this many average characters is laid out word-wrapped (QLabel's own wrap
# width heuristic, ~40-80 characters) instead of one screen-wide line.
TOOLTIP_WRAP_CHARS = 60


class _TipWrap(QObject):
    """Filter on Qt's tooltip label (the private QTipLabel class, reused for
    every tooltip): whenever it is shown / resized for a new text
    it only word-wraps rich text, so a plain line longer than
    TOOLTIP_WRAP_CHARS gets wrapped here and the label re-sized; kept on
    screen if the taller tip would reach past the bottom."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize) and isinstance(obj, QLabel) and not obj.wordWrap():
            metrics = obj.fontMetrics()
            limit = metrics.averageCharWidth() * TOOLTIP_WRAP_CHARS
            if max((metrics.horizontalAdvance(line) for line in obj.text().split("\n")), default=0) > limit:
                obj.setWordWrap(True)
                obj.resize(obj.sizeHint() + QSize(1, 0))
                screen = obj.screen()
                if screen is not None:
                    bottom = screen.availableGeometry().bottom()
                    if obj.geometry().bottom() > bottom:
                        obj.move(obj.x(), max(screen.availableGeometry().top(), bottom - obj.height()))
        return False


# The Windows 11 title bar (step 3.4, §3b approved): DwmSetWindowAttribute
# colours - the caption in --bg with --text, a --border window edge; popups
# (menus, combo lists, tooltips, the Edit Config Sections popup) get no DWM
# border. Windows 11 (build 22000+) only; anywhere else nothing is installed,
# and a refused call is ignored (the native look stays).
_DWMWA_BORDER_COLOR, _DWMWA_CAPTION_COLOR, _DWMWA_TEXT_COLOR = 34, 35, 36
_DWMWA_COLOR_NONE = 0xFFFFFFFE


def colorref(hex_color: str) -> int:
    """'#rrggbb' -> a Win32 COLORREF (0x00BBGGRR)."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return r | g << 8 | b << 16


def dwm_supported() -> bool:
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000


def dwm_attributes(popup: bool) -> tuple[tuple[int, int], ...]:
    if popup:
        return ((_DWMWA_BORDER_COLOR, _DWMWA_COLOR_NONE),)
    return ((_DWMWA_CAPTION_COLOR, colorref(theme.BG)), (_DWMWA_TEXT_COLOR, colorref(theme.TEXT)),
            (_DWMWA_BORDER_COLOR, colorref(theme.BORDER)))


class _DwmColors(QObject):
    """Filter on every top-level window: on each Show, once per native
    window, sets its DWM colours (dwm_attributes)."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Show:
            try:
                hwnd = int(obj.winId())
                if obj.property("voltDwm") != hwnd:
                    obj.setProperty("voltDwm", hwnd)
                    import ctypes
                    from ctypes import wintypes

                    popup = obj.windowType() in (Qt.WindowType.Popup, Qt.WindowType.ToolTip)
                    for attribute, value in dwm_attributes(popup):
                        data = wintypes.DWORD(value)
                        ctypes.windll.dwmapi.DwmSetWindowAttribute(
                            wintypes.HWND(hwnd), wintypes.DWORD(attribute), ctypes.byref(data), ctypes.sizeof(data))
            except Exception:  # noqa: BLE001 - a platform nicety: never let it break a window
                pass
        return False


_TIP_WRAP: _TipWrap | None = None
_DWM: _DwmColors | None = None


def _tip_wrap() -> _TipWrap:
    global _TIP_WRAP
    if _TIP_WRAP is None:
        _TIP_WRAP = _TipWrap()
    return _TIP_WRAP


def _dwm() -> _DwmColors:
    global _DWM
    if _DWM is None:
        _DWM = _DwmColors()
    return _DWM


class VoltStyle(QProxyStyle):
    """Fusion (theme.apply_theme's base style) with VOLT's own pieces:

    - standardIcon: QMessageBox's Question / Information / Warning /
      Critical icons are drawn ones (QMessageBox asks its style for them,
      through the stylesheet style, at PM_MessageBoxIconSize and the box's
      device pixel ratio) instead of the Windows-native bitmaps.
    - drawPrimitive: every QRadioButton / QCheckBox indicator is a drawn
      ring / box (indicator_color; Fusion's unchecked radio was 1.09:1 on
      --panel-2). A tristate check box's partial state stays Fusion's.
    - polish(widget): every QPushButton gets the keyboard focus ring
      (painters.FocusRing); every QLabel[role="modal-title"] the terminal
      font (letter-spacing + caps; theme.py sets family / size / color);
      Qt's tooltip label wraps long plain text (_TipWrap); every top-level
      window gets the Windows 11 DWM colours (_DwmColors; not installed
      elsewhere); a QInputDialog's prompt label word-wraps (QLabel's wrap hint is
      ~80 average chars, so a long prompt no longer stretches the dialog
      across the screen - the same wrapped-label shape as the app's own
      text dialogs), at one wrap width for every prompt (a minimum width).
      QStyleSheetStyle calls this base polish for every widget it polishes.
    """

    def styleHint(self, hint, option=None, widget=None, return_data=None):
        # The keyboard focus ring (painters._RingFrame, the app's only
        # QFocusFrame; Fusion makes none) goes above its button, in the window
        # (or the scroll area's viewport), not in the button's own parent:
        # a QMessageBox's button box is exactly button-high, so the ring's top
        # and bottom 2px were clipped away (0.5.12 hardware, Export as code
        # after Tab). Qt asks this once per QFocusFrame, with no widget.
        if hint == QStyle.StyleHint.SH_FocusFrame_AboveWidget:
            return 1
        return super().styleHint(hint, option, widget, return_data)

    def standardIcon(self, standard_icon, option=None, widget=None):
        name = _DIALOG_ICONS.get(standard_icon)
        if name is not None:
            return icon(name)
        return super().standardIcon(standard_icon, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        names = _INDICATORS.get(element)
        state = option.state
        if names is None or state & QStyle.StateFlag.State_NoChange:
            return super().drawPrimitive(element, option, painter, widget)
        on = bool(state & QStyle.StateFlag.State_On)
        color = indicator_color(on, bool(state & QStyle.StateFlag.State_Enabled),
                                bool(state & QStyle.StateFlag.State_MouseOver), bool(state & QStyle.StateFlag.State_Sunken))
        _draw_indicator(painter, names[on], color, option.rect)
        return None

    def polish(self, target):
        super().polish(target)
        if isinstance(target, QWidget) and target.isWindow():  # polish also gets the QApplication / QPalette
            if target.inherits("QTipLabel"):  # Qt's tooltip label (its objectName is set only after polish)
                target.installEventFilter(_tip_wrap())
            if dwm_supported():
                target.installEventFilter(_dwm())
        if isinstance(target, QPushButton):
            target.installEventFilter(painters.focus_ring())
        elif isinstance(target, QLabel) and target.property("role") == "modal-title":
            if not painters.is_terminal_font(target.font(), painters.TERMINAL_MODAL_PX, painters.TERMINAL_MODAL_SPACING):
                target.setFont(painters.terminal_font(painters.TERMINAL_MODAL_PX, painters.TERMINAL_MODAL_SPACING))
        if isinstance(target, QLabel) and isinstance(target.parent(), QInputDialog):
            target.setWordWrap(True)
            # Every prompt at the same wrap width (80 average chars), or its own
            # one-line width if shorter: QLabel's wrap hint halves its trial
            # width for a prompt of a few lines (Add mod came out ~250px
            # against its ~500px siblings). The text is set before the show
            # that polishes it (QInputDialog.getText: setLabelText, exec).
            metrics = target.fontMetrics()
            longest = max((metrics.horizontalAdvance(line) for line in target.text().split("\n")), default=0)
            target.setMinimumWidth(min(longest, metrics.averageCharWidth() * 80))
