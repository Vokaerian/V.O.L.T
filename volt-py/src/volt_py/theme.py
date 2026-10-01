"""VOLT palette + app-wide Qt stylesheet.

Port of the Electron renderer's `src/renderer/src/styles.css` (`:root` tokens
and the global button/input rules). Applied once, app-wide, from `main()` -
the same way styles.css applies globally today. Screen-specific pieces
(panel framing, path links, the storefront tag...) are selected by dynamic
properties / object names that the screens set on their widgets.

Visual language: design direction B "Circuit" (memory/DESIGN.md), phase 1 =
these tokens + the base QSS; phase 2 = the shared painters (painters.py: dot
grid, panel shadows, terminal labels, the copper rail, the keyboard focus
ring) and the drawn icons + app style (icons.py, installed by apply_theme);
phase 3 = per screen (3.1 main manage, 3.2/3.3 Browse Mods, 3.4 the rest: game
select, dialogs, status bar, tooltips, title bar); motion follows in phase 4.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def _alpha(hex_color: str, alpha: float) -> str:
    """'#rrggbb' -> 'rgba(r, g, b, a)': a translucent wash that Qt blends over
    whatever the widget sits on (QSS has no `opacity`)."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _mix(color_a: str, weight_a: float, color_b: str) -> str:
    """CSS `color-mix(in srgb, A weight_a*100%, B)` for opaque '#rrggbb' colors:
    per-channel A*w + B*(1-w), rounded half-up, as '#rrggbb'. QSS has no
    color-mix(), so styles.css's mixed colors are computed here."""
    a = [int(color_a[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i : i + 2], 16) for i in (1, 3, 5)]
    mixed = (int(x * weight_a + y * (1 - weight_a) + 0.5) for x, y in zip(a, b))
    return "#" + "".join(f"{c:02x}" for c in mixed)


# ---- tokens: design direction B "Circuit" (memory/DESIGN.md; signed off by
# the user 2026-09-29; the fidelity artifact's circuit theme). Each value is
# defined once here; QSS below and the screens' painters read these names. ----

# Surface / elevation scale, lowest to highest: WELL < BG < PANEL < PANEL_2 < RAISED.
WELL = "#111214"  # recessed, below the window (phase 2-3: wells / insets)
BG = "#141517"  # window, inputs
PANEL = "#1c1d20"  # panels, lists, dialogs
PANEL_2 = "#25272b"  # cards: buttons, row cards, rails
RAISED = "#2d3035"  # above a card (phase 2-3: lifted / hovered cards)
BORDER = "#373a40"
BORDER_HI = "#4c5058"  # a hovered edge (rows, inputs); the scrollbar handle
TEXT = "#e9e6e0"
MUTED = "#a39f97"
# Blue is the one interactive color (links, focus, selection, primary action).
ACCENT = "#4f9ff0"
ACCENT_HOVER = "#72b3f4"
INK = "#07111f"  # text / icons on a bright ACCENT fill (primary buttons)
DANGER = "#ff7a6e"
WARN = "#e0b341"
OK = "#5cc47f"  # success (installed, found); also RDEP below
# Copper: structural / decorative only (the load-order rail, terminal labels),
# never an interactive affordance and never a status. Phase 2-3 painters.
SIGNAL = "#dc9660"
RADIUS = 6  # px, shared corner radius: buttons/inputs/panels/rows

# The blue de-dup (steps 3.2 + 3.3, DESIGN.md §18-19): one blue. The
# dependency tint is the main --accent (was its own #4a90d9) at 18% (was
# 22%: with the brighter blue, 22% put --danger 4.59 / --muted 4.42 below AA
# on RimWorld dependency rows; 18% = --text 10.2, --danger 5.0, --muted 4.8).
# Dependency / dependent tints (.row.dependency / .row.dependent): the mod-list
# rows' dependency highlighting (screens/mod_list.py), the Rules window's
# Example chips and Browse Mods' "Will be installed" pill.
DEP = ACCENT
DEP_BG = _alpha(DEP, 0.18)
# The Official (Core/DLC) row badge: a neutral chip - --panel fill (sunk into
# the --panel-2 row card), a --border-hi edge - holding a neutral --text
# drawn check (the user's final call, DESIGN.md §22, = the fidelity artifact's
# neutral badge; blue stays interactive-only). --text, not --muted (user,
# 0.5.12 amendment): at 125% the 10px check is a 1-device-px anti-aliased
# stroke, and in --muted it peaked at ~2.9:1 on hardware; --text on the
# --panel fill is 13.5:1 designed (~5:1 effective). The fill is opaque, so the
# glyph's contrast is the same on a plain, hovered, selected or tinted row.
# OFFICIAL is the check's colour (was --muted, --accent, before that #6cb4ee),
# OFFICIAL_EDGE / OFFICIAL_FILL the chip's; screens/mod_list.py's
# paint_row_badge paints all three (step 3.5, v0.5.11).
OFFICIAL = TEXT
OFFICIAL_EDGE = BORDER_HI
OFFICIAL_FILL = PANEL
RDEP = OK
RDEP_BG = _alpha(RDEP, 0.2)
MONO_FONTS = ("Cascadia Mono", "Consolas", "DejaVu Sans Mono")
_MONO_CSS = ", ".join(f'"{f}"' for f in MONO_FONTS)  # --mono, as a QSS font-family list

# styles.css body font: 13px 'Segoe UI', system-ui.
FONT_FAMILY = "Segoe UI"
FONT_SIZE_PX = 13


# --selected (step 3.1, DESIGN.md §15 decision 1, v0.5.9): ACCENT 25% into
# WELL = #21354b, "a card pressed into the board" - every selection app-wide
# (row cards, menus, text selection, rail entries, the drag pill). The old
# 35%-into-PANEL_2 fill (#345170) failed AA for every selected-row foreground
# but --text; on this one --text 10.1, --muted 4.75, --warn 6.4, --danger
# 4.9, --ok 5.8 and the --accent edge 4.5:1. It is about as dark as a hovered
# card, so a selected row is carried by its hue + the --accent edge.
SELECTED = _mix(ACCENT, 0.25, WELL)
# A hovered menu / combo drop-down item (DESIGN.md §17-19): the pre-3.1
# selection fill #345170 (ACCENT 35% into PANEL_2), as the new --selected is
# only 1.19:1 against the popups' --panel-2 and the pointer's item got lost.
# --text on it 6.6:1.
MENU_SELECTED = _mix(ACCENT, 0.35, PANEL_2)
# The details pane's recessed description well (step 3.1): the darker top /
# left edges of a surface sunk below --panel, and its 7px inner shade.
WELL_EDGE_TOP = "#08090a"
WELL_EDGE_LEFT = "#0c0d0f"
WELL_SHADE = _alpha("#000000", 0.4)
# The BepInEx manager's Vanilla launch button (THUNDERSTORE.md §3): a neutral
# gray one small step lighter than the default button (Save = PANEL_2 /
# BORDER), user-directed 2026-09-28 - the same 10% step toward TEXT for both.
VANILLA_BG = _mix(TEXT, 0.10, PANEL_2)
VANILLA_BORDER = _mix(TEXT, 0.10, BORDER)
# .row:hover: color-mix(in srgb, var(--text) 7%, var(--panel-2)) - every hover
# wash on a --panel-2 surface (rows, rail entries, cards, pressed chips).
HOVER = _mix(TEXT, 0.07, PANEL_2)
# A pressed primary button: ACCENT sunk 15% toward BG (INK on it 5.2:1).
ACCENT_PRESSED = _mix(ACCENT, 0.85, BG)
# Disabled states: opaque colors (not 50% alpha) so every disabled label keeps
# WCAG AA 4.5:1 on the surfaces it sits on (design phase 1, 2026-09-29).
DISABLED_FILL = _mix(ACCENT, 0.25, PANEL_2)  # a disabled primary's fill / a disabled outline's edge
DISABLED_FILL_TEXT = _mix(TEXT, 0.5, MUTED)  # its label, 5.6:1 on DISABLED_FILL
DISABLED_ACCENT = _mix(ACCENT, 0.4, MUTED)  # a disabled accent-outline / link label, >=4.5:1 on PANEL_2 and HOVER
DISABLED_WARN = _mix(WARN, 0.6, MUTED)  # a disabled warn-outline label


