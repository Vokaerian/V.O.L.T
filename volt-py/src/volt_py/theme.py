"""VOLT palette + app-wide Qt stylesheet.

Port of the Electron renderer's `src/renderer/src/styles.css` (`:root` tokens
and the global button/input rules). Applied once, app-wide, from `main()` -
the same way styles.css applies globally today. Screen-specific pieces
(panel framing, path links, the storefront tag...) are selected by dynamic
properties / object names that the screens set on their widgets.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# ---- tokens (styles.css :root) ----
BG = "#1b1c1f"
PANEL = "#232428"
PANEL_2 = "#2b2d31"
BORDER = "#3a3c42"
TEXT = "#e3e5e8"
MUTED = "#9a9ea6"
ACCENT = "#4a9eed"
ACCENT_HOVER = "#6db4f2"
DANGER = "#e5484d"
WARN = "#e0b341"
OFFICIAL = "#6cb4ee"
RADIUS = 9  # px, shared corner radius: buttons/inputs/panels/rows

# Dependency / dependent tints (.row.dependency / .row.dependent): the mod-list
# rows' dependency highlighting (screens/mod_list.py) and the Rules window's
# Example chips.
DEP = "#4a90d9"
DEP_BG = "rgba(74, 144, 217, 0.22)"
RDEP = "#4caf6e"
RDEP_BG = "rgba(76, 175, 110, 0.2)"
MONO_FONTS = ("Cascadia Mono", "Consolas", "DejaVu Sans Mono")
_MONO_CSS = ", ".join(f'"{f}"' for f in MONO_FONTS)  # --mono, as a QSS font-family list

# styles.css body font: 13px 'Segoe UI', system-ui.
FONT_FAMILY = "Segoe UI"
FONT_SIZE_PX = 13


def _alpha(hex_color: str, alpha: float) -> str:
    """'#rrggbb' -> 'rgba(r, g, b, a)'. QSS has no `opacity` for widgets, so
    CSS's `button:disabled { opacity: 0.5 }` is emulated by half-alpha colors,
    which Qt blends over whatever the button sits on (as opacity would)."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _half(hex_color: str) -> str:
    return _alpha(hex_color, 0.5)


def _mix(color_a: str, weight_a: float, color_b: str) -> str:
    """CSS `color-mix(in srgb, A weight_a*100%, B)` for opaque '#rrggbb' colors:
    per-channel A*w + B*(1-w), rounded half-up, as '#rrggbb'. QSS has no
    color-mix(), so styles.css's mixed colors are computed here."""
    a = [int(color_a[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i : i + 2], 16) for i in (1, 3, 5)]
    mixed = (int(x * weight_a + y * (1 - weight_a) + 0.5) for x, y in zip(a, b))
    return "#" + "".join(f"{c:02x}" for c in mixed)


# --selected: color-mix(in srgb, var(--accent) 35%, var(--panel-2)).
SELECTED = _mix(ACCENT, 0.35, PANEL_2)
# The BepInEx manager's Vanilla launch button (THUNDERSTORE.md §3): a neutral
# gray one small step lighter than the default button (Save = PANEL_2 /
# BORDER), user-directed 2026-09-28 - the same 10% step toward TEXT for both.
VANILLA_BG = _mix(TEXT, 0.10, PANEL_2)
VANILLA_BORDER = _mix(TEXT, 0.10, BORDER)


# The Browse Mods cards' title size (screens/bepinex_browse_window.py): one
# step above FONT_SIZE_PX, tuned on real hardware 2026-09-29.
BROWSE_NAME_PX = 14

# Mod-list row-card ::item margin (left, top, right, bottom): the card sits this
# far inside its row rect. Also for sizing the drag pill.
ROW_MARGINS = (2, 1, 6, 1)


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