# Settings' underline tabs (step 3.4): the gap between the tab row's rule and
# the --panel-2 page under it (each tab's bottom margin; the rule past the
# last tab is painted at the same height, screens/settings_window.py).
SETTINGS_TABS_GAP = 10

# The Browse Mods cards' title size (screens/bepinex_browse_window.py): one
# step above FONT_SIZE_PX, tuned on real hardware 2026-09-29.
BROWSE_NAME_PX = 14

# ---- motion (phase 4, memory/DESIGN.md §27-28) ----
# Durations in ms: the only moving parts. Hover / press stay instant (QSS),
# no button hover animates, nothing pulses. Every animation consults
# animations_enabled() when it starts and jumps to its end state when that
# is False (painters.crossfade / TabIndicator / set_raised, the game-select
# tile, the download bar fill, Edit Config's section jump).
MOTION_FAST = 120  # a tab page's content crossfade; the Valheim toggle slide (coder, 0.5.15)
MOTION = 150  # a Browse card's lift (shadow blend), Browse results <-> detail, the game-select tile lift
MOTION_SLIDE = 180  # the tab underline sliding to the clicked tab (OutCubic)
MOTION_SCREEN = 200  # game select -> the game's screen

# The Settings > General "Animations" choice (settings.json "animations",
# settings.ANIMATIONS; stored per game - VOLT has no app-wide settings file -
# and applied by each game screen when it opens: set_animation_mode).
# "windows" (default) follows Windows' own "Animation effects" switch
# (Settings > Accessibility > Visual effects), re-read at every animation
# start, so flipping it applies without a restart; "on" / "off" override it.
SPI_GETCLIENTAREAANIMATION = 0x1042
_animation_mode = "windows"


def set_animation_mode(mode) -> None:
    """The app-wide animation mode: "on" / "off", anything else = "windows"."""
    global _animation_mode
    _animation_mode = mode if mode in ("on", "off") else "windows"


def windows_animations() -> bool:
    """Windows' "Animation effects" (SystemParametersInfoW
    SPI_GETCLIENTAREAANIMATION, a microsecond call). True off Windows and on
    any failure: a broken probe never turns motion off by itself."""
    import sys

    if sys.platform != "win32":
        return True
    try:
        import ctypes

        value = ctypes.c_int(1)  # BOOL
        if not ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0):
            return True
        return bool(value.value)
    except Exception:
        return True


def animations_enabled() -> bool:
    """Should an animation starting now run (True) or jump to its end (False)?"""
    mode = _animation_mode
    return mode == "on" or (mode == "windows" and windows_animations())

# Mod-list row-card ::item margin (left, top, right, bottom): the card sits this
# far inside its row rect. Also for sizing the drag pill.
ROW_MARGINS = (2, 1, 6, 1)
# The same with the copper load-order rail (painters.install_rail): the left
# margin becomes the rail's gutter (the line and its nodes live in it).
RAIL_GUTTER = 22


def row_margins(view) -> tuple[int, int, int, int]:
    """ROW_MARGINS for `view`'s row cards: the left one is RAIL_GUTTER on a
    list with the rail (rail="true"), as the ::item rules have it. Qt-free
    (the stdlib harnesses' fake views: a missing / None property = no rail)."""
    left, top, right, bottom = ROW_MARGINS
    rail = view is not None and getattr(view, "property", None) is not None and view.property("rail") is True
    return (RAIL_GUTTER if rail else left, top, right, bottom)


STYLESHEET = f"""
QWidget {{
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE_PX}px;
}}
QMainWindow {{
    background: {BG};
}}

QLabel[muted="true"] {{
    color: {MUTED};
}}
/* The header's "V. O. L. T. vX" (both main screens): the Circuit wordmark,
   copper mono 600 (after [muted] so it wins; 7.2:1 on --bg). */
QLabel[role="wordmark"] {{
    color: {SIGNAL};
    font-family: {_MONO_CSS};
    font-weight: 600;
}}

/* ---- buttons ---- */
QPushButton {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 3px 12px;
    outline: 0;  /* no style focus rect around the label: painters.FocusRing is the one Tab indicator */
}}
QPushButton:enabled:hover {{
    border-color: {MUTED};
}}
/* Press: the card sinks to --panel (Circuit). Deliberately the same
   specificity as a [variant] rule and declared before them, so a variant
   that sets its own background (link, entries, tabs, chips...) keeps it
   while pressed; the variants that want a press look say so below. */
QPushButton:pressed {{
    background: {PANEL};
}}
/* Disabled: the fill drops out, the label goes --muted (5.7:1 on --panel-2,
   6.4:1 on --panel) - no 50% alpha, which failed AA. */
QPushButton:disabled {{
    background: transparent;
    border-color: {BORDER};
    color: {MUTED};
}}
/* Primary: dark ink on the bright accent (6.8:1; white on it was 2.8:1). */
QPushButton[variant="primary"] {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: {INK};
}}
QPushButton[variant="primary"]:enabled:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton[variant="primary"]:enabled:pressed {{
    background: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}
QPushButton[variant="primary"]:disabled {{
    background: {DISABLED_FILL};
    border-color: {DISABLED_FILL};
    color: {DISABLED_FILL_TEXT};
}}
/* The BepInEx manager's Vanilla launch button: the default button, one step
   lighter (VANILLA_BG / VANILLA_BORDER); same hover / disabled scheme. */
QPushButton[variant="vanilla"] {{
    background: {VANILLA_BG};
    border-color: {VANILLA_BORDER};
    color: {TEXT};
}}
QPushButton[variant="vanilla"]:enabled:hover {{
    border-color: {MUTED};
}}
QPushButton[variant="vanilla"]:enabled:pressed {{
    background: {PANEL};
}}
QPushButton[variant="vanilla"]:disabled {{
    background: transparent;
    border-color: {VANILLA_BORDER};
    color: {MUTED};
}}
QPushButton[variant="accent-outline"] {{
    border-color: {ACCENT};
    color: {ACCENT};
}}
/* disabled (a browse card's Installing... / Installed): a dim blue edge and
   label, 5.4:1 on the card, 4.5:1 on the hovered card */
QPushButton[variant="accent-outline"]:disabled {{
    border-color: {DISABLED_FILL};
    color: {DISABLED_ACCENT};
}}
/* Save while there are unsaved changes (button.warn-outline). */
QPushButton[variant="warn-outline"] {{
    background: {_alpha(WARN, 0.14)};
    border-color: {WARN};
    color: {WARN};
}}
QPushButton[variant="warn-outline"]:enabled:pressed {{
    background: {PANEL};
}}
QPushButton[variant="warn-outline"]:disabled {{
    background: transparent;
    border-color: {_mix(WARN, 0.35, PANEL_2)};
    color: {DISABLED_WARN};
}}
/* Game/Mods/Config: plain accent-text links (button.path-link). */
QPushButton[variant="link"] {{
    background: transparent;
    border: 0;
    padding: 0;
    color: {ACCENT};
}}
QPushButton[variant="link"]:enabled:hover {{
    color: {ACCENT_HOVER};
    text-decoration: underline;
}}
QPushButton[variant="link"]:enabled:pressed {{
    color: {ACCENT_PRESSED};
}}
QPushButton[variant="link"]:disabled {{
    background: transparent;
    color: {DISABLED_ACCENT};
}}

/* ---- inputs ---- */
QLineEdit, QComboBox, QPlainTextEdit {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 3px 6px;
}}
/* Classic list popup: always drops straight down, instead of Fusion's
   menu-style popup that aligns the selected row over the combo. */
QComboBox {{
    combobox-popup: 0;
}}
/* Blend the arrow sub-control into the rounded frame (no native seam). */
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border: none;
    background: transparent;
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {MUTED};
}}
/* Hover / focus edges (SCOPE.md section 2's feedback bar); focus after hover
   so a focused, hovered field keeps the accent. Frameless inner edits
   (#configSearchEdit, #browsePackageName: border 0) are unaffected. */
QLineEdit:enabled:hover, QComboBox:enabled:hover, QPlainTextEdit:enabled:hover {{
    border-color: {BORDER_HI};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}
/* Text selection matches the row selection (--selected + --text, 10.1:1). */
QLineEdit, QPlainTextEdit, QTextBrowser {{
    selection-background-color: {SELECTED};
    selection-color: {TEXT};
}}
/* The combo drop-down list (a QListView): the card surface, selection as rows. */
QComboBox QAbstractItemView {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    selection-background-color: {MENU_SELECTED};
    selection-color: {TEXT};
    outline: 0;
}}
/* its items: 6px side padding, so a popup row's text starts where the closed
   combo's does (its 1px border + 6px padding) instead of touching the popup
   edge (step 3.4 review: 1px in on hardware); the hover / current row keeps
   MENU_SELECTED (a styled ::item draws its own background). */
QComboBox QAbstractItemView::item {{
    padding: 2px 6px;
}}
QComboBox QAbstractItemView::item:selected {{
    background: {MENU_SELECTED};
    color: {TEXT};
}}

/* ---- scrollbars: thin, rounded, no arrow buttons (Circuit) - a 10px track
   with a 6px handle (2px margin); transparent, over the scrolled surface ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
    border: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
    border: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_HI};
    min-height: 24px;
    margin: 2px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_HI};
    min-width: 24px;
    margin: 2px;
    border-radius: 3px;
}}
QScrollBar::handle:hover {{
    background: {MUTED};
}}
QScrollBar::handle:pressed {{
    background: {ACCENT};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
    border: 0;
    background: none;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
}}
QAbstractScrollArea::corner {{
    background: transparent;
    border: 0;
}}

/* ---- popups: menus, tooltips, and every dialog's base surface ---- */
QMenu {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMenu::item {{
    background: transparent;
    padding: 4px 16px;
    border-radius: {RADIUS - 2}px;
}}
QMenu::item:selected {{
    background: {MENU_SELECTED};
    color: {TEXT};
}}
QMenu::item:disabled {{
    color: {MUTED};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}
/* Tooltips (step 3.4): padded, a --border-hi edge (--text on --panel-2
   12.0:1). Long plain-text tips wrap (icons.VoltStyle: ~60 characters). */
QToolTip {{
    background: {PANEL_2};
    color: {TEXT};
    border: 1px solid {BORDER_HI};
    padding: 5px 8px;
}}
/* Every QDialog (incl. QMessageBox / QInputDialog / QColorDialog) on --panel;
   the named dialogs below repeat it for their own selectors. */
QDialog {{
    background: {PANEL};
}}
/* A message box's default button (the one Enter presses) in the primary
   look (step 3.4, the user's call: the artifact's msgPrimary on). QSS's
   :default follows the button's live state - as in any dialog, the
   default moves to the push button that has keyboard focus. Every state
   restated with :default so the plain button's :hover / :pressed rules
   (more specific otherwise) don't win. --ink on --accent 6.8:1. */
QMessageBox QPushButton:default {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: {INK};
}}
QMessageBox QPushButton:default:enabled:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QMessageBox QPushButton:default:enabled:pressed {{
    background: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}
QMessageBox QPushButton:default:disabled {{
    background: {DISABLED_FILL};
    border-color: {DISABLED_FILL};
    color: {DISABLED_FILL_TEXT};
}}

/* ---- panel framing (.details / .actions-column / .list-scroll) ---- */
/* The mod lists are screens/mod_list.py's ModListView (modList="true"): scoped
   by property, since a bare QListView rule would also hit every QComboBox
   drop-down list (QComboBox's popup view is a QListView too). */
QFrame[panel="true"] {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QListView[modList="true"] {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
/* No focus rectangle around the current row (square; clashes with the cards). */
QListView[modList="true"] {{
    outline: 0;
}}
/* List rows as cards (.row): --panel-2 + radius each. ModList.jsx rows are
   22px tall in 24px slots (ROW_GAP 2) - vertical padding sizes the card,
   the 1px top/bottom margin leaves the 2px gap between neighbors. The
   6px right margin keeps the rounded right edge clear of the vertical
   scrollbar (flush, the corner read as clipped); 2px on the left. */
QListView[modList="true"]::item {{
    background: {PANEL_2};
    border: 1px solid transparent;
    border-radius: {RADIUS}px;
    margin: {ROW_MARGINS[1]}px {ROW_MARGINS[2]}px {ROW_MARGINS[3]}px {ROW_MARGINS[0]}px;
    padding: 1px 7px;
}}
/* A list with the copper rail (painters.install_rail sets rail="true"; the
   Valheim Active list only): the card starts past the rail's gutter. */
QListView[modList="true"][rail="true"]::item {{
    margin: {ROW_MARGINS[1]}px {ROW_MARGINS[2]}px {ROW_MARGINS[3]}px {RAIL_GUTTER}px;
}}
/* Circuit's row edge: a transparent 1px border (the padding above is 1px
   less than styles.css's 2px 8px, so the card's size and the text's place
   are exactly as before - RimWorld's 22px rows stay 22px) that lights
   --border-hi on hover and --accent when selected (selection isn't carried
   by the fill alone). .row:hover: the 7% --text wash (HOVER). */
QListView[modList="true"]::item:hover {{
    background: {HOVER};
    border-color: {BORDER_HI};
}}
/* .row.selected (after :hover so it wins, as in styles.css). No `color`
   here: it would override the palette's HighlightedText, which
   ModRowDelegate.initStyleOption sets per row (--text, or --danger for an
   outdated mod's name, which stays red when selected). */
QListView[modList="true"]::item:selected {{
    background: {SELECTED};
    border-color: {ACCENT};
}}
/* .row.dependency / .row.dependent: ModRowDelegate flags those rows with the
   Alternate feature (these lists never alternate row colors) and paints the
   tint itself, under a transparent card. Last, so it wins over :hover (as
   .row.dependency does in styles.css) and :selected. */
QListView[modList="true"]::item:alternate {{
    background: transparent;
}}

/* ---- main-screen pieces ---- */
/* Storefront pill (.tag). */
QLabel[role="tag"] {{
    background: {PANEL_2};
    color: {MUTED};
    font-size: 11px;
    padding: 1px 6px;
    border-radius: 8px;
}}
/* .loadorder-bar: thin rule under the whole header. */
QFrame#loadOrderBar {{
    border: 0;
    border-bottom: 1px solid {BORDER};
}}
/* "Unsaved changes" beside the undo button (.dirty). */
QLabel[role="dirty"] {{
    color: {WARN};
}}
/* ... and the download row's pause / resume button (.dl-btn: the same 24x24 square). */
QPushButton#undoButton, QPushButton#downloadToggle {{
    padding: 0;
}}
/* A pane title as a Circuit terminal label (painters.TerminalLabel paints
   it: copper spaced caps - the spacing/caps are on its font, QSS has
   neither - the " [count]" in --text, and with [rule] a copper hairline
   under it, in the 5px below the text). Copper on --bg 7.2:1. */
QLabel[role="pane-title"] {{
    font-family: {_MONO_CSS};
    font-size: 11px;
    font-weight: 600;
    color: {SIGNAL};
}}
QLabel[role="pane-title"][rule="true"] {{
    padding-bottom: 5px;
}}
/* An action-column group label (step 3.1: LOAD ORDER / GET MODS / LAUNCH):
   the same terminal label, 10px, with a copper side rule after the text
   (painters.TerminalLabel(rule="side")). Copper on --panel 6.9:1. */
QLabel[role="pane-title"][rule="side"] {{
    font-size: 10px;
}}
/* ---- the details pane as a readout (step 3.1, both games) ----
   Keys: copper terminal caps (the caps / spacing are on the label's font,
   painters.terminal_font; copper on --panel 6.9:1). In the Valheim pane
   (readout="true") each key / value pair is one row between 1px --border
   rules: the key's right padding is the column gap, so a rule runs
   unbroken under both cells (the grid has no spacing). */
QLabel[role="details-key"] {{
    font-family: {_MONO_CSS};
    font-size: 11px;
    font-weight: 600;
    color: {SIGNAL};
}}
QLabel[role="details-key"][readout="true"] {{
    border: 0;  /* a lone border-bottom isn't drawn on a QLabel (0.5.9 hardware): reset all sides first, as browse-fact */
    border-bottom: 1px solid {BORDER};
    padding: 5px 10px 5px 2px;
}}
QLabel[role="details-value"] {{
    border: 0;
    border-bottom: 1px solid {BORDER};
    padding: 5px 2px 5px 0;
}}
QLabel[role="details-key"][first="true"], QLabel[role="details-value"][first="true"] {{
    border-top: 1px solid {BORDER};
}}
/* The description's recessed well: --well (--text on it 15.1:1), darker
   top / left edges, a 7px inner shade along the top (its own strip, so the
   gradient's 0..1 stops are exactly 7px) and 10px 12px of text padding. */
QFrame#detailsWell, QFrame#browseWell, QFrame#browseFilterStrip, QFrame#browsePager {{
    background: {WELL};
    border: 1px solid {BORDER};
    border-top-color: {WELL_EDGE_TOP};
    border-left-color: {WELL_EDGE_LEFT};
    border-radius: {RADIUS}px;
}}
QWidget#detailsWellShade, QWidget#browseWellShade {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {WELL_SHADE}, stop: 1 rgba(0, 0, 0, 0));
    border-top-left-radius: {RADIUS - 1}px;
    border-top-right-radius: {RADIUS - 1}px;
}}
QLabel#detailsWellText {{
    padding: 10px 12px;
}}
QPushButton[variant="issue-count"] {{
    padding: 3px 6px;
}}
/* "N scan issues" (.issue-count.scan). */
QPushButton[variant="issue-count"][scan="true"] {{
    color: {WARN};
}}
/* Self-closing success notice (Run / Push), laid over the main screen. */
QFrame#notice {{
    background: {PANEL_2};
    border: 1px solid {ACCENT};
    border-radius: {RADIUS}px;
}}
QLabel[role="notice-title"] {{
    font-weight: 600;
}}

/* ---- footer: .action-divider + footer.statusbar, with the SteamCMD download row
   (screens/download_bar.py; DownloadBar.jsx) ---- */
QFrame#actionDivider {{
    border: 0;
    border-top: 1px solid {BORDER};
}}
/* .statusbar font-size: 12px (the status text and the row's "Downloading..." label) */
QFrame#statusBar QLabel {{
    font-size: 12px;
}}
/* the copper ">" prompt before the status text (step 3.4; the filter
   strip's prompt): copper on --bg 7.2:1 */
QLabel[role="status-prompt"] {{
    font-family: {_MONO_CSS};
    font-weight: 600;
    color: {SIGNAL};
    padding-right: 8px;
}}
/* .statusbar.error / .statusbar.warn .status-text (App.jsx say(text, kind)) */
QLabel[role="status-text"][kind="error"] {{
    color: {DANGER};
}}
QLabel[role="status-text"][kind="warn"] {{
    color: {WARN};
}}
/* .mono.dl-num: the done / total counter and the speed */
QLabel[role="dl-num"] {{
    font-family: {_MONO_CSS};
    font-size: 12px;
    color: {MUTED};
}}

/* ---- Thunderstore/BepInEx manager (screens/bepinex_main_screen.py; the signed-off
   Valheim mockup): the muted 12px path line under the paths bar. The rows'
   own look (two lines, toggle, update button) is painted by
   screens/bepinex_mod_list.py, not styled here. ---- */
QLabel[role="path-line"] {{
    color: {MUTED};
    font-size: 12px;
}}

/* ---- Scan issues window (screens/scan_issues_window.py; .modal.validation-window.scan-issues) ---- */
QDialog#scanIssues {{
    background: {PANEL};
}}
/* Every modal title: a Circuit terminal label - copper mono 13px 600;
   letter-spacing + caps are set on the font by icons.VoltStyle.polish.
   Copper on --panel 6.9:1. */
QLabel[role="modal-title"] {{
    font-family: {_MONO_CSS};
    font-size: 13px;
    font-weight: 600;
    color: {SIGNAL};
}}
/* .validation-rail */
QScrollArea#scanRail {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
/* .validation-entry.scan: flat, full-width, a 3px --muted bar on the left
   (CSS draws it as an inset box-shadow; a border here, so the entry's own
   layout margins make up the rest of the 8px left padding). */
QPushButton[variant="scan-entry"] {{
    background: transparent;
    border: 0;
    border-left: 3px solid {MUTED};
    border-radius: 0;
    padding: 0;
    text-align: left;
}}
QPushButton[variant="scan-entry"][selected="true"] {{
    background: {SELECTED};
}}
/* .validation-target, and its --text color on the selected entry. */
QLabel[role="scan-target"] {{
    color: {MUTED};
    padding-left: 16px;
}}
QLabel[role="scan-target"][selected="true"] {{
    color: {TEXT};
}}
/* .validation-detail */
QScrollArea#scanDetail {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QLabel[role="scan-heading"] {{
    font-weight: bold;
}}
/* .modal p.mono */
QLabel[role="scan-mono"] {{
    color: {MUTED};
    font-family: {_MONO_CSS};
    font-size: 12px;
}}
/* .modal p.error */
QLabel[role="scan-error"] {{
    color: {DANGER};
}}

/* ---- Warnings and errors window (screens/validation_window.py; .modal.validation-window) ---- */
QDialog#validation {{
    background: {PANEL};
}}
/* .validation-rail */
QScrollArea#validationRail {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
/* .validation-mod: the mod's header over its entries */
QLabel[role="validation-mod"] {{
    font-weight: 600;
    padding: 2px 8px;
}}
/* .validation-entry.warning / .error: flat, full-width, a 3px bar on the
   left (CSS's inset box-shadow, a border here: 3 + 17 = CSS's 20px left
   padding) over a 12% --warn / 14% --danger wash; --selected when selected.
   The hover wash (a little stronger) isn't in styles.css - SCOPE.md §2's
   hover-feedback rule for ported pieces. */
QPushButton[variant="validation-entry"] {{
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 2px 8px 2px 17px;
    text-align: left;
}}
QPushButton[variant="validation-entry"][severity="warning"] {{
    border-left: 3px solid {WARN};
    background: {_alpha(WARN, 0.12)};
}}
QPushButton[variant="validation-entry"][severity="error"] {{
    border-left: 3px solid {DANGER};
    background: {_alpha(DANGER, 0.14)};
}}
/* Not in the real Electron CSS: a deliberate port deviation, kept by user decision 2026-09-27 - revisit only if a byte-exact port is ever wanted. */
QPushButton[variant="validation-entry"][severity="warning"]:hover {{
    background: {_alpha(WARN, 0.2)};
}}
QPushButton[variant="validation-entry"][severity="error"]:hover {{
    background: {_alpha(DANGER, 0.22)};
}}
QPushButton[variant="validation-entry"][selected="true"],
QPushButton[variant="validation-entry"][selected="true"]:hover {{
    background: {SELECTED};
}}
/* .validation-detail (.warning / .error: a 3px left border) */
QScrollArea#validationDetail {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QScrollArea#validationDetail[severity="warning"] {{
    border-left: 3px solid {WARN};
}}
QScrollArea#validationDetail[severity="error"] {{
    border-left: 3px solid {DANGER};
}}

/* ---- Help window (screens/help_window.py): the Scan issues window's frame,
   the Rules window's rail entries (hover tint, --selected when selected) ---- */
QDialog#help {{
    background: {PANEL};
}}
QScrollArea#helpRail {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QScrollArea#helpDetail {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QPushButton[variant="help-entry"] {{
    background: transparent;
    border: 0;
    border-radius: 6px;
    padding: 6px 10px;
    text-align: left;
    color: {MUTED};
}}
QPushButton[variant="help-entry"]:hover {{
    background: {HOVER};
    color: {TEXT};
}}
QPushButton[variant="help-entry"][selected="true"] {{
    background: {SELECTED};
    color: {TEXT};
}}
QLabel[role="help-heading"] {{
    font-size: 16px;
    font-weight: bold;
}}
QLabel[role="help-short"] {{
    font-size: 14px;
    font-weight: 600;
}}
QLabel[role="help-long"] {{
    color: {MUTED};
}}

/* ---- Edit Config window (screens/bepinex_config_window.py; the signed-off
   mockup https://claude.ai/artifact/5WdEyKKwmrHpzvct1cqziY): the Help
   window's frame and rail entries, the detail pane's form text roles ---- */
QDialog#editConfig {{
    background: {PANEL};
}}
QFrame#configRail {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QFrame#configDetail {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QScrollArea#configRailList, QScrollArea#configForm {{
    background: transparent;
    border: 0;
}}
QFrame#configDivider {{
    border: 0;
    border-top: 1px solid {BORDER};
}}
/* the rail's file rows (.vc-row-btn): the Help window's entry look */
QPushButton[variant="config-entry"] {{
    background: transparent;
    border: 0;
    border-radius: 6px;
    padding: 6px 10px;
    text-align: left;
    color: {MUTED};
}}
QPushButton[variant="config-entry"]:hover {{
    background: {HOVER};
    color: {TEXT};
}}
QPushButton[variant="config-entry"][selected="true"] {{
    background: {SELECTED};
    color: {TEXT};
}}
/* the file's path in the toolbar: mono 14px 600 */
QLabel[role="config-path"] {{
    font-family: {_MONO_CSS};
    font-size: 14px;
    font-weight: 600;
}}
/* [Section] heading: 600, a rule under it */
QLabel[role="config-section"] {{
    font-weight: 600;
    padding-bottom: 4px;
    border: 0;  /* without it the lone border-bottom is never drawn (seen 0.5.7-0.5.9) */
    border-bottom: 1px solid {BORDER};
}}
QLabel[role="config-key"] {{
    font-weight: 600;
}}
QLabel[role="config-desc"], QLabel[role="config-empty"] {{
    color: {MUTED};
}}
/* "Setting type: X · Default value: Y" / Acceptable values: mono 11px muted */
QLabel[role="config-meta"] {{
    color: {MUTED};
    font-family: {_MONO_CSS};
    font-size: 11px;
}}
/* the raw-text fallback's banner: --warn text on a 14% --warn wash (also the
   deprecated-package banner: Browse Mods' detail page, the manager's details) */
QLabel[role="config-banner"] {{
    background: {_alpha(WARN, 0.14)};
    border-radius: {RADIUS}px;
    padding: 8px 12px;
    color: {WARN};
}}
/* the raw text box: mono 12px */
QPlainTextEdit[mono="true"] {{
    font-family: {_MONO_CSS};
    font-size: 12px;
}}
/* "Show more" links under a long list / long text: 12px */
QPushButton[variant="link"][small="true"] {{
    font-size: 12px;
}}
/* the Color swatch (its background is set per widget from the value) */
QPushButton[variant="config-swatch"] {{
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 0;
}}
/* ---- the pinned section-jump + search toolbar (THUNDERSTORE.md §7's QoL
   pass, the same signed-off design's ConfigJump artboard) ---- */
/* a section chip (.vc-chip): the plain button, hover = accent border +
   accent-hover text, elided at 130px; dimmed (45%) in Filter mode when
   its section has no matches */
QPushButton[variant="config-chip"]:enabled:hover {{
    border-color: {ACCENT};
    color: {ACCENT_HOVER};
}}
QPushButton[variant="config-chip"]:enabled:pressed,
QPushButton[variant="config-sections"]:enabled:pressed,
QPushButton[variant="config-filter"]:enabled:pressed {{
    background: {HOVER};
}}
QPushButton[variant="config-chip"][dim="true"] {{
    background: {_alpha(PANEL_2, 0.45)};
    border-color: {_alpha(BORDER, 0.45)};
    color: {_alpha(TEXT, 0.45)};
}}
/* "Sections (N) v": accent border while its popup is open */
QPushButton[variant="config-sections"][open="true"] {{
    border-color: {ACCENT};
}}
/* the Filter toggle: --selected + accent border + --text when on (10.1:1) */
QPushButton[variant="config-filter"]:checked {{
    background: {SELECTED};
    border-color: {ACCENT};
    color: {TEXT};
}}
QPushButton[variant="config-filter"]:checked:hover {{
    background: {_mix(ACCENT, 0.45, PANEL_2)};
}}
/* the search field: an input-look frame holding a bare line edit, the
   counter and the mini buttons (.vc-input / .vc-bare / .vc-mini) */
QFrame#configSearchBox {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QFrame#configSearchBox[fieldFocus="true"] {{
    border-color: {ACCENT};
}}
QLineEdit#configSearchEdit {{
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 2px 0;
}}
QLabel[role="config-counter"] {{
    color: {MUTED};
    font-size: 12px;
}}
QPushButton[variant="config-mini"] {{
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 0 5px;
    color: {MUTED};
    font-size: 14px;
}}
QPushButton[variant="config-mini"]:enabled:hover {{
    color: {TEXT};
}}
QPushButton[variant="config-mini"]:enabled:pressed {{
    color: {ACCENT};
}}
/* the Sections popup: --panel-2, bordered, rounded (the drop shadow is a
   QGraphicsDropShadowEffect); its rows reuse the config-entry look */
QFrame#configSectionsPopup {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QScrollArea#configSectionsList {{
    background: transparent;
    border: 0;
}}
QPushButton[variant="config-entry"][popup="true"]:pressed {{
    background: {SELECTED};
}}
QPushButton[variant="config-entry"][dim="true"] {{
    color: {_alpha(MUTED, 0.45)};
}}
/* an entry row as a card: transparent until the search marks it - a
   match gets the 8% --warn wash + 30% --warn border, the current match
   12% + a solid --warn border. (Non-matches are dimmed by a 50% --panel
   wash the row paints over itself, since QSS has no opacity.) */
QFrame[variant="config-row"] {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS}px;
}}
QFrame[variant="config-row"][hit="match"] {{
    background: {_alpha(WARN, 0.08)};
    border-color: {_alpha(WARN, 0.3)};
}}
QFrame[variant="config-row"][hit="current"] {{
    background: {_alpha(WARN, 0.12)};
    border-color: {WARN};
}}

/* ---- Browse Mods window (screens/bepinex_browse_window.py; the signed-off
   BrowseMods / PackageDetail artboards of the same Valheim design) ---- */
QDialog#browseMods {{
    background: {PANEL};
}}
/* .close-btn: the plain button, 30x30, no padding */
QPushButton#browseClose {{
    padding: 0;
}}
QScrollArea#browseGrid {{
    background: transparent;
    border: 0;
}}
/* .card: --panel-2, rounded; the hover tint is SCOPE.md §2's feedback rule
   (not in the mockup), the same 7% --text wash the list rows use */
QFrame[role="browse-card"] {{
    background: {PANEL_2};
    border: 1px solid transparent;
    border-radius: {RADIUS}px;
}}
/* Raised hover (steps 3.2/3.3, §3b approved): the hover wash and the
   --border-hi edge (instant, like a button's hover), and a deeper cached
   shadow (painters.set_raised blends it in / out over MOTION on enter /
   leave - the phase-4 card lift). */
QFrame[role="browse-card"]:hover {{
    background: {HOVER};
    border-color: {BORDER_HI};
}}
/* an installed mod's card (3.2 tweak "Installed card edge", 0.5.10): the
   Installed button's 45% --ok edge on the card too, kept while hovered (after
   the :hover rule, same specificity - the mockup's .inst-edge .card.inst) */
QFrame[role="browse-card"][installed="true"] {{
    border-color: {_alpha(OK, 0.45)};
}}
/* .card-icon / .pkg-icon placeholder: --panel, rounded (the loaded icon is
   pre-rounded to the same radius) */
QLabel[role="browse-icon"] {{
    background: {PANEL};
    border-radius: {RADIUS}px;
}}
/* a result card's icon on a recessed mat (3.2): --well, a 1px --border edge,
   3px of mat around the 40px icon (rounded 3px inside it) */
QLabel[role="browse-icon"][mat="true"] {{
    background: {WELL};
    border: 1px solid {BORDER};
    border-radius: {RADIUS - 1}px;
    padding: 3px;
}}
/* the card's footer (3.2): a hairline rule across the card's full width
   above the downloads / Install row (border reset first: a lone border-top
   on a QFrame / QLabel is not reliably drawn, 0.5.9) */
QFrame[role="browse-card-foot"] {{
    background: transparent;
    border: 0;
    border-top: 1px solid {BORDER};
}}
/* its downloads count: mono 11px --muted (5.7:1 on --panel-2, 4.7:1 hovered) */
QLabel[role="browse-dl"] {{
    color: {MUTED};
    font-family: {_MONO_CSS};
    font-size: 11px;
}}
/* .card-name: 600; a step above the body's 13px (BROWSE_NAME_PX) - the
   mockup's 13px read too small on a large monitor (user, 2026-09-29) */
QLabel[role="browse-name"] {{
    font-size: {BROWSE_NAME_PX}px;
    font-weight: 600;
}}
/* "by author", "⬇ downloads": muted 11px; .card-desc the same */
QLabel[role="browse-small"], QLabel[role="browse-desc"] {{
    color: {MUTED};
    font-size: 11px;
}}
/* the detail header's stats line (3.3): mono 12px --muted (5.7:1) */
QLabel[role="browse-stats"] {{
    color: {MUTED};
    font-family: {_MONO_CSS};
    font-size: 12px;
}}
/* .pkg-name: 22px h2 */
QLabel[role="browse-title"] {{
    font-size: 22px;
    font-weight: bold;
}}
/* .pagination's Prev / Next: link-blue text (blue = interactive), no frame */
QPushButton[variant="browse-page"] {{
    background: transparent;
    border: 0;
    padding: 0 4px;
    color: {ACCENT};
}}
QPushButton[variant="browse-page"]:enabled:hover {{
    color: {ACCENT_HOVER};
}}
QPushButton[variant="browse-page"]:enabled:pressed {{
    color: {ACCENT_PRESSED};
}}
/* disabled at --muted (6.4:1): the enabled state is the blue one, so the
   two stay apart without dropping below AA (was 50% --muted, 2.6:1) */
QPushButton[variant="browse-page"]:disabled {{
    background: transparent;
    border: 0;
    color: {MUTED};
}}
/* the page counter (3.2): "PAGE  1 / 764" in a small well (QFrame#browsePager
   above) - a copper terminal key (7.7:1 on --well) and the mono numbers in
   --text (15.1:1) */
QLabel[role="pager-key"] {{
    font-family: {_MONO_CSS};
    font-size: 10px;
    font-weight: 600;
    color: {SIGNAL};
}}
QLabel[role="pager-num"] {{
    font-family: {_MONO_CSS};
    font-size: 12px;
    color: {TEXT};
}}
/* The search + Category + Sort row as one recessed strip (3.2): the well
   (QFrame#browseFilterStrip above) takes the fields' own frames; it shows
   the hover (--border-hi) and focus (--accent) edges for all three (the
   window sets [focus] while one of them has focus). Copper ">" prompt. */
QFrame#browseFilterStrip:hover {{
    border-color: {BORDER_HI};
}}
QFrame#browseFilterStrip[fieldFocus="true"] {{
    border-color: {ACCENT};
}}
QLabel[role="strip-prompt"] {{
    font-family: {_MONO_CSS};
    font-weight: 600;
    color: {SIGNAL};
    padding: 0 2px 0 8px;
}}
QLineEdit[strip="true"], QComboBox[strip="true"] {{
    background: transparent;
    border: 0;
    border-radius: {RADIUS - 2}px;
}}
/* a strip combo's own hover: the --panel step up out of the well (--text on it 13.6:1) */
QComboBox[strip="true"]:enabled:hover {{
    background: {PANEL};
}}
QFrame[role="strip-divider"] {{
    background: {BORDER};
    border: 0;
}}
/* the detail page's big Install: button.primary, padding 10px, 15px */
QPushButton[variant="primary"][big="true"] {{
    padding: 10px;
    font-size: 15px;
}}
/* .pkg-description's border-top, and the README box inside it */
QFrame#browseDivider {{
    border: 0;
    border-top: 1px solid {BORDER};
}}
QTextBrowser#browseReadme {{
    background: transparent;
    border: 0;
    padding: 8px 10px;  /* + the document's 4px margin = the well's 12px 14px (3.3) */
}}
/* the dependency block (3.3): a REQUIRES terminal label (painters.
   TerminalLabel side rule) over a muted 12px sub-line */
QLabel[role="browse-dep-sub"] {{
    color: {MUTED};
    font-size: 12px;
}}
/* the dependency rows: a dependency that gets pulled in is --accent (the
   mockup); one that couldn't be resolved is --warn */
QLabel[role="browse-dep-missing"] {{
    color: {ACCENT};
}}
QLabel[role="browse-dep-problem"] {{
    color: {WARN};
}}
/* ---- the detail page, reworked as a Thunderstore-style page (signed off
   2026-09-29: the PackageDetail artboard): cards on the modal, a tab
   strip, the right column's facts / copy box / chips, the Required rows'
   status pills, the Versions rows ---- */
/* the header card, the tab body, the facts and categories cards: --panel-2, rounded */
QFrame[role="browse-panel"] {{
    background: {PANEL_2};
    border: 0;
    border-radius: {RADIUS}px;
}}
QScrollArea#browseTabScroll {{
    background: transparent;
    border: 0;
}}
/* the tab strip (3.3): a static underline on a 1px strip rule. Each tab's
   own bottom edge IS the rule under it (1px --border, so the rule runs on
   unbroken - the tabs sit 0px apart), the selected tab's 2px --accent
   covers it (+ --text label), a hovered one's 2px --border-hi; the rest of
   the rule is QFrame#browseTabRule after the tabs. All sides reset first
   (a lone single-side border isn't drawn, 0.5.9). The slide is phase 4. */
QPushButton[variant="browse-tab"] {{
    background: transparent;
    border: 0;
    border-bottom: 1px solid {BORDER};
    border-radius: 0;
    padding: 5px 15px 7px 15px;
    color: {MUTED};
}}
QPushButton[variant="browse-tab"]:enabled:hover {{
    border: 0;
    border-bottom: 2px solid {BORDER_HI};
    padding-bottom: 6px;
    color: {TEXT};
}}
QPushButton[variant="browse-tab"]:enabled:pressed {{
    background: transparent;
    color: {ACCENT_HOVER};
}}
/* selected: the 2px underline's room is kept (no layout shift) but left
   transparent - the --accent underline itself is painters.TabIndicator's,
   which slides it between tabs (phase 4 M2) */
QPushButton[variant="browse-tab"][selected="true"],
QPushButton[variant="browse-tab"][selected="true"]:enabled:hover {{
    border: 0;
    border-bottom: 2px solid transparent;
    padding-bottom: 6px;
    color: {TEXT};
}}
QFrame#browseTabRule {{
    background: transparent;
    border: 0;
    border-bottom: 1px solid {BORDER};
}}
/* the package-name copy box: an input frame holding a bare read-only
   line edit (mono 12px) and the copy button on its right edge */
QFrame#browseCopyBox {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QLineEdit#browsePackageName {{
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 4px 8px;
    font-family: {_MONO_CSS};
    font-size: 12px;
}}
QPushButton#browseCopy {{
    border: 0;
    border-left: 1px solid {BORDER};
    border-radius: 0;
    border-top-right-radius: {RADIUS}px;
    border-bottom-right-radius: {RADIUS}px;
    padding: 4px 10px;
}}
/* the facts rows: a rule under each but the last; values 600 */
QFrame[role="browse-fact"] {{
    border: 0;
    border-bottom: 1px solid {BORDER};
}}
QFrame[role="browse-fact"][last="true"] {{
    border-bottom: 0;
}}
/* the facts as a terminal table (3.3): keys are details-key labels (copper
   terminal caps, 6.1:1 on --panel-2), values mono 12px --text (13.0:1) */
QLabel[role="browse-fact-value"] {{
    font-family: {_MONO_CSS};
    font-size: 12px;
}}
/* the PACKAGE label heading the facts: the side-rule terminal label at the
   pane-title size (11px) */
QLabel[role="pane-title"][rule="side"][size="pane"] {{
    font-size: 11px;
}}
/* (the same 11px side-rule label is every dialog heading since step 3.4:
   painters.TerminalLabel(rule="heading") - the Rules form, the Warnings
   windows' issue headings; copper on --panel 6.9:1, on --panel-2 6.1:1) */
/* a category chip: the storefront tag's look, clickable (accent on hover) */
QPushButton[variant="browse-chip"] {{
    background: {PANEL};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 2px 8px;
    color: {MUTED};
    font-size: 11px;
}}
QPushButton[variant="browse-chip"]:enabled:hover {{
    border-color: {ACCENT};
    color: {ACCENT_HOVER};
}}
/* a Required row: a --panel card inside the --panel-2 body */
QFrame[role="browse-row"] {{
    background: {PANEL};
    border: 0;
    border-radius: {RADIUS}px;
}}
/* clickable (0.6.0: opens that dependency's page) - SCOPE.md §2's hover wash */
QFrame[role="browse-row"]:hover {{
    background: {HOVER};
}}
/* its status pill: green = already installed (the Rules window's ok
   tint), accent = will be installed (the dependency tint; --accent-hover
   text, as --accent on that tint is 4.4:1), warn = a dependency that
   couldn't be resolved */
QLabel[role="browse-pill"] {{
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 8px;
}}
QLabel[role="browse-pill"][state="ok"] {{
    background: {RDEP_BG};
    color: {RDEP};
}}
QLabel[role="browse-pill"][state="get"] {{
    background: {DEP_BG};
    color: {ACCENT_HOVER};
}}
QLabel[role="browse-pill"][state="warn"] {{
    background: {_alpha(WARN, 0.14)};
    color: {WARN};
}}
/* a deprecated card's "Deprecated" pill: the same pill in --danger */
QLabel[role="browse-pill"][state="danger"] {{
    background: {_alpha(DANGER, 0.14)};
    color: {DANGER};
}}
/* a Versions row: a rule under each, the rows' hover wash; the header row plain */
QFrame[role="browse-vrow"] {{
    border: 0;
    border-bottom: 1px solid {BORDER};
    border-radius: 0;
}}
QFrame[role="browse-vrow"]:hover {{
    background: {HOVER};
}}
QFrame[role="browse-vrow"][head="true"]:hover {{
    background: transparent;
}}

/* ---- Rules window (screens/rules_window.py; the approved Design mockup) ---- */
QDialog#rules {{
    background: {PANEL};
}}
/* .validation-rail (padding/gap are the inner layout's margins/spacing) */
QScrollArea#rulesRail {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QScrollArea#rulesRight {{
    background: transparent;
}}
/* .validation-entry: flat, rounded, hover tint, --selected when selected */
QPushButton[variant="rules-entry"] {{
    background: transparent;
    border: 0;
    border-radius: 6px;
    padding: 0;
    text-align: left;
}}
QPushButton[variant="rules-entry"]:hover {{
    background: {HOVER};
}}
QPushButton[variant="rules-entry"][selected="true"] {{
    background: {SELECTED};
}}
/* .validation-target: the muted "Rule N" line, --text on the selected entry */
QLabel[role="rules-target"] {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel[role="rules-target"][selected="true"] {{
    color: {TEXT};
}}
/* .mono inputs / row text */
QLineEdit[mono="true"], QLabel[role="rules-row-text"] {{
    font-family: {_MONO_CSS};
    font-size: 12px;
}}
/* .rules-check: found / not-found circle */
QLabel[role="rules-check"] {{
    border-radius: 10px;
    font-size: 12px;
    font-weight: bold;
}}
QLabel[role="rules-check"][state="ok"] {{
    background: {RDEP_BG};
    color: {RDEP};
}}
QLabel[role="rules-check"][state="err"] {{
    background: {_alpha(DANGER, 0.14)};
    color: {DANGER};
}}
/* .rules-field-box */
QFrame[role="rules-box"] {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
/* .rules-field-row; .error: the warn outline + danger text */
QFrame[role="rules-row"] {{
    background: {PANEL_2};
    border: 1px solid transparent;
    border-radius: 6px;
}}
QFrame[role="rules-row"][error="true"] {{
    border-color: {WARN};
}}
QLabel[role="rules-row-text"][error="true"] {{
    color: {DANGER};
}}
/* the row's x (remove) */
QPushButton[variant="rules-remove"] {{
    background: transparent;
    border: 0;
    border-radius: 10px;
    padding: 0;
    color: {MUTED};
    font-size: 14px;
}}
QPushButton[variant="rules-remove"]:hover {{
    background: {HOVER};
    color: {TEXT};
}}
/* .rules-field-hint */
QLabel[role="rules-hint"] {{
    color: {DANGER};
    font-size: 12px;
    padding: 2px 4px;
}}
/* .rules-example */
QFrame[role="rules-example"] {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
/* the tier captions: mono 11px, muted */
QLabel[role="rules-caption"] {{
    color: {MUTED};
    font-family: {_MONO_CSS};
    font-size: 11px;
}}
/* .rules-chip: After = dependency tint + left bar, Before = dependent tint +
   right bar (CSS inset box-shadows, drawn as borders here), this mod =
   --selected with an accent outline. Every chip has a 1px (transparent)
   border so the outlined one isn't taller than the rest. */
QLabel[role="rules-chip"] {{
    padding: 6px 14px;
    border: 1px solid transparent;
    border-radius: {RADIUS}px;
}}
QLabel[role="rules-chip"][tier="after"] {{
    background: {DEP_BG};
    border-left: 3px solid {DEP};
}}
QLabel[role="rules-chip"][tier="before"] {{
    background: {RDEP_BG};
    border-right: 3px solid {RDEP};
}}
QLabel[role="rules-chip"][tier="self"] {{
    background: {SELECTED};
    border: 1px solid {ACCENT};
    font-weight: 600;
}}

/* ---- Game-selection screen (screens/game_select.py; GameSelect.jsx / .game-select) ----
   The tile's own frame (background, border, hover ring/shadow/lift) is painted
   by GameTile so it can animate; these rules style the pieces inside it. */
/* .game-select-subtitle (the brand header's tagline) / .game-select-caption
   (letter-spacing: set on the font) */
QLabel[role="game-select-subtitle"], QLabel[role="game-select-caption"] {{
    color: {MUTED};
    font-size: 12px;
    font-weight: 600;
}}
/* .game-tile-cover: --panel behind the image, 1px rule under it; top corners
   follow the card's inner radius (the image itself is pre-rounded). */
QLabel[role="game-tile-cover"] {{
    background: {PANEL};
    border: 0;
    border-bottom: 1px solid {BORDER};
    border-top-left-radius: {RADIUS - 1}px;
    border-top-right-radius: {RADIUS - 1}px;
}}
/* .game-tile-label; muted on a disabled ("soon") tile */
QLabel[role="game-tile-label"] {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 600;
    padding: 0 16px;
}}
QLabel[role="game-tile-label"][soon="true"] {{
    color: {MUTED};
}}
/* .game-tile-scrim: --bg at 64%, over the cover only (step 3.4), so the
   Coming-soon name below it is --muted on --panel-2 (5.7:1; was 1.83:1
   under the scrim) */
QFrame[role="game-tile-scrim"] {{
    background: {_alpha(BG, 0.64)};
    border: 0;
    border-top-left-radius: {RADIUS - 1}px;
    border-top-right-radius: {RADIUS - 1}px;
}}
/* the COMING SOON badge (step 3.4): mono terminal caps (caps + spacing on
   its font) in a tiny --well, darker top edge; --muted on --well 6.9:1 */
QLabel[role="game-tile-badge"] {{
    background: {WELL};
    border: 1px solid {BORDER};
    border-top-color: {WELL_EDGE_TOP};
    border-radius: 2px;
    color: {MUTED};
    font-family: {_MONO_CSS};
    font-size: 10px;
    font-weight: 600;
    padding: 5px 10px;
}}

/* ---- Settings window (screens/settings_window.py; .modal.settings-window) ---- */
QDialog#settings {{
    background: {PANEL};
}}
/* .settings-panel: the QTabWidget's pane (--panel-2, border, radius; its
   12px padding is each page's layout margins). */
QTabWidget#settingsTabs::pane {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}
QTabWidget#settingsTabs::tab-bar {{
    left: 0px;
}}
/* the tabs (step 3.4): the Browse Mods detail's underline tabs (3.3). Each
   tab's own 1px --border bottom edge is the rule under it (all sides reset
   first: a lone single-side border isn't drawn); the rest of the rule, past
   the last tab, is painted by settings_window.underline_tabs at the same
   height. Selected: a 2px --accent underline (painters.TabIndicator) + --text; hovered: 2px
   --border-hi + --text; at rest --muted (5.7:1 on --panel). The bottom
   margin is the gap to the page. */
QTabWidget#settingsTabs QTabBar::tab {{
    background: transparent;
    border: 0;
    border-bottom: 1px solid {BORDER};
    border-radius: 0;
    padding: 5px 15px 7px 15px;
    margin: 0px 0px {SETTINGS_TABS_GAP}px 0px;
    color: {MUTED};
}}
QTabWidget#settingsTabs QTabBar::tab:hover {{
    border: 0;
    border-bottom: 2px solid {BORDER_HI};
    padding-bottom: 6px;
    color: {TEXT};
}}
/* selected (after :hover so it wins): the underline's room kept, left
   transparent - painters.TabIndicator paints and slides the --accent
   underline (phase 4 M2) */
QTabWidget#settingsTabs QTabBar::tab:selected {{
    border: 0;
    border-bottom: 2px solid transparent;
    padding-bottom: 6px;
    color: {TEXT};
}}
/* .path-value: one-line mono field; .unset ("Not found") in --danger */
QLabel[role="path-value"] {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 2px 6px;
    font-family: {_MONO_CSS};
    font-size: 12px;
}}
QLabel[role="path-value"][unset="true"] {{
    color: {DANGER};
}}
/* The profile code (Export... > Share as code; step 3.4): read-only, in the
   3.1 recessed well - --well, darker top / left edges, the inner shade as a
   gradient over the field's top quarter - mono 12px (--text 15.1:1). */
QLineEdit#profileCode {{
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 {_mix("#000000", 0.4, WELL)}, stop: 0.25 {WELL}, stop: 1 {WELL});
    border: 1px solid {BORDER};
    border-top-color: {WELL_EDGE_TOP};
    border-left-color: {WELL_EDGE_LEFT};
    padding: 6px 10px;
    font-family: {_MONO_CSS};
    font-size: 12px;
}}
QLineEdit#profileCode:hover {{
    border-color: {BORDER_HI};
}}
QLineEdit#profileCode:focus {{
    border-color: {ACCENT};
}}

/* ---- Import from Steam Workshop dialog (screens/collection_dialog.py; .modal) - and the
   Thunderstore Import local mod dialog built on it (screens/bepinex_local_import_dialog.py) ---- */
QDialog#collectionImport, QDialog#localModImport {{
    background: {PANEL};
}}
/* .modal p.error */
QLabel[role="modal-error"] {{
    color: {DANGER};
}}
/* .modal p.collection-title (.collection-preview is the plain --text default) */
QLabel[role="collection-title"] {{
    font-weight: 600;
}}

/* ---- Offline mods dialog (screens/offline_mods_dialog.py, 0.6.16): the checklist as
   the scan rail's card (--panel-2, --border), rows hover --hover and
   select --selected; header cells in --muted. Pairs: --text on --panel-2 12.0,
   --hover 10.0, --selected 10.1; --muted (header, disabled rows) on --panel-2 5.7,
   --hover 4.7, --selected 4.75. ---- */
QDialog#offlineMods {{
    background: {PANEL};
}}
QTreeWidget#offlineModsList {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    outline: 0;
}}
QTreeWidget#offlineModsList::item {{
    padding: 2px 4px;
}}
QTreeWidget#offlineModsList::item:hover {{
    background: {HOVER};
}}
QTreeWidget#offlineModsList::item:selected {{
    background: {SELECTED};
    color: {TEXT};
}}
QTreeWidget#offlineModsList::item:disabled {{
    color: {MUTED};
}}
QTreeWidget#offlineModsList QHeaderView::section {{
    background: {PANEL_2};
    color: {MUTED};
    border: 0;
    border-bottom: 1px solid {BORDER};
    padding: 3px 6px;
}}

/* ---- Sync to Steam heads-up (RimWorldMainScreen._confirm_sync; .modal) ---- */
QDialog#syncConfirm {{
    background: {PANEL};
}}

/* ---- Installed / already installed (design phase 2, decision 5): a success
   state, not a washed-out disabled control - a 12% --ok wash, a 45% --ok
   edge, --ok text 600 and a drawn check (the screen sets the icon). Last, so
   it wins over every variant's :disabled rule (same specificity). --ok on
   the wash: 5.9:1 over --panel-2, 5.0:1 over the hovered card, 6.6:1 over
   --panel. ---- */
QPushButton[installed="true"]:disabled {{
    background: {_alpha(OK, 0.12)};
    border-color: {_alpha(OK, 0.45)};
    color: {OK};
    font-weight: 600;
}}
"""