/* ---- buttons ---- */
QPushButton {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 3px 12px;
}}
QPushButton:enabled:hover {{
    border-color: {MUTED};
}}
QPushButton:disabled {{
    background: {_half(PANEL_2)};
    border-color: {_half(BORDER)};
    color: {_half(TEXT)};
}}
QPushButton[variant="primary"] {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
}}
QPushButton[variant="primary"]:enabled:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton[variant="primary"]:disabled {{
    background: {_half(ACCENT)};
    border-color: {_half(ACCENT)};
    color: {_alpha("#ffffff", 0.5)};
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
QPushButton[variant="vanilla"]:disabled {{
    background: {_half(VANILLA_BG)};
    border-color: {_half(VANILLA_BORDER)};
    color: {_half(TEXT)};
}}
QPushButton[variant="accent-outline"] {{
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton[variant="accent-outline"]:disabled {{
    border-color: {_half(ACCENT)};
    color: {_half(ACCENT)};
}}
/* Save while there are unsaved changes (button.warn-outline). */
QPushButton[variant="warn-outline"] {{
    background: {PANEL_2};
    border-color: {WARN};
    color: {WARN};
}}
QPushButton[variant="warn-outline"]:disabled {{
    background: {_half(PANEL_2)};
    border-color: {_half(WARN)};
    color: {_half(WARN)};
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
QPushButton[variant="link"]:disabled {{
    background: transparent;
    color: {_half(ACCENT)};
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
    border-radius: {RADIUS}px;
    margin: {ROW_MARGINS[1]}px {ROW_MARGINS[2]}px {ROW_MARGINS[3]}px {ROW_MARGINS[0]}px;
    padding: 2px 8px;
}}
/* .row:hover: color-mix(in srgb, var(--text) 7%, var(--panel-2)). */
QListView[modList="true"]::item:hover {{
    background: {_mix(TEXT, 0.07, PANEL_2)};
}}
/* .row.selected (after :hover so it wins, as in styles.css). No `color`
   here: it would override the palette's HighlightedText, which
   ModRowDelegate.initStyleOption sets per row (--text, or --danger for an
   outdated mod's name, which stays red when selected). */
QListView[modList="true"]::item:selected {{
    background: {SELECTED};
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
QLabel[role="pane-title"] {{
    font-weight: 600;
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
QLabel[role="modal-title"] {{
    font-size: 16px;
    font-weight: bold;
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
/* .validation-detail h3: 13px, bold */
QLabel[role="validation-heading"] {{
    font-weight: bold;
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
    background: {_mix(TEXT, 0.07, PANEL_2)};
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
    background: {_mix(TEXT, 0.07, PANEL_2)};
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
/* the raw-text fallback's banner: --warn text on a 14% --warn wash */
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
    background: {_mix(TEXT, 0.07, PANEL_2)};
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
/* the Filter toggle: --selected + accent border + white text when on */
QPushButton[variant="config-filter"]:checked {{
    background: {SELECTED};
    border-color: {ACCENT};
    color: #ffffff;
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
QFrame#configSearchBox[focus="true"] {{
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
QFrame[role="browse-card"]:hover {{
    background: {_mix(TEXT, 0.07, PANEL_2)};
}}
/* .card-icon / .pkg-icon placeholder: --panel, rounded (the loaded icon is
   pre-rounded to the same radius) */
QLabel[role="browse-icon"] {{
    background: {PANEL};
    border-radius: {RADIUS}px;
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
/* .pkg-name: 22px h2 */
QLabel[role="browse-title"] {{
    font-size: 22px;
    font-weight: bold;
}}
/* .pagination's Prev / Next: muted text, --text on hover, no frame */
QPushButton[variant="browse-page"] {{
    background: transparent;
    border: 0;
    padding: 0 4px;
    color: {MUTED};
}}
QPushButton[variant="browse-page"]:enabled:hover {{
    color: {TEXT};
}}
QPushButton[variant="browse-page"]:disabled {{
    background: transparent;
    border: 0;
    color: {_half(MUTED)};
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
/* the tab strip: the Settings tabs' look - plain text, accent border +
   text when selected, the muted border on hover */
QPushButton[variant="browse-tab"] {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS}px;
    padding: 4px 12px;
    color: {MUTED};
}}
QPushButton[variant="browse-tab"]:enabled:hover {{
    border-color: {MUTED};
    color: {TEXT};
}}
QPushButton[variant="browse-tab"][selected="true"],
QPushButton[variant="browse-tab"][selected="true"]:enabled:hover {{
    border-color: {ACCENT};
    color: {ACCENT};
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
QLabel[role="browse-fact-value"] {{
    font-weight: 600;
}}
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
/* its status pill: green = already installed (the Rules window's ok
   tint), accent = will be installed (the dependency tint), warn = a
   dependency that couldn't be resolved */
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
    color: {ACCENT};
}}
QLabel[role="browse-pill"][state="warn"] {{
    background: {_alpha(WARN, 0.14)};
    color: {WARN};
}}
/* a Versions row: a rule under each, the rows' hover wash; the header row plain */
QFrame[role="browse-vrow"] {{
    border: 0;
    border-bottom: 1px solid {BORDER};
    border-radius: 0;
}}
QFrame[role="browse-vrow"]:hover {{
    background: {_mix(TEXT, 0.07, PANEL_2)};
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
    background: {_mix(TEXT, 0.07, PANEL_2)};
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
/* field labels: font-weight 600 */
QLabel[role="rules-field-label"] {{
    font-weight: 600;
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
    background: {_alpha(DANGER, 0.18)};
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
    background: {_mix(TEXT, 0.07, PANEL_2)};
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
/* .game-select-header h1 */
QLabel[role="game-select-title"] {{
    font-size: 46px;
    font-weight: bold;
}}
/* .game-select-accent-bar */
QFrame[role="game-select-accent-bar"] {{
    background: {ACCENT};
    border: 0;
    border-radius: 2px;
}}
/* .game-select-subtitle / .game-select-caption (letter-spacing: set on the font) */
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
/* .game-tile-scrim: rgba(27, 28, 31, 0.64) = --bg at 64% */
QFrame[role="game-tile-scrim"] {{
    background: {_alpha(BG, 0.64)};
    border: 0;
    border-radius: {RADIUS - 1}px;
}}
/* .game-tile-badge (letter-spacing: set on the font) */
QLabel[role="game-tile-badge"] {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 2px;
    color: {MUTED};
    font-size: 10px;
    font-weight: bold;
    padding: 5px 11px;
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
/* button.settings-tab: the plain button look, 4px apart (.settings-tabs gap);
   the bottom margin is .modal's 10px gap between the tab row and the panel. */
QTabWidget#settingsTabs QTabBar::tab {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 3px 12px;
    margin: 0px 4px 10px 0px;
}}
QTabWidget#settingsTabs QTabBar::tab:hover {{
    border-color: {MUTED};
}}
/* button.settings-tab.selected (after :hover so it wins) */
QTabWidget#settingsTabs QTabBar::tab:selected {{
    border-color: {ACCENT};
    color: {ACCENT};
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

/* ---- Import from Steam Workshop dialog (screens/collection_dialog.py; .modal) ---- */
QDialog#collectionImport {{
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

/* ---- Sync to Steam heads-up (RimWorldMainScreen._confirm_sync; .modal) ---- */
QDialog#syncConfirm {{
    background: {PANEL};
}}
"""


def apply_theme(app: QApplication) -> None:
    # Fusion as the base style: Qt's style-sheet support is most predictable
    # on Fusion (the native Windows 11 style can ignore or fight parts of a
    # QSS). The dark color scheme is the port of styles.css's
    # `color-scheme: dark` - it darkens anything the QSS doesn't cover
    # (scrollbars, popups, the combo drop-down list).
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    app.setStyleSheet(STYLESHEET)