def apply_theme(app: QApplication) -> None:
    # Fusion as the base style: Qt's style-sheet support is most predictable
    # on Fusion (the native Windows 11 style can ignore or fight parts of a
    # QSS). The dark color scheme is the port of styles.css's
    # `color-scheme: dark` - it darkens anything the QSS doesn't cover
    # (scrollbars, popups, the combo drop-down list).
    # VoltStyle (icons.py) is Fusion plus the drawn QMessageBox icons and the
    # app-wide polish hooks (keyboard focus ring, terminal modal titles).
    from volt_py.icons import VoltStyle

    app.setStyle(VoltStyle("Fusion"))
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    # The palette roles QSS can't set: Fusion's focus / check indicators and
    # link color (Highlight / Link - otherwise the Windows accent color),
    # placeholder text, tooltips. Surfaces stay with the QSS above.
    from PySide6.QtGui import QColor, QPalette

    palette = app.palette()
    for role, color in (
        (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, INK),
        (QPalette.ColorRole.Link, ACCENT),
        (QPalette.ColorRole.LinkVisited, ACCENT),
        (QPalette.ColorRole.PlaceholderText, MUTED),
        (QPalette.ColorRole.ToolTipBase, PANEL_2),
        (QPalette.ColorRole.ToolTipText, TEXT),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
