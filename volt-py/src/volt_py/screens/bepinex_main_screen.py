"""The Thunderstore/BepInEx game manager screen (THUNDERSTORE.md §3), built
for Valheim (VALHEIM.md PLAN item 3, stage 3b) against the signed-off design
https://claude.ai/artifact/KeNe4nnwPVmCgfxrpbXBCZ - and game-agnostic: the
screen takes the game's own module (valheim.py's shape: NAME, SLUG, GAME,
autodetect, is_game_root, find_game_exe) plus that game's Help entries
(screens/bepinex_help_entries.help_entries(module)). main_window builds it
for every row of bepinex_games.GAMES, so the next BepInEx game (Lethal
Company, R.E.P.O.) is a module plus a registry row - no screen subclass.
Same shell as RimWorld's screen (screens/rimworld_main_screen.py, whose
small shared pieces - the notice, the status text, the eye icon, the button
helpers - are imported from it rather than copied); the data layer is
bepinex_load_orders.py (a load order IS a BepInEx tree; its manifest says
what's installed), thunderstore.py (metadata, downloads, the shared package
cache and the per-package metadata cache) and bepinex_install.py.

Top to bottom (the mockup):
  paths bar      Settings | Paths: Game / Load order / BepInEx | storefront tag | version ... Help
                 <game folder>  /  <the open load order's BepInEx folder>   (muted, 12px)
  load-order bar Load order [picker] New.. Copy.. [Unsaved changes ↺] ... [⚠ N updates · Update all]
  checklist      GET STARTED 1. .. 2. .. 3. .. 4. .. ... Hide   (0.6.23, until done / hidden)
  content row    [details | inactive | active] (1.2 : 1 : 1) + actions column (150px)
  footer         divider; [status text] ... [Downloading: <mod>  done / total  [pill]] (0.6.25, while a job downloads;
                 0.6.26: the same bar also in Browse Mods' footer + detail card, _extra_dl_bars;
                 a job's whole total is known up front: bepinex_load_orders.plan_downloads)

Deltas from RimWorld's screen (THUNDERSTORE.md §3), all here:
  - Active / Inactive are separate lists, drag-reorder within Active, but
    the order is cosmetic (BepInEx resolves load order itself): no Sort,
    no order validation. Dependency *presence* is still checked
    (_update_issues: an active, enabled mod whose declared dependency isn't
    installed = error, installed but inactive / toggled off = warning; the
    "⚠ N · ✕ M" button lists them, a row with an error gets a "✕").
  - No Sync, no Push: one Save (bepinex_load_orders.save_load_order)
    materializes the Active list + every toggle into the load order's real
    tree (enabled = plain file names, everything else .disabled).
  - Rows are two lines (screens/bepinex_mod_list.py) right of the mod's
    icon tile (0.6.26: the package's icon.png via mod_icons.py, loaded off
    the GUI thread on first paint; a plain tile meanwhile / without one): name, then version ·
    last-updated from the Thunderstore metadata cache; per-mod on/off
    toggle on every Active row but the framework's (an unsaved edit, like a
    move: history / dirty / undo cover it, Save materializes it); per-mod
    update button on any row (framework included) with an update available.
  - The framework package (game.GAME.framework_package, installed by
    create_load_order) is pinned first in Active: not draggable, not
    toggleable, not movable, not uninstallable; never passed to Save.
  - Update checking (THUNDERSTORE.md §3, TODO #3): a check pass
    (check_updates, off the GUI thread) runs on opening the manager, on
    switching to a load order with unchecked packages, after a mod is
    added / removed / updated and on Rescan. Only Rescan asks Thunderstore
    about every package; the others ask only for packages whose check
    failed or isn't from this session (after a change: from the last
    RECHECK_AFTER_S), which keeps a big load order clear of HTTP 429
    rate-limiting. The load-order bar's "Update
    all" button carries the live count (warn-outline while > 0; "Up to
    date" / "Checking for updates..." / "Update check failed · Retry"
    otherwise). What it learns per package (latest version, date_updated,
    deprecated) is kept in <APP-ROOT>/cache/package-meta.json, so rows show
    a last-updated date (and the "Deprecated" pill / the details panel's
    deprecated banner) before this run's check finishes; a package never
    checked shows neither. An Active row toggled off shows the "Disabled"
    pill (bepinex_mod_list.py).
  - Paths: Game (the install), Load order (load-orders/<slug>/) and BepInEx
    (its BepInEx/ subfolder); the latter two follow the picker and are
    disabled with no load order open.
  - "Browse Mods..." (stage 3f; screens/bepinex_browse_window.py) opens
    the in-app Thunderstore browser over the open load order: search /
    category / sort over the site's own paged listing, a card grid, a
    Thunderstore-style package page (README, Required / Versions /
    Changelog tabs, the latest version's facts, a version selector), Install
    = _install_package - the same job as "Add mod..." (download into the
    shared cache if absent, dependencies first, appended to the Active
    list, the panes refreshed), and the window stays open for the next
    one. "Add mod..." (a Team-Package name or a thunderstore.io package
    URL) stays as the power-user shortcut (user decision 2026-09-28).
  - Enable all / Disable all (THUNDERSTORE.md §8a): two links under
    Export... that set every Active mod's toggle at once (never the
    framework's, never list membership) - one unsaved edit, one undo step.
  - Import... / Export... (stage 3e; volt_py/bepinex_share.py): the
    load order as an r2modman / Thunderstore Mod Manager `.r2z` profile
    file, so VOLT and TMM users can swap load orders. Both buttons open the
    same popup menu RimWorld's do (_show_action_menu). "Export to file..."
    zips the on-screen lists (unsaved edits included, like Copy to new) +
    the load order's BepInEx/config files, default name <load order>.r2z.
    "Import from file..." always creates a NEW load order (name asked,
    the file's profile name offered): the framework at the file's
    version, each listed mod at the file's exact version (a version
    Thunderstore no longer has falls back to the latest; a package that
    can't be fetched is reported, the rest still install), the config
    files restored, enabled: false mods switched off - one busy job with
    per-package progress, then a summary dialog. A file made for another
    game is refused. "Export as code..." / "Import from code..." are the
    same .r2z through Thunderstore's own profile-code service (the one
    r2modman / TMM use, so codes cross over both ways): export asks for
    confirmation every time (the profile and its config files go to a
    public service; anyone with the code can fetch it), uploads as a job
    and shows the code in a small dialog with a Copy button; import asks
    for the code (whitespace / a pasted URL tolerated, validated before
    any request), downloads it as a job into <APP-ROOT>/cache/profiles/,
    then runs the file import unchanged (name prompt, job, summary).
    "Local mod (.zip)..." (THUNDERSTORE.md §8b) is the menu's odd one out:
    one mod from a Thunderstore-shaped zip on disk into the OPEN load
    order (screens/bepinex_local_import_dialog.py picks + validates it,
    bepinex_load_orders.import_local_mod installs it) - _install_package's
    job and refresh, so it lands in Active like a download, never an
    unsaved change; recorded online_source: false (no update check).
    "Dependency strings..." (THUNDERSTORE.md §8d) is read-only: the
    framework + every switched-on Active mod (on-screen, unsaved edits
    included) as `"Team-Package-Version",` lines for a modpack's
    manifest.json, in the code dialog's shape (read-only box, Copy, Close;
    bepinex_share.dependency_strings; local imports left out, counted).
  - Modded (stage 3c; volt_py/bepinex_launch.py has the mechanism; the
    button was "Run" until v0.4.27 - the method is still _run, the log
    prefix still `run:`): the open load order's Doorstop loader files are
    copied into the game folder
    (anything already there is backed up), the game is started through
    `steam.exe -applaunch` with the Doorstop arguments pointing at the
    load order's own BepInEx, and the screen stays busy while the game
    runs (a poll of `tasklist` every 2 s, off the GUI thread) - the
    running load order's DLLs are mapped by the game, so a Save / Update /
    Uninstall rename would fail mid-way. When it exits, the copied files
    are removed and the backups restored ("game folder restored"). Never
    saves: unsaved changes and missing-dependency errors each ask first, a
    BepInEx/ folder inside the game install asks once. A launch record
    left by a previous VOLT session is handled on open (_recover_launch):
    re-attach if the game is still running, else clean up and say so.
    Vanilla (v0.4.27, right above Modded; both carry a play-triangle icon,
    _play_icon) is _run(modded=False): a plain Steam launch, nothing
    copied, no confirms - the screen stays locked while it runs, exactly
    as for Modded (user decision 2026-09-28). Modded needs a load order
    open; Vanilla only the game (enabled whenever the screen isn't busy,
    load order or not); the Vanilla button is theme.py's neutral
    "vanilla" variant (a step lighter than Save), Modded stays primary.
  - Row right-click: Open folder (BepInEx/plugins/<Team-Package>), Open on
    Thunderstore, Open website, Copy Thunderstore name, Edit config..., Update
    (when one is available), Reinstall (0.6.27), Uninstall... (remove_mod,
    confirmed; not the framework).
  - Files missing (0.6.27, PLAN.md §11 (f)): every manifest read
    (_take_manifest: open, switch, Rescan, after any change) runs
    bepinex_load_orders.missing_files - one walk of the tree's BepInEx/
    folder - so a mod whose files were deleted outside VOLT gets a "Files
    missing" pill (bepinex_mod_list.py), a tooltip line and a "files"
    warning in the issues window / "⚠ N" count. Reinstall (row menu, any
    mod, always enabled while idle - a harmless repair on a healthy mod)
    = reinstall_mod: the same version again from the cached zip (or
    downloaded, the bar then shows), state / position / config kept.
  - Edit config... (THUNDERSTORE.md §7; screens/bepinex_config_window.py):
    the open load order's BepInEx/config/ files, browsed and edited in a
    split-pane window. Scoped to the whole load order, not a mod (no
    reliable file-to-package mapping exists), so it opens from the
    load-order picker's right-click menu and from every row's menu alike -
    the row entry just pre-fills the search with the package name when
    that matches a file.

First-run guidance (PLAN.md §10, 0.6.23; words + rules in volt_py/first_run.py,
widgets in screens/first_run_widgets.py): while the game is found and no
profile is open, a card on the Active list's empty dot grid ("Let's set up
your first profile." + Create a profile / Import one someone shared = the
existing New profile / Import... actions); every control disabled only for
want of a profile says "Create a profile first."; and a get-started checklist band under
the profile bar ticks off game folder / profile / mods / first modded
launch (settings has_launched), until all four are done or Hide
(settings checklist_dismissed). _apply_first_run keeps all of it in step.

Network work (create - the framework download; add; update one / all;
the check pass) runs on a daemon thread (rimworld_main_screen.py's
_fetch_community_rules pattern: a QObject carrier's queued signal brings
the result back), one mutating job at a time - the screen's `_busy` text
disables everything that could conflict meanwhile (buttons, picker, the
rows' controls) and shows in the status text. The check pass is read-only
and may overlap a job.
"""

import re
import threading
import time
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from volt_py import bepinex_launch as bl, bepinex_load_orders as lo, bepinex_share as share, icons, painters, paths, theme
from volt_py import download_state as ds
from volt_py import first_run as fr
from volt_py import mod_icons
from volt_py import thunderstore as ts
from volt_py.app_root import migrate_legacy_app_root, resolve_app_root
from volt_py.applog import clip, init_log, log
from volt_py.bepinex_install import BEPINEX_DIR, PackageError
from volt_py.mods import natural_key
from volt_py.paths import norm
from volt_py.screens.bepinex_browse_window import DEPRECATED_BANNER, BepInExBrowseWindow, _IconLoader, rounded_pixmap
from volt_py.screens.bepinex_config_window import BepInExConfigWindow
from volt_py.screens.bepinex_issues_window import BepInExIssuesWindow
from volt_py.screens.bepinex_local_import_dialog import LocalModDialog
from volt_py.screens.bepinex_mod_list import ROW_ICON_PX, ROW_ICON_RADIUS, BepInExModListView, RowInfo
from volt_py.screens.details_panel import details_well, readout
from volt_py.screens.download_bar import PackageDownloadBar
from volt_py.screens.error_box import show_error
from volt_py.screens.first_run_widgets import ChecklistStrip, EmptyStateCard
from volt_py.screens.bepinex_settings_window import BepInExSettingsWindow
from volt_py.screens.help_window import HelpWindow
from volt_py.screens.rimworld_main_screen import (
    ACTIONS_WIDTH,
    BAR_SIDE,
    GAP,
    GRID_MIN_WIDTH,
    GAMES_TOOLTIP,
    GRID_STRETCH,
    NOTICE_BOTTOM,
    SOURCE_LABEL,
    _EYE_TOOLTIP,
    _Notice,
    _StatusText,
    _button,
    _eye_icon,
    _games_button,
    _issue_count_html,
    _label,
    _panel,
)
from volt_py.settings import SettingsStore

IMPORT_TOOLTIP = (
    "Open a profile file (.r2z) someone shared - from VOLT, r2modman or Thunderstore Mod Manager - as a new "
    "profile or in place of the open one. Its mods are downloaded and its mod settings put in place."
)
EXPORT_TOOLTIP = (
    "Save the open profile as a file (.r2z) to share: the mod list, versions, on/off switches and mod settings. "
    "The mods themselves download again on the other computer. VOLT, r2modman and Thunderstore Mod Manager can open it."
)
ENABLE_ALL_TOOLTIP = "Switch every mod in the Active list on. Press Save to keep it."
DISABLE_ALL_TOOLTIP = (
    "Switch every mod in the Active list off (the mod loader stays on). The mods stay in the list; press Save to "
    "keep it."
)
IMPORT_CODE_TOOLTIP = (
    "Paste a profile code someone sent you (from VOLT, r2modman or Thunderstore Mod Manager). VOLT downloads "
    "the profile from Thunderstore and imports it, as a new profile or in place of the open one."
)
EXPORT_CODE_TOOLTIP = (
    "Upload the open profile (mod list and mod settings) to Thunderstore and get a short code to send. Anyone with "
    "the code can import it in VOLT, r2modman or Thunderstore Mod Manager."
)
EXPORT_CODE_CONFIRM = (
    'Upload "{name}" to Thunderstore?\n\nThe profile - its mod list and all its mod settings files - is uploaded '
    "to Thunderstore's public profile-sharing service (the one r2modman and Thunderstore Mod Manager use). Anyone "
    "who has the code can download it, and it can't be taken back. The mods themselves aren't uploaded.\n\n"
    "Don't share a profile whose mod settings hold anything private (server passwords, tokens and so on)."
)
IMPORT_CODE_PROMPT = (
    "Paste the profile code someone sent you - from VOLT, r2modman or Thunderstore Mod Manager (their "
    "\"Export as code\"). VOLT downloads the profile from Thunderstore, then imports it as a new profile or in "
    "place of the open one.\n\nCode:"
)
DEP_STRINGS_TOOLTIP = (
    "For modpack makers: list the open profile's mods as \"Author-ModName-Version\" lines (Thunderstore's "
    "dependency strings) to paste into a modpack's manifest.json - the mod loader and every switched-on Active mod."
)
SHARE_FILTER = "Profile files (*.r2z);;All files (*)"
IMPORT_LOCAL_TOOLTIP = (
    "Install one mod from a Thunderstore mod .zip on this computer into the open profile - for a mod that isn't "
    "(or is no longer) on Thunderstore. It's never checked for updates."
)
BROWSE_TOOLTIP = "Browse Thunderstore's {game} mods and install them into the open profile."
# The two launch buttons' tooltips ({game} = the game module's NAME).
MODDED_TOOLTIP = "Start {game} with this profile's mods."
VANILLA_TOOLTIP = "Start {game} without any mods."
PLAY_ICON_PX = icons.PLAY_ICON_PX
ADD_MOD_PROMPT = (
    "The mod to install into the open profile, with any mods it needs.\n"
    "Its name as Thunderstore writes it (Author-ModName, like {example}) or the address of its thunderstore.io page:"
)  # {example} = the game module's EXAMPLE_PACKAGE
# thunderstore.io/c/<community>/p/<Team>/<Package>/ (the site) or /package/<Team>/<Package>/ (older links).
_PACKAGE_URL = re.compile(r"thunderstore\.io/(?:c/[^/]+/p|package)/([A-Za-z0-9_]+)/([A-Za-z0-9_]+)/?", re.IGNORECASE)


# The play triangle moved to icons.py (0.6.15) so RimWorld's Modded / Vanilla
# share it; these names stay for this screen and its harness.
_play_icon = icons.play_icon


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _duration(seconds: float) -> str:
    """12s / 4m 05s / 1h 02m 03s."""
    s = max(0, int(seconds))
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s" if m else f"{s}s"


# Packages checked at or after this moment count as "checked this session": a
# switch back to a load order doesn't re-ask Thunderstore for them (ISO
# timestamps compare as text).
_SESSION_START = _now()
# The update check after an install / uninstall / update re-asks Thunderstore
# only for packages not successfully checked within this many seconds (new,
# stale or failed ones), not the whole load order: a full pass after every
# install is what pushed a 30+ package load order into HTTP 429.
RECHECK_AFTER_S = 300


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ago(value, now: datetime | None = None) -> str | None:
    """A Thunderstore date_updated as the mockup's "12d ago" / "2mo ago":
    today, Nd ago (under 30 days), Nmo ago (under a year), Ny ago; None for
    a missing / unreadable date."""
    dt = _parse_iso(value)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    days = max(0, (now - dt).days)
    if days < 1:
        return "today"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def parse_package_input(text: str) -> ts.PackageRef:
    """What Add mod... accepts: a "Team-Package" (a pinned version is
    ignored - the latest is installed) or a thunderstore.io package URL.
    ValueError for anything else."""
    s = (text or "").strip()
    m = _PACKAGE_URL.search(s)
    if m:
        return ts.PackageRef(m.group(1), m.group(2))
    ref = ts.PackageRef.parse(s)
    return ts.PackageRef(ref.namespace, ref.name)


def package_page_url(community: str, entry: dict) -> str:
    return f"{ts.SITE}/c/{community}/p/{entry['namespace']}/{entry['name']}/"


class _JobDone(QObject):
    """Carries a background job's result (and progress text) to the GUI
    thread over queued connections (rimworld_main_screen's carriers)."""

    done = Signal(object)  # {"ok": result} or {"error": message}
    progress = Signal(str)
    package = Signal(object)  # bepinex_load_orders.package_progress events (a downloads= job only)


def _details_text(rich: bool = False) -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
    )
    if rich:
        label.setOpenExternalLinks(True)
    return label


class ThunderstoreDetailsPanel(QFrame):
    """The mockup's .details: a deprecated package's warn banner (the Browse
    Mods page's, DEPRECATED_BANNER) at the top, the package icon
    (BepInEx/plugins/<Team-Package>/icon.png, when installed), Name / Author / Version ("2.30.2 installed
    (2.31.0 available)" in --warn when newer) / Last updated / Website (a
    link) and the description. details_panel.py's DetailsPanel is
    RimWorld-shaped (authors, path, package id, About/Preview.png), so this
    is its own class with the same frame and layout.

    Step 3.1 (DESIGN.md §15, v0.5.9) makes it a Circuit readout, same
    widgets in the same order: the icon on a framed mat
    (painters.ThumbFrame), copper terminal keys with a 1px rule between the
    rows (a grid, so key and value cells share each row's height and the
    rule runs unbroken), and the description in a recessed well that takes
    the pane's leftover height. The readout and well are details_panel's
    readout() / details_well() since the 0.6.8 follow-up (RimWorld's pane
    uses them too)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("panel", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        empty = self.details_empty = _label("Select a mod to see its details.", muted=True)
        empty.setWordWrap(True)
        empty.setContentsMargins(0, theme.FONT_SIZE_PX, 0, 0)
        empty.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(empty, 1)

        body = self.details_body = QWidget()
        body.setVisible(False)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        self.details_deprecated = QLabel(DEPRECATED_BANNER)
        self.details_deprecated.setProperty("role", "config-banner")  # theme.py: --warn on a 14% --warn wash
        self.details_deprecated.setWordWrap(True)
        self.details_deprecated.setVisible(False)
        body_layout.addWidget(self.details_deprecated)
        self.details_icon = painters.ThumbFrame()  # the icon on its framed mat (step 3.1)
        self.details_icon.setVisible(False)
        body_layout.addWidget(self.details_icon, 0, Qt.AlignmentFlag.AlignHCenter)

        # .details-grid as a readout, and the description's recessed well:
        # details_panel.readout / details_well, shared with RimWorld's pane
        # (0.6.8 follow-up; moved there unchanged)
        self.details_fields: dict[str, QLabel] = {}
        rows = []
        for key, title, rich in (
            ("name", "Name", False),
            ("author", "Author", False),
            ("version", "Version", True),
            ("updated", "Last updated", False),
            ("website", "Website", True),
        ):
            rows.append((title, _details_text(rich)))
            self.details_fields[key] = rows[-1][1]
        body_layout.addLayout(readout(rows))
        self.details_description = _details_text()
        body_layout.addWidget(details_well(self.details_description), 1)
        layout.addWidget(body, 1)
        self._icon_source = None

    def show_entry(self, entry: dict | None, *, latest: str | None = None, date_updated=None,
                   icon: Path | None = None, framework: bool = False, deprecated: bool = False) -> None:
        shown = entry is not None
        self.details_empty.setVisible(not shown)
        self.details_body.setVisible(shown)
        if not shown:
            return
        self.details_deprecated.setVisible(deprecated)
        f = self.details_fields
        f["name"].setText(entry["display_name"] or entry["name"])
        f["author"].setText(entry["namespace"])
        ver = f"{entry['version'] or '?'} installed"
        if latest and ts.is_newer(latest, entry["version"]):
            ver += f' &nbsp; <span style="color:{theme.WARN}">({latest} available)</span>'
        elif framework:
            ver += f' &nbsp; <span style="color:{theme.MUTED}">(mod loader, always on)</span>'
        f["version"].setText(ver)
        when = _parse_iso(date_updated)
        f["updated"].setText(when.strftime("%Y-%m-%d") if when else "-")
        url = entry.get("website_url") or ""
        if url:
            shown_url = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
            f["website"].setText(f'<a href="{url}" style="color:{theme.ACCENT}; text-decoration: none">{shown_url} ↗</a>')
        else:
            f["website"].setText("-")
        self.details_description.setText((entry.get("description") or "").strip() or "No description.")
        from PySide6.QtGui import QPixmap

        self._icon_source = QPixmap(str(icon)) if icon and icon.is_file() else None
        self._update_icon()

    def _update_icon(self) -> None:
        pixmap = self._icon_source
        if pixmap is None or pixmap.isNull():
            self.details_icon.setVisible(False)
            return
        # A 256x256 Thunderstore icon: at most 35% of the panel's height, as
        # DetailsPanel's preview (.details-preview max-height: 35%) - the
        # frame's mat / margins included; ThumbFrame shrinks, never grows.
        chrome_w, chrome_h = painters.thumb_chrome()
        self.details_icon.set_image(pixmap, self.width() - 20 - chrome_w, int(self.height() * 0.35) - chrome_h)
        self.details_icon.setVisible(True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_icon()


class _PathLine(QLabel):
    """The mockup's second header row: "<game>  /  <BepInEx folder>", muted
    12px (theme.py's path-line role), elided to the bar's width."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "path-line")  # theme.py: --muted, 12px (a QSS font-size beats setFont)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._full = ""

    def set_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width()
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, width)))


class BepInExMainScreen(QWidget):
    """The manager screen for one Thunderstore/BepInEx game (module docstring).
    `game`: that game's module (valheim.py's shape, a bepinex_games.GAMES
    row); `help_entries`: its Help window entries (help_entries(game))."""

    back_requested = Signal()  # the "Games" button / Alt+Left: back to the game select screen

    def __init__(self, game, help_entries: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.game = game
        self.game_name: str = game.NAME
        self.ts_game: lo.ThunderstoreGame = game.GAME
        self._help_entries = help_entries
        self.app_version = version("volt-py")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_paths_bar())
        layout.addWidget(self._build_load_order_bar())
        layout.addWidget(self._build_checklist())  # 0.6.23: a new band, nothing above / below it moves
        layout.addLayout(self._build_content_row(), 1)
        layout.addWidget(self._build_footer())
        # Each control that needs an open profile, with its own tooltip: while
        # it's disabled only for want of one, it says "Create a profile
        # first." instead (PLAN.md §10 (d), 0.6.23; _apply_load_order_state).
        # The Paths links and Update all set theirs where they're computed.
        self._profile_tips = {w: w.toolTip() for w in (
            self.load_order_picker, self.copy_button, self.export_button, self.enable_all_button,
            self.disable_all_button, self.rescan_button, self.config_button, self.add_mod_button,
            self.browse_button, self.save_button, self.run_button)}
        # First-run guidance (0.6.23) as last shown: the card / the checklist
        # band visible, the checklist's state - a change crossfades, a repeat
        # does nothing (_apply_first_run runs on every state change).
        self._card_shown = False
        self._checklist_shown = False
        self._checklist_state: tuple | None = None

        self.game_dir: Path | None = None
        self._game_source: str | None = None
        self._saved_game_dir_missing = False
        self.current_load_order: str | None = None  # slug
        self._manifest: dict | None = None  # the open load order, as last read / written
        self._entries: dict[str, dict] = {}  # full_name -> installed entry (framework included)
        self._framework: str | None = None  # the framework's full_name, when installed
        self._toggles: dict[str, bool] = {}  # on-screen toggle state of each Active mod (unsaved)
        # Dirty tracking (RimWorldMainScreen's baseline / history, plus the
        # toggles): a snapshot is (Active full_names in order, their toggles).
        self._baseline: tuple[list[str], dict[str, bool]] = ([], {})
        self._history: list[tuple[list[str], dict[str, bool]]] = []
        self._was_dirty = False
        # Update checking: what the last check learned per package (also on
        # disk: thunderstore.read_meta_cache), the packages whose check
        # failed, and whether a pass is running.
        self._check_errors: dict[str, str] = {}
        self._checking = False
        self._check_job: _JobDone | None = None
        self._busy: str | None = None  # a mutating job in flight (its status text)
        self._updating: set[str] = set()  # full_names with an update in flight
        self._jobs: dict[_JobDone, threading.Thread] = {}
        self._issues: dict[str, list[tuple[str, str]]] = {}  # full_name -> [(severity, text)] (the rows / tooltips)
        self._issue_list: list[dict] = []  # bepinex_load_orders.dependency_issues' dicts (the issues window)
        self._missing_files: dict[str, tuple[int, int]] = {}  # lo.missing_files of the open load order (0.6.27)
        # The launch being watched (Run): exe_name, load_order_name, modded,
        # phase "starting" / "running", started (monotonic). None when idle.
        self._launch: dict | None = None
        # Set once this screen is left for game select (_request_back): every
        # job's queued result / progress is dropped from then on (the screen
        # is being deleted; its threads just finish on their own).
        self._closed = False
        # The footer's download bar (0.6.25): the one downloads= job in flight
        # (its carrier), its download_state, full_name -> mod name. None = hidden.
        self._dl: ds.DownloadState | None = None
        self._dl_job: _JobDone | None = None
        self._dl_titles: dict[str, str] = {}
        # More bars on the same state while Browse Mods is open (0.6.26): its footer's and its
        # detail card's - the window is modal over the footer one (_browse_mods registers them).
        self._extra_dl_bars: list[PackageDownloadBar] = []
        # The rows' icons (0.6.26, mod_icons.py): icon key ("Team-Package-Version") -> the row's
        # pixmap, None while loading / when the package has none (the placeholder tile). Asked for
        # when a row is first painted; read from disk on _IconLoader's worker threads.
        self._icons: dict[str, QPixmap | None] = {}
        self._icon_waiting: set[str] = set()  # keys asked for, not back yet (one log line per batch, 0.6.27)
        self._icon_loader = _IconLoader(None, fetch=lambda key: mod_icons.load_icon(self.app_root, key))
        self._icon_loader.loaded.connect(self._on_row_icon, Qt.ConnectionType.QueuedConnection)
        self._poll_timer = QTimer(self)
        self._poll_timer.setSingleShot(True)  # re-armed after each poll's result, so polls never overlap
        self._poll_timer.timeout.connect(self._poll_launch)

        self.app_root = resolve_app_root(game.SLUG)
        moved = migrate_legacy_app_root(game.SLUG)  # before init_log creates the new folder
        self._log_path: Path | None = init_log(self.app_root)
        log(f"app root: {self.app_root} ({self.game_name})")
        if moved:
            log(moved)
        self._settings = SettingsStore(self.app_root)
        # Settings > General > Animations, app-wide from here on (phase 4)
        theme.set_animation_mode(self._settings.get()["animations"])
        log(f"animations: {self._settings.get()['animations']}")
        self._meta: dict[str, dict] = ts.read_meta_cache(self.app_root)
        log(f"package metadata cache: {len(self._meta)} packages")
        self._connect_signals()
        self._resolve_paths()
        self._reload_load_order_picker()
        self._apply_paths()
        self._recover_launch()
        if self.game_dir:
            self._apply_current_load_order_to_panes()
            self._start_update_check()
        else:
            log("no game folder: not opening a load order")

    # ---- paths: saved settings, else autodetect ----
    def _resolve_paths(self) -> None:
        s = self._settings.get()
        game_dir = s["game_dir"]
        if not (game_dir and self.game.is_game_root(game_dir)):
            log(
                f"paths: saved game folder {game_dir!r} is not a {self.game_name} install, autodetecting"
                if game_dir else "paths: no saved game folder, autodetecting"
            )
            found = self.game.autodetect()
            log(f"paths: autodetect found game={clip(found['game'])}, tried={clip(found['tried'])}")
            if found["game"]:
                self._settings.update({"game_dir": str(found["game"]["game_dir"]), "game_source": found["game"]["source"]})
        self._load_paths()
        log(f"paths: game_dir={self.game_dir}, source={self._game_source}")

    def _load_paths(self) -> None:
        s = self._settings.get()
        saved = s["game_dir"]
        ok = bool(saved) and self.game.is_game_root(saved)
        self.game_dir = Path(saved) if ok else None
        self._game_source = s["game_source"] if ok else None
        self._saved_game_dir_missing = bool(saved) and not ok

    def _paths_state(self) -> dict:
        return {"game_dir": self.game_dir, "game_source": self._game_source}

    def _reload_for_paths(self) -> None:
        had_game = self.game_dir is not None
        self._load_paths()
        log(f"paths changed: game_dir={self.game_dir}, source={self._game_source}, "
            f"saved game folder missing={self._saved_game_dir_missing}")
        self._apply_paths()
        if self.game_dir is not None and not had_game:
            self._apply_current_load_order_to_panes()
            self._start_update_check()

    def _browse_path(self, kind: str = "game", parent: QWidget | None = None) -> None:
        """Browse... for the game folder (the only path a Thunderstore game
        has - THUNDERSTORE.md TODO #6): a folder picker; a pick that isn't
        the game's install is refused with a warning, never saved."""
        if kind != "game":
            raise ValueError(f"Unknown path kind: {kind}")
        current = self._settings.get()["game_dir"]
        log(f"browse game folder: picker opened at {current}")
        picked = QFileDialog.getExistingDirectory(
            parent if parent is not None else self, f"Locate your {self.game_name} install folder", str(current or "")
        )
        if not picked:
            log("browse game folder: cancelled")
            return
        picked = str(norm(picked))
        if not self.game.is_game_root(picked):
            self._warn(
                "Couldn't set game folder",
                f"That folder doesn't look like where {self.game_name} is installed.",
                means=f"VOLT looks for {self.game.DATA_DIR} or the game's .exe inside the folder you pick. "
                      "The game folder wasn't changed.",
                tryit=f"Pick the folder that holds the {self.game_name} .exe, or press Autodetect to find it for you. "
                      f"In Steam: right-click {self.game_name} > Manage > Browse local files shows it.",
                details=f"Picked: {picked}\nExpected inside it: {self.game.DATA_DIR} or one of {', '.join(self.game.GAME_EXES)}",
                parent=parent,
            )
            return
        try:
            self._settings.update({"game_dir": picked, "game_source": "manual"})
        except OSError as err:
            self._warn("Couldn't save settings", "VOLT couldn't save your settings.",
                       means="The change you made won't be remembered next time VOLT starts.",
                       tryit="Make sure VOLT's folder isn't read-only or full, then try again.",
                       details=str(err), parent=parent)
            return
        log(f"browse game folder: picked {picked}")
        self._reload_for_paths()
        self._notice("Paths", f"Game folder set to {self.game_dir}.")

    def _autodetect_paths(self, parent: QWidget | None = None) -> None:
        found = self.game.autodetect()
        log(f"autodetect (user): found game={clip(found['game'])}, tried={clip(found['tried'])}")
        if found["game"]:
            try:
                self._settings.update({"game_dir": str(found["game"]["game_dir"]), "game_source": found["game"]["source"]})
            except OSError as err:
                self._warn("Couldn't save settings", "VOLT couldn't save your settings.",
                           means="The change you made won't be remembered next time VOLT starts.",
                           tryit="Make sure VOLT's folder isn't read-only or full, then try again.",
                           details=str(err), parent=parent)
                return
        self._reload_for_paths()
        if found["game"]:
            self._notice("Autodetect", f"Found {self.game_name} (Steam) at {found['game']['game_dir']}.")
        else:
            self._warn("Autodetect", f"VOLT couldn't find {self.game_name} on this computer.",
                       means="Autodetect only looks in Steam's usual library folders.",
                       tryit=f"Use Browse to pick the folder {self.game_name} is installed in. In Steam: right-click "
                             f"{self.game_name} > Manage > Browse local files shows it.",
                       details="Looked in: " + (", ".join(str(t) for t in found.get("tried") or []) or "(nowhere)"),
                       parent=parent)

    def _show_settings(self) -> None:
        log("settings window opened")
        BepInExSettingsWindow(
            self.game_name, self._paths_state, self._browse_path, self._autodetect_paths, self._warn,
            self._log_path, self, app_root=self.app_root, is_busy=lambda: self._busy is not None,
            settings=self._settings, game=self.game, confirm=self._confirm,
            troubleshooting_info=self._troubleshooting_info,
        ).exec()
        log("settings window closed")

    def _troubleshooting_info(self) -> list[tuple[str, object]]:
        """Settings > Troubleshooting > Copy troubleshooting info: this
        screen's part (game, folder, Steam, the open load order, mod counts)."""
        active = self._active_ids()
        off = sum(1 for n in active if not self._toggles.get(n, True))
        return [
            ("Game", self.game_name),
            ("Game folder", f"{self.game_dir} ({SOURCE_LABEL.get(self._game_source) or self._game_source})"
             if self.game_dir else None),
            ("Steam", paths.find_steam_exe()),
            ("Profile", f"{self.load_order_picker.currentText()} ({self.current_load_order})"
             if self.current_load_order else None),
            ("Framework", self._framework),
            ("Mods", f"{len(active)} active ({off} toggled off), {len(self.inactive_list.mod_ids())} inactive"
             + (", unsaved changes" if self._dirty() else "")),
        ]

    def _show_help(self) -> None:
        log("help window opened")
        HelpWindow(self._help_entries, parent=self, report={
            "game": self.game_name, "slug": self.game.SLUG, "game_dir": self.game_dir, "profile_label": "Profile",
            "profile": self.load_order_picker.currentText() if self.current_load_order else None,
            "log_path": self._log_path,
        }).exec()
        log("help window closed")

    def _edit_config(self, query: str = "") -> None:
        """Edit config...: the open load order's BepInEx/config/ files
        (THUNDERSTORE.md §7). `query` pre-fills the window's search (a row's
        package name) when it matches a file there."""
        if self.current_load_order is None:
            return
        name = self.load_order_picker.currentText()
        log(f"edit config window opened for {self.current_load_order} (query={query!r})")
        BepInExConfigWindow(name, self._bepinex_dir(), self, query=query).exec()
        log("edit config window closed")

    def _apply_paths(self) -> None:
        has_game = self.game_dir is not None
        self.game_link.setEnabled(has_game)
        self.game_link.setToolTip(str(self.game_dir) if has_game else "")
        source_label = SOURCE_LABEL.get(self._game_source)
        self.storefront_tag.setText(source_label or "")
        self.storefront_tag.setVisible(bool(source_label))
        self._grid.setVisible(has_game)
        self._no_game.setVisible(not has_game)
        self._no_game_text.setText(
            (f"The saved {self.game_name} folder no longer exists." if self._saved_game_dir_missing
             else f"Autodetect didn't find a Steam install of {self.game_name}.")
            + f" Please locate your {self.game_name} install folder (the one containing {self.game.DATA_DIR})."
        )
        self.inactive_list.setEnabled(has_game)
        self.active_list.setEnabled(has_game)
        for search, eye in ((self.inactive_search, self.inactive_eye), (self.active_search, self.active_eye)):
            search.setEnabled(has_game)
            eye.setEnabled(has_game)
        self._apply_path_links()
        self._apply_load_order_state()

    # ---- load-order state: enabled buttons, dirty, issues, the update count ----
    def _apply_load_order_state(self) -> None:
        has_game = self.game_dir is not None
        has_lo = self.current_load_order is not None
        busy = self._busy is not None
        ready = has_game and not busy
        self.load_order_picker.setEnabled(ready and self.load_order_picker.count() > 0)
        self.new_button.setEnabled(ready)
        self.import_button.setEnabled(ready)  # creates a new load order: the game is all it needs
        self.export_button.setEnabled(ready and has_lo)
        self.enable_all_button.setEnabled(ready and has_lo and not all(self._toggles.values()))
        self.disable_all_button.setEnabled(ready and has_lo and any(self._toggles.values()))
        self.copy_button.setEnabled(ready and has_lo)
        self.rescan_button.setEnabled(ready and has_lo)
        self.config_button.setEnabled(ready and has_lo)
        self.add_mod_button.setEnabled(ready and has_lo)
        self.browse_button.setEnabled(ready and has_lo)
        self.save_button.setEnabled(ready and has_lo)
        self.run_button.setEnabled(ready and has_lo)
        self.vanilla_button.setEnabled(ready)  # no load order needed for a vanilla launch (user-directed 2026-09-28)
        no_profile = fr.needs_profile_tip(game_found=has_game, busy=busy, open_slug=self.current_load_order)
        for widget, tip in self._profile_tips.items():
            widget.setToolTip(fr.NO_PROFILE_TIP if no_profile else tip)
        # Games (back to game select): disabled for the whole of any busy
        # state, a running game included (leaving would skip its modded-run
        # cleanup); the tooltip says why.
        self.games_button.setEnabled(not busy)
        if not busy:
            self.games_button.setToolTip(GAMES_TOOLTIP)
        elif self._launch is not None:
            running = "starting" if self._launch["phase"] == "starting" else "running"
            self.games_button.setToolTip(f"Can't go back to game select while {self.game_name} is {running}.")
        else:
            self.games_button.setToolTip(f"Can't go back to game select until this finishes: {self._busy}")
        dirty = self._dirty()
        if dirty != self._was_dirty:
            log(f"unsaved changes: {'yes' if dirty else 'none'} ({len(self._history)} undo steps)")
            self._was_dirty = dirty
        self.dirty_label.setVisible(has_game and dirty)
        self.undo_button.setVisible(has_game and dirty)
        self.undo_button.setEnabled(ready)
        variant = "warn-outline" if dirty else ""
        if self.save_button.property("variant") != variant:
            self.save_button.setProperty("variant", variant)
            self.save_button.style().unpolish(self.save_button)
            self.save_button.style().polish(self.save_button)
        self._apply_update_button()
        self._update_issues()
        self.active_list.viewport().update()  # the rows' controls follow busy / toggles
        self.inactive_list.viewport().update()
        self._apply_first_run()

    def _apply_update_button(self) -> None:
        """The load-order bar's permanent update element (THUNDERSTORE.md §3):
        the live count + Update all while there are updates, else its state."""
        button = self.update_all_button
        count = len(self._updatable())
        if self._checking:
            text, enabled, variant, tip = "Checking for updates...", False, "", ""
        elif count:
            text, enabled, variant = f"{count} update{'s' if count != 1 else ''} · Update all", self._busy is None, "warn-outline"
            tip = "Download and install the latest version of every mod in this profile that has one."
        elif self._check_errors and self.current_load_order is not None:
            text, enabled, variant, tip = "Update check failed · Retry", self._busy is None, "", self._check_error()
        elif self._entries and all(n in self._meta for n in self._entries if self._entries[n].get("online_source", True)):
            text, enabled, variant, tip = "Up to date", False, "", "Every mod in this profile is at its latest version."
        else:
            no_profile = fr.needs_profile_tip(game_found=self.game_dir is not None, busy=self._busy is not None,
                                              open_slug=self.current_load_order)
            text, enabled, variant, tip = "Update all", False, "", fr.NO_PROFILE_TIP if no_profile else ""
        button.setText(text)
        # the drawn warning icon (icons.py) before "N updates" - was a "⚠"
        # in the text, which Windows drew as a color emoji
        button.setIcon(icons.icon("warn", theme.WARN, theme.DISABLED_WARN) if variant == "warn-outline" else QIcon())
        button.setEnabled(enabled)
        button.setToolTip(tip)
        if button.property("variant") != variant:
            button.setProperty("variant", variant)
            button.style().unpolish(button)
            button.style().polish(button)

    def _check_error(self) -> str:
        """The update check's error to show: Thunderstore's rate-limit message
        when any package hit it (it names the cure), else the first."""
        errs = list(self._check_errors.values())
        return ts.RATE_LIMITED_MSG if ts.RATE_LIMITED_MSG in errs else errs[0]

    # ---- first-run guidance (PLAN.md §10 (c)-(f), 0.6.23; volt_py/first_run.py) ----
    def _apply_first_run(self) -> None:
        """The empty-state card and the get-started checklist follow the
        screen's state (from _apply_load_order_state, i.e. after every
        change): the card while the game is found and no profile is open,
        its buttons enabled exactly as New profile / Import...; the
        checklist's four steps ticked live, the next one emphasised, each
        step's action enabled as its button is. A visibility change
        crossfades (painters.crossfade: Animations setting, no effect on
        the lists), a tick changes the band under a short one."""
        has_game = self.game_dir is not None
        card = self.first_run_card
        card.create_button.setEnabled(self.new_button.isEnabled())
        card.import_button.setEnabled(self.import_button.isEnabled())
        show = fr.show_card(game_found=has_game, open_slug=self.current_load_order,
                            active_rows=len(self.active_list.mod_ids()))
        if show != self._card_shown:
            self._card_shown = show
            log(f"first run: empty-state card {'shown' if show else 'hidden'}")
            self._fade(lambda: card.setVisible(show), self._active_pane)
        s = self._settings.get()
        mods = sum(1 for n in self._entries if n != self._framework) if self.current_load_order else 0
        st = fr.checklist(game_found=has_game, profiles=self.load_order_picker.count(), mods=mods,
                          launched=s["has_launched"], dismissed=s["checklist_dismissed"])
        if st["next"] is None and not s["checklist_dismissed"]:
            log("first run: every get-started step done, the checklist retires")
            self._remember({"checklist_dismissed": True})
        enabled = (self.settings_button.isEnabled(), self.new_button.isEnabled(), self.browse_button.isEnabled(), False)
        state = (st["done"], st["next"], enabled)
        if st["visible"] != self._checklist_shown:
            self._checklist_shown = st["visible"]
            self._checklist_state = state
            log(f"first run: checklist {'shown' if st['visible'] else 'hidden'} (done={st['done']}, next={st['next']})")

            def swap() -> None:
                self.checklist.set_state(*state)
                self._checklist_box.setVisible(st["visible"])

            self._fade(swap)  # the content row moves: the whole screen crossfades
        elif state != self._checklist_state:
            if st["done"] != (self._checklist_state or ((),))[0]:
                log(f"first run: checklist done={st['done']}, next={st['next']}")
            self._checklist_state = state
            if st["visible"]:
                self._fade(lambda: self.checklist.set_state(*state), self.checklist, theme.MOTION_FAST)
            else:
                self.checklist.set_state(*state)

    def _fade(self, swap, area: QWidget | None = None, duration: int = theme.MOTION) -> None:
        """swap() under a crossfade of `area` (a child widget; None = the
        whole screen). Before the screen is shown it just swaps."""
        rect = None if area is None else QRect(area.mapTo(self, QPoint(0, 0)), area.size())
        painters.crossfade(self, swap, duration, rect)

    def _remember(self, patch: dict) -> None:
        """A first-run settings key (checklist_dismissed / has_launched):
        best effort - a read-only settings file only means the guidance
        shows again next time."""
        try:
            self._settings.update(patch)
            log(f"first run: settings {patch}")
        except OSError as err:
            log(f"first run: couldn't save {patch}: {err!r}")

    def _hide_checklist(self) -> None:
        """The checklist's "Hide": gone for this game, for good."""
        log("first run: checklist hidden by the user")
        self._remember({"checklist_dismissed": True})
        self._apply_first_run()

    def _snapshot(self) -> tuple[list[str], dict[str, bool]]:
        ids = self._active_ids()
        return ids, {n: self._toggles.get(n, True) for n in ids}

    def _dirty(self) -> bool:
        return self._snapshot() != self._baseline

    def _reset_baseline(self) -> None:
        self._baseline = self._snapshot()
        self._history = []
        self._apply_load_order_state()

    def _connect_signals(self) -> None:
        self.games_button.clicked.connect(lambda: self._request_back())
        # Alt+Left = the Games button (window context, Qt's default), through the same guard
        QShortcut(QKeySequence("Alt+Left"), self).activated.connect(lambda: self._request_back())
        self.settings_button.setEnabled(True)
        self.settings_button.clicked.connect(lambda: self._show_settings())
        self.help_button.setEnabled(True)
        self.help_button.clicked.connect(lambda: self._show_help())
        self.game_link.clicked.connect(lambda: self._open_folder(self.game_dir))
        self.load_order_link.clicked.connect(lambda: self.current_load_order and self._open_folder(self._load_order_dir()))
        self.bepinex_link.clicked.connect(lambda: self.current_load_order and self._open_folder(self._bepinex_dir()))
        self.rescan_button.clicked.connect(lambda: self.rescan())
        self.config_button.clicked.connect(lambda: self._edit_config())
        self.import_button.clicked.connect(lambda: self._show_action_menu(self.import_button, self._import_menu_items()))
        self.export_button.clicked.connect(lambda: self._show_action_menu(self.export_button, self._export_menu_items()))
        self.add_mod_button.clicked.connect(lambda: self._add_mod())
        self.enable_all_button.clicked.connect(lambda: self._set_all_toggles(True))
        self.disable_all_button.clicked.connect(lambda: self._set_all_toggles(False))
        self.browse_button.clicked.connect(lambda: self._browse_mods())
        active_model = self.active_list.mod_model
        for signal in (active_model.rowsAboutToBeInserted, active_model.rowsAboutToBeRemoved,
                       active_model.rowsAboutToBeMoved):
            signal.connect(lambda *_: self._history.append(self._snapshot()))
        for signal in (active_model.rowsInserted, active_model.rowsRemoved, active_model.rowsMoved):
            signal.connect(lambda *_: self._apply_load_order_state())
        self.undo_button.clicked.connect(lambda: self._undo())
        QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self).activated.connect(lambda: self._undo_shortcut())
        self.inactive_list.selectionModel().selectionChanged.connect(
            lambda *_: self._on_selection_changed(self.inactive_list, self.active_list)
        )
        self.active_list.selectionModel().selectionChanged.connect(
            lambda *_: self._on_selection_changed(self.active_list, self.inactive_list)
        )
        self.inactive_list.doubleClicked.connect(lambda index: self._move(index, self.inactive_list, self.active_list))
        self.active_list.doubleClicked.connect(lambda index: self._move(index, self.active_list, self.inactive_list))
        self.load_order_picker.currentIndexChanged.connect(self._on_load_order_picker_changed)
        self.new_button.clicked.connect(lambda: self._new_load_order())
        self.copy_button.clicked.connect(lambda: self._copy_to_new_load_order())
        self.save_button.clicked.connect(lambda: self._save_load_order())
        self.run_button.clicked.connect(lambda: self._run())
        self.vanilla_button.clicked.connect(lambda: self._run(modded=False))
        self.update_all_button.clicked.connect(lambda: self._update_all_clicked())
        self.issues_button.clicked.connect(lambda: self._show_issues())

    # ---- paths bar links ----
    def _load_order_dir(self) -> Path | None:
        if self.current_load_order is None:
            return None
        return lo.tree_root(self.app_root, self.current_load_order)

    def _bepinex_dir(self) -> Path | None:
        if self.current_load_order is None:
            return None
        return lo.bepinex_dir(self.app_root, self.current_load_order)

    def _apply_path_links(self) -> None:
        """Paths: Load order / BepInEx follow the picker (disabled with none
        open), and the muted path line under the bar."""
        for link, path, what in ((self.load_order_link, self._load_order_dir(), ""),
                                 (self.bepinex_link, self._bepinex_dir(), "The mod loader's folder (BepInEx): ")):
            link.setEnabled(path is not None)
            link.setToolTip(f"{what}{path}" if path else fr.NO_PROFILE_TIP if self.game_dir is not None else "")
        parts = [str(p) for p in (self.game_dir, self._bepinex_dir()) if p]
        self.path_line.set_text("  /  ".join(parts))
        self.path_line.setVisible(bool(parts))

    @staticmethod
    def _open_folder(path: Path | None) -> None:
        if path is None:
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        log(f"open folder {path}: {'opened' if opened else 'FAILED (openUrl returned false)'}")

    def _open_url(self, url: str) -> None:
        opened = QDesktopServices.openUrl(QUrl(url))
        log(f"open url {url}: {'opened' if opened else 'FAILED'}")

    def _copy_text(self, text: str, done: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self._notice("Copied", done)

    def _pane_name(self, pane) -> str:
        return "Active" if pane is self.active_list else "Inactive"

    # ---- boxes / notices ----
    def _warn(self, title: str, what: str, *, means: str = "", tryit: str = "", details: str = "",
              parent: QWidget | None = None) -> None:
        """The friendly error box (screens/error_box.py, 0.6.24): what happened /
        what it means / what to try, Copy details for the raw detail. Logged
        there, every part included. parent: a dialog showing the failure, so
        the box sits over it; else this screen."""
        show_error(parent if parent is not None else self, title, what, means=means, tryit=tryit, details=details)

    def _notice(self, title: str, message: str) -> None:
        log(f"info shown: {title}: {message}")
        for old in self.findChildren(_Notice):
            old.close()
        notice = _Notice(title, message, self)
        self._place_notice(notice)
        notice.show()

    def _place_notice(self, notice: _Notice) -> None:
        notice.adjustSize()
        notice.move((self.width() - notice.width()) // 2, self.height() - notice.height() - NOTICE_BOTTOM)
        notice.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for notice in self.findChildren(_Notice):
            self._place_notice(notice)

    def _confirm(self, title: str, message: str, *, confirm_label: str, parent: QWidget | None = None) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, message, QMessageBox.StandardButton.Cancel,
                          parent if parent is not None else self)
        confirm = box.addButton(confirm_label, QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(confirm)  # Enter confirms (user decision 2026-09-29)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)  # Esc still cancels
        box.exec()
        confirmed = box.clickedButton() is confirm
        log(f"confirm shown: {title}: {message} -> {confirm_label if confirmed else 'Cancel'}")
        return confirmed

    def _confirm_discard(self) -> bool:
        return not self._dirty() or self._confirm(
            "Unsaved changes", "Discard unsaved changes to the current list?", confirm_label="Discard changes"
        )

    def _request_back(self) -> None:
        """The Games button and Alt+Left (0.6.8): back to the game select
        screen (MainWindow swaps a fresh one in and deleteLater()s this one).
        Does nothing while the button is disabled (busy - the shortcut
        doesn't follow it on its own) or when the unsaved-changes confirm is
        cancelled. Then _closed: jobs still running (an update check, a
        Browse fetch left behind when its window closed) finish on their own
        and their results are dropped (_run_job / _finish_job), and the
        launch poll timer is stopped."""
        if not self.games_button.isEnabled() or not self._confirm_discard():
            return
        self._closed = True
        self._poll_timer.stop()
        self._icon_loader.stop()
        log(f"back to game select: leaving the {self.game_name} manager")
        self.back_requested.emit()

    # ---- background jobs ----
    def _run_job(self, name: str, fn, on_done, *, progress=None, downloads=None) -> None:
        """Runs fn(report) on a daemon thread; on_done({"ok": result} or
        {"error": text}) then runs on the GUI thread. report(text) reaches
        `progress` (GUI thread) when given. `downloads` (full_names, may be
        empty): a job that fetches mods - the footer's download bar follows
        its per-mod events (_on_package) from the start and hides before
        on_done (or when the screen is left: _closed drops everything)."""
        carrier = _JobDone()
        carrier.done.connect(lambda payload: self._finish_job(carrier, on_done, payload), Qt.ConnectionType.QueuedConnection)
        if progress is not None:
            carrier.progress.connect(lambda text: None if self._closed else progress(text),
                                     Qt.ConnectionType.QueuedConnection)
        if downloads is not None:
            carrier.package.connect(lambda ev: None if self._closed else self._on_package(carrier, ev),
                                    Qt.ConnectionType.QueuedConnection)
            self._dl_job, self._dl = carrier, ds.seed_packages(downloads)
            self._dl_titles = {i: self._mod_title(i) for i in self._dl.wids}
            self._render_dl()
            log(f"download bar: job {name} started, {len(self._dl.wids)} mods known {clip(list(self._dl.wids), 600)}")

        def run() -> None:
            try:
                if downloads is None:
                    result = fn(carrier.progress.emit)
                else:
                    with lo.package_progress(carrier.package.emit):
                        result = fn(carrier.progress.emit)
                payload = {"ok": result}
            except Exception as err:  # every failure reaches the GUI as text; nothing crashes the thread
                log(f"[job {name}] failed: {err!r}")
                payload = {"error": str(err) or repr(err)}
            carrier.done.emit(payload)

        thread = threading.Thread(target=run, name=name, daemon=True)
        self._jobs[carrier] = thread
        thread.start()
        log(f"[job {name}] started (thread {thread.name})")

    def _finish_job(self, carrier: _JobDone, on_done, payload: dict) -> None:
        self._jobs.pop(carrier, None)
        if self._closed:  # finished after the screen was left (_request_back): nothing to show it on
            return
        if carrier is self._dl_job:  # its download bar goes before on_done's dialogs / follow-up jobs
            if self._dl is not None:
                log(f"download bar: job finished, {ds.count_text(self._dl)} mods, "
                    f"{len(self._dl.failed)} failed - bar hidden")
            self._dl_job, self._dl = None, None
            self._render_dl()
        on_done(payload)

    # ---- the footer's download bar (0.6.25, PLAN.md §11 (a)) ----
    def _mod_title(self, full_name: str) -> str:
        """The bar's name for a mod: its installed display name, else the
        package name with spaces (as Thunderstore shows it)."""
        if full_name in self._entries:
            return self._display_name(full_name)
        return full_name.split("-", 1)[-1].replace("_", " ")

    def _on_package(self, carrier: _JobDone, ev: dict) -> None:
        if carrier is not self._dl_job:  # a late event from a job already finished
            return
        kind = ev.get("type")
        for mod_id in ev["ids"] if kind == "plan" else [ev["id"]] if kind == "start" else []:
            self._dl_titles.setdefault(mod_id, self._mod_title(mod_id))
        self._dl = ds.apply_package_event(self._dl, ev)
        if kind == "plan":
            log(f"download bar: total now {len(self._dl.wids)} (pre-pass planned {len(ev['ids'])})")
        elif kind == "item-done":
            log(f"download bar: {ev['id']} {'done' if ev.get('ok') else 'FAILED: ' + clip(ev.get('message'), 300)} "
                f"({ds.count_text(self._dl)})")
        self._render_dl()

    def _render_dl(self) -> None:
        """The bars (the footer's + Browse Mods' while it's open) follow _dl:
        hidden (and cleared) when None or nothing to fetch yet."""
        for bar in (self.download_bar, *self._extra_dl_bars):
            if self._dl is None or not self._dl.wids:
                bar.setVisible(False)
                bar.clear()
            else:
                bar.render(self._dl, self._dl_titles)
                bar.setVisible(True)

    # ---- the rows' icons (0.6.26) ----
    def _row_icon(self, mod_id: str) -> QPixmap | None:
        """The row's icon pixmap, or None (placeholder); the first ask for a
        key queues its load."""
        key = mod_icons.icon_key(self._entries[mod_id])
        if key not in self._icons:
            self._icons[key] = None
            self._icon_waiting.add(key)
            self._icon_loader.request(key)
        return self._icons[key]

    def _on_row_icon(self, key: str, data: bytes) -> None:
        if self._closed:
            return
        self._icon_waiting.discard(key)
        if not self._icon_waiting:  # a batch of rows is done: one line, never one per paint
            s = mod_icons.take_stats()
            log(f"icons: batch done - {s['cache']} from the icon cache, {s['copied']} copied from downloaded zips, "
                f"{s['none']} without an icon (plain tile)")
        if not data:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            log(f"icons: {key}: icon.png isn't a readable image")
            return
        self._icons[key] = rounded_pixmap(pixmap, ROW_ICON_PX, ROW_ICON_RADIUS)
        for mod_list in (self.active_list, self.inactive_list):
            mod_list.viewport().update()

    def _set_busy(self, text: str | None) -> None:
        self._busy = text
        if text:
            self.status_text.set_status_text(text)
        self._apply_load_order_state()

    # ---- the open load order -> the panes ----
    def _read_manifest(self) -> dict | None:
        if self.current_load_order is None:
            return None
        try:
            return lo.load_load_order(self.app_root, self.current_load_order)
        except (OSError, ValueError) as err:
            self._warn("Couldn't open profile", "VOLT couldn't read this profile's saved mod list.",
                       means="Its file may be damaged, or made by a newer VOLT. Nothing was changed.",
                       tryit="Pick another profile, or delete this one and import or create it again.",
                       details=f"Profile folder: {self._load_order_dir()}\n{err}")
            return None

    def _take_manifest(self, manifest: dict | None) -> None:
        self._manifest = manifest
        self._entries = lo.installed(manifest) if manifest else {}
        fw = manifest.get("framework") if manifest else None
        self._framework = fw["full_name"] if fw else None
        # Files missing (0.6.27): one walk of BepInEx/ per manifest read, on the GUI thread
        # (a directory listing, no per-file stat; the log line has its time).
        self._missing_files = lo.missing_files(self.app_root, self.current_load_order, manifest) if manifest else {}

    def _apply_current_load_order_to_panes(self) -> None:
        """Shows the open load order's saved lists and toggles; they become
        the baseline (unsaved edits and undo are dropped)."""
        self._take_manifest(self._read_manifest())
        m = self._manifest
        active = [e["full_name"] for e in m["active"]] if m else []
        toggles = {e["full_name"]: e["enabled"] for e in m["active"]} if m else {}
        self._show_lists(active, toggles)
        self._reset_baseline()

    def _show_lists(self, active: list[str], toggles: dict[str, bool]) -> None:
        """Active = `active`'s installed, non-framework ids in order (the
        framework pinned first), Inactive = every other installed mod in
        name order. A repopulate, not an edit."""
        fw = self._framework
        shown: list[str] = []
        for n in active:
            if n in self._entries and n != fw and n not in shown:
                shown.append(n)
        active = shown
        self._toggles = {n: bool(toggles.get(n, True)) for n in active}
        inactive = sorted(
            (n for n in self._entries if n != fw and n not in active),
            key=lambda n: (natural_key(self._display_name(n)), n),
        )
        self.active_list.set_mod_ids([])
        self.inactive_list.set_mod_ids(inactive)
        self.active_list.set_mod_ids(([fw] if fw else []) + active)
        log(f"panes rebuilt for load order {self.current_load_order}: {len(active)} active "
            f"({sum(1 for n in active if not self._toggles[n])} off), {len(inactive)} inactive"
            f"{', framework ' + fw if fw else ', NO framework'}")
        self._show_details(None)

    def _active_ids(self) -> list[str]:
        """The Active list's mod ids, the framework left out."""
        return [n for n in self.active_list.mod_ids() if n != self._framework]

    def _undo_shortcut(self) -> None:
        """Ctrl+Z: exactly the undo button's click, and only while it could be
        clicked - shown (this screen showing, something to undo) and enabled
        (not busy). A focused text field keeps its own Ctrl+Z (Qt hands it
        the key first - ShortcutOverride - and this check covers the rest),
        and a list drag under way ignores it (the button can't be clicked
        mid-drag either)."""
        button = self.undo_button
        if (not button.isVisible() or not button.isEnabled()
                or isinstance(QApplication.focusWidget(), (QLineEdit, QTextEdit, QPlainTextEdit))
                or self.active_list._drag_state is not None or self.inactive_list._drag_state is not None):
            return
        log("undo: Ctrl+Z")
        button.click()

    def _undo(self) -> None:
        if not self._history:
            log("undo: nothing to undo")
            return
        log(f"undo: restoring the Active list from before the last change ({len(self._history) - 1} steps left)")
        ids, toggles = self._history.pop()
        self._show_lists(ids, toggles)
        self._apply_load_order_state()

    def rescan(self) -> None:
        """Rescan: re-reads the open load order from disk (its tree is the
        truth) and re-runs the update check. Unsaved edits would be lost, so
        it asks first."""
        if not self._confirm_discard():
            log("rescan: cancelled at the discard-changes prompt")
            return
        log(f"rescan: reloading load order {self.current_load_order}")
        self._apply_current_load_order_to_panes()
        self._start_update_check(force=True)

    # ---- load orders: picker, new, copy, delete, save ----
    def _reload_load_order_picker(self, select_slug: str | None = None) -> None:
        all_entries = lo.list_load_orders(self.app_root)
        for e in all_entries:
            if "error" in e:
                log(f"load-order picker: skipping unreadable load order {e['slug']}: {e['error']}")
        entries = [e for e in all_entries if "error" not in e]
        slugs = [e["slug"] for e in entries]
        last = self._settings.get()["last_load_order"]
        slug = select_slug if select_slug in slugs else last if last in slugs else slugs[0] if slugs else None
        picker = self.load_order_picker
        picker.blockSignals(True)
        picker.clear()
        for i, e in enumerate(entries):
            picker.addItem(e["name"])
            picker.setItemData(i, e["slug"])
        picker.setCurrentIndex(slugs.index(slug) if slug else -1)
        picker.blockSignals(False)
        self.current_load_order = slug
        self._apply_path_links()
        log(f"load-order picker reloaded: {len(entries)} load orders, current={slug} "
            f"(requested={select_slug}, last saved={last})")

    def _on_load_order_picker_changed(self, index: int) -> None:
        slug = self.load_order_picker.itemData(index)
        if slug == self.current_load_order:
            return
        if not self._confirm_discard():
            log(f"load order switch to {slug} cancelled: keeping unsaved changes in {self.current_load_order}")
            picker = self.load_order_picker
            picker.blockSignals(True)
            picker.setCurrentIndex(picker.findData(self.current_load_order))
            picker.blockSignals(False)
            return
        log(f"load order selected: {self.current_load_order} -> {slug}")
        self.current_load_order = slug
        self._apply_path_links()
        self._settings.update({"last_load_order": slug})
        self._apply_current_load_order_to_panes()
        self._start_update_check()

    def _show_load_order_menu(self, pos: QPoint) -> None:
        picker = self.load_order_picker
        slug, name = picker.currentData(), picker.currentText()
        if not slug or self._busy is not None:
            return
        menu = QMenu(picker)
        menu.addAction("Edit config...").triggered.connect(lambda: self._edit_config())
        menu.addSeparator()
        menu.addAction(f'Delete "{name}"...').triggered.connect(lambda: self._delete_load_order(slug, name))
        menu.exec(picker.mapToGlobal(pos))
        menu.deleteLater()

    def _delete_load_order(self, slug: str, name: str) -> None:
        if not self._confirm(
            "Delete profile",
            f'Delete "{name}"? The profile and every mod in it are removed from disk. This can\'t be undone.\n\n'
            "VOLT keeps its downloaded copies of the mods, and the game itself isn't touched.",
            confirm_label="Delete",
        ):
            log(f"delete load order {slug} ({name!r}): cancelled")
            return
        res = lo.delete_load_order(self.app_root, slug)
        if res.get("skipped"):
            self._warn("Couldn't delete everything", f"{len(res['skipped'])} file(s) of the profile couldn't be removed.",
                       means="Another program (often the game) is probably still using them. The rest is gone.",
                       tryit=f"Close {self.game_name} and anything showing that folder, then delete the leftover files "
                             "by hand (Copy details lists them).",
                       details="\n".join(str(s.get("path", s)) for s in res["skipped"]))
        old = self.current_load_order
        self._reload_load_order_picker(select_slug=old)
        if self.current_load_order == old:
            self._apply_load_order_state()
            return
        self._settings.update({"last_load_order": self.current_load_order})
        self._apply_current_load_order_to_panes()
        self._start_update_check()

    def _ask_name(self, title: str, message: str | None = None, default: str = "") -> str | None:
        name, ok = QInputDialog.getText(self, title, f"{message}\n\nName:" if message else "Name:",
                                        QLineEdit.EchoMode.Normal, default)
        if not ok or not name.strip():
            log(f"{title}: {'cancelled' if not ok else 'empty name entered'}, nothing created")
            return None
        return name.strip()

    def _new_load_order(self) -> None:
        """New load order: a folder + manifest, then the framework package
        downloaded (or taken from the cache) and installed - so the
        download runs as a job, the screen busy meanwhile."""
        if not self._confirm_discard():
            log("New load order: cancelled at the discard-changes prompt")
            return
        name = self._ask_name(
            "New profile",
            f"A new profile gets its own copy of the mod loader ({self.ts_game.framework_package}), downloaded "
            "from Thunderstore (or reused if VOLT already has it), so it's ready to play right away.",
        )
        if name is None:
            return
        self._set_busy(f"Creating profile \"{name}\" - installing {self.ts_game.framework_package}...")

        def job(report):
            return lo.create_load_order(self.app_root, name, self.ts_game, self.app_version)

        def done(payload: dict) -> None:
            self._set_busy(None)
            if "error" in payload:
                self._warn("Couldn't create profile", f'Couldn\'t create the profile "{name}".',
                           means=f"Every profile needs the mod loader ({self.ts_game.framework_package}) from "
                                 "Thunderstore, and VOLT couldn't get it. No profile was made.",
                           tryit="Check your internet connection and try again in a minute.",
                           details=payload["error"])
                self.status_text.set_status_text(f"Couldn't create \"{name}\".", "error")
                return
            manifest = payload["ok"]
            log(f"New load order: created {name!r} as slug {manifest['slug']}")
            self._settings.update({"last_load_order": manifest["slug"]})
            self._reload_load_order_picker(select_slug=manifest["slug"])
            self._apply_current_load_order_to_panes()
            self.status_text.set_status_text(f"Created \"{name}\" with {manifest['framework']['full_name']} "
                                             f"{manifest['framework']['version']}.")
            self._start_update_check()

        self._run_job("create-load-order", job, done, downloads=[self.ts_game.framework_package])

    def _copy_to_new_load_order(self) -> None:
        """Copies the open load order's whole tree under a new name, then
        applies the on-screen lists / toggles to the copy (so unsaved edits
        are what the copy holds), and opens it."""
        if self.current_load_order is None:
            return
        name = self._ask_name("Copy to new profile")
        if name is None:
            return
        src = self.current_load_order
        try:
            manifest = lo.copy_load_order(self.app_root, src, name)
            if self._dirty():
                manifest = lo.save_load_order(self.app_root, manifest["slug"], *self._save_lists())
        except (OSError, ValueError) as err:
            log(f"Copy to new load order: {src} -> {name!r} failed: {err!r}")
            self._warn("Couldn't copy profile", f'Couldn\'t copy the profile to "{name}".',
                       means="The open profile is unchanged.",
                       tryit="Make sure the disk isn't full and nothing (like the game) is using the profile's "
                             "files, then try again.",
                       details=str(err))
            return
        log(f"Copy to new load order: {src} -> {manifest['slug']} ({name!r})")
        self._settings.update({"last_load_order": manifest["slug"]})
        self._reload_load_order_picker(select_slug=manifest["slug"])
        self._apply_current_load_order_to_panes()
        self.status_text.set_status_text(f"Copied to \"{name}\".")

    # ---- Import / Export (THUNDERSTORE.md §4; bepinex_share.py) ----
    def _import_menu_items(self) -> list[tuple]:
        """Import...'s entries: (label, handler, enabled, tooltip)."""
        return [
            ("Import from file...", self._import_file, True, IMPORT_TOOLTIP),
            ("Import from code...", self._import_code, True, IMPORT_CODE_TOOLTIP),
            ("Local mod (.zip)...", self._import_local_mod, self.current_load_order is not None,
             IMPORT_LOCAL_TOOLTIP if self.current_load_order is not None else fr.NO_PROFILE_TIP),
        ]

    def _export_menu_items(self) -> list[tuple]:
        """Export...'s entries: (label, handler, enabled, tooltip)."""
        return [
            ("Export to file...", self._export_file, True, EXPORT_TOOLTIP),
            ("Export as code...", self._export_code, True, EXPORT_CODE_TOOLTIP),
            ("Dependency strings...", self._show_dependency_strings, self.current_load_order is not None, DEP_STRINGS_TOOLTIP),
        ]

    def _show_action_menu(self, button: QPushButton, items: list[tuple]) -> None:
        """Import... / Export...: a native menu dropped 4px below the button
        (rimworld_main_screen's), entries (label, handler[, enabled,
        tooltip]) - a disabled entry is a later update, its tooltip says so."""
        log(f"{button.text()} menu opened")
        menu = QMenu(button)
        menu.setToolTipsVisible(True)
        for label, fn, *rest in items:
            enabled = rest[0] if rest else True
            action = menu.addAction(label)
            action.setEnabled(bool(enabled))
            if len(rest) > 1 and rest[1]:
                action.setToolTip(rest[1])
            action.triggered.connect(lambda _checked=False, fn=fn: fn())
        menu.exec(button.mapToGlobal(QPoint(0, button.height() + 4)))
        menu.deleteLater()

    def _share_dir(self) -> Path | None:
        """The folder of the last Import / Export file pick (settings
        `share_dir`), if it still exists."""
        d = self._settings.get().get("share_dir")
        return Path(d) if d and Path(d).is_dir() else None

    def _remember_share_dir(self, path: Path) -> None:
        try:
            self._settings.update({"share_dir": str(path.parent)})
        except OSError as err:
            log(f"share dir not remembered: {err!r}")

    def _export_file(self) -> None:
        """Export to file...: the open load order as a .r2z - the on-screen
        lists / toggles (unsaved edits included, Copy to new's rule) and its
        BepInEx/config files - written as a job."""
        if self.current_load_order is None or self._busy is not None:
            return
        slug, lo_name = self.current_load_order, self.load_order_picker.currentText()
        start = self._share_dir()
        default = share.export_file_name(lo_name)
        path, _ = QFileDialog.getSaveFileName(
            self, f'Export profile "{lo_name}"', str(start / default) if start else default, SHARE_FILTER,
        )
        if not path:
            log(f"export {slug}: file picker cancelled")
            return
        path = Path(path)
        if not path.suffix:
            path = path.with_suffix(share.EXTENSION)
        self._remember_share_dir(path)
        active, inactive = self._save_lists()
        log(f"export {slug} ({lo_name!r}) -> {path}: {len(active)} active, {len(inactive)} inactive"
            f"{' (unsaved edits included)' if self._dirty() else ''}")
        self._set_busy(f'Exporting "{lo_name}"...')

        def job(report):
            return share.export_profile(self.app_root, slug, self.ts_game, path, active=active, inactive=inactive,
                                        app_version=self.app_version)

        def done(payload: dict) -> None:
            self._set_busy(None)
            if "error" in payload:
                self._warn("Export failed", f'Couldn\'t export "{lo_name}".',
                           means="Your profile is unchanged; only the export didn't happen.",
                           tryit="Pick a different place to save the file (one you can write to) and try again.",
                           details=payload["error"])
                self.status_text.set_status_text(f"Couldn't export \"{lo_name}\".", "error")
                return
            res = payload["ok"]
            self.status_text.set_status_text(
                f"Exported \"{lo_name}\": {res['mods']} mods, {res['config_files']} settings files -> {path.name}.")
            self._notice("Export", f"Exported \"{lo_name}\" ({res['mods']} mods, {res['files']} files) to {path}.")

        self._run_job(f"export-{slug}", job, done)

    def _import_file(self) -> None:
        """Import from file...: a .r2z (VOLT's or TMM's) -> a NEW load order
        or, with one open, in place of it (never merged into an existing
        one). Reads and checks the file first (not a profile / another
        game's = refused before anything is created), then _import_profile:
        one busy job - framework, each listed mod at the file's version,
        config files, on/off flags (bepinex_share.import_profile /
        replace_profile) - and a summary dialog."""
        if self.game_dir is None or self._busy is not None:
            return
        start = self._share_dir()
        path, _ = QFileDialog.getOpenFileName(self, "Import a profile from a file", str(start) if start else "", SHARE_FILTER)
        if not path:
            log("import: file picker cancelled")
            return
        path = Path(path)
        self._remember_share_dir(path)
        try:
            profile = share.read_profile(path)
        except (share.ProfileError, OSError) as err:
            self._warn("Couldn't import", f"VOLT couldn't read {path.name}.",
                       means="It may not be a profile file (.r2z), or it may be damaged. Nothing was changed.",
                       tryit="Ask for the file again, or import it with a profile code instead.",
                       details=f"File: {path}\n{err}")
            return
        self._import_profile(profile, path.name)

    def _ask_import_mode(self, source: str, profile_name: str, current: str) -> str | None:
        """With a load order open (0.6.22): add the import as a new one
        (the default, Enter) or replace the open one; None = Cancel / Esc."""
        box = QMessageBox(QMessageBox.Icon.Question, "Import profile",
                          f'{source} holds the profile "{profile_name}". Add it as a new profile, or replace the open '
                          f'profile "{current}" with it?', QMessageBox.StandardButton.NoButton, self)
        new = box.addButton("Add as a new profile", QMessageBox.ButtonRole.AcceptRole)
        replace = box.addButton(f'Replace current profile ("{current}")', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(new)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        mode = "new" if clicked is new else "replace" if clicked is replace else None
        log(f"import mode asked ({source}, open load order {current!r}) -> {mode or 'Cancel'}")
        return mode

    def _ask_replace_anyway(self, summary: dict) -> bool:
        """A Replace whose import finished with failures (0.6.22 follow-up):
        replace anyway (keep the partial new profile) or keep the old one.
        Keep is the default and Esc - destructive, asked after the fact."""
        old, n = summary["old_name"], len(summary["failed"]) + len(summary["errors"])
        box = QMessageBox(QMessageBox.Icon.Warning, "Replace profile",
                          f'The import finished, but {n} mod{"s" if n != 1 else ""} couldn\'t be installed:\n\n'
                          + "\n".join(share.failed_lines(summary))
                          + f'\n\nReplace "{old}" with the incomplete "{summary["name"]}" anyway, or keep "{old}" as it is?',
                          QMessageBox.StandardButton.NoButton, self)
        anyway = box.addButton(f'Replace "{old}" anyway', QMessageBox.ButtonRole.DestructiveRole)
        keep = box.addButton(f'Keep "{old}"', QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)
        box.exec()
        answer = box.clickedButton() is anyway
        log(f"replace {summary['old_slug']}: {n} failed -> {'replace anyway' if answer else 'keep the old one'}")
        return answer

    def _confirm_replace(self, profile: dict, source: str, new_name: str) -> bool:
        """Replace's one confirm (it stands in for the discard prompt): names
        the open load order and how many of its mods aren't in the import."""
        old_name = self.load_order_picker.currentText()
        manifest = self._read_manifest()
        if manifest is None:
            return False
        listed = {m["full_name"] for m in profile["mods"]}
        held = [e["full_name"] for e in manifest["active"] + manifest["inactive"]]
        dropping = [x for x in held if x not in listed]
        log(f"replace {self.current_load_order}: holds {len(held)} mods, {len(dropping)} not in {source}: {dropping}")
        one = len(dropping) == 1
        holds = (f'"{old_name}" holds no mods yet. ' if not held
                 else f'"{old_name}" holds {share._plural(len(held), "mod")}; all of them are in the import. ' if not dropping
                 else f'"{old_name}" holds {share._plural(len(held), "mod")}; {len(dropping)} of them '
                      f"{'is' if one else 'are'}n't in the import and drop{'s' if one else ''} out. ")
        return self._confirm(
            "Replace profile",
            f'Replace "{old_name}" with "{new_name}" from {source}?\n\n' + holds
            + ("Its unsaved changes are discarded. " if self._dirty() else "")
            + f'Downloaded mod files stay in VOLT\'s cache.\n\n"{old_name}" is only replaced once the import completes: '
            f"if anything fails, it's left as it is. This can't be undone.",
            confirm_label="Replace",
        )

    def _import_profile(self, profile: dict, source: str) -> None:
        """The shared tail of both imports (a picked file, a downloaded
        code): game check; with a load order open, New or Replace
        (_ask_import_mode). New: discard prompt, name prompt (the file's
        profile name offered), bepinex_share.import_profile. Replace: one
        confirm, bepinex_share.replace_profile under the file's name (the
        old load order deleted only once the import completed). Either way
        one busy job, the resulting load order opened, the summary dialog."""
        path = Path(profile["path"])
        try:
            share.check_game(profile, self.ts_game, self.game_name)
        except share.ProfileError as err:
            self._warn("Couldn't import", f"This profile isn't for {self.game_name}.",
                       means="It was made for another game, so its mods wouldn't work here. Nothing was changed.",
                       tryit=f"Import it in that game's manager, or ask for a {self.game_name} profile.",
                       details=str(err))
            return
        n = sum(1 for m in profile["mods"] if m["full_name"] != self.ts_game.framework_package)
        default = profile["name"] or path.stem
        old_slug, old_name = self.current_load_order, self.load_order_picker.currentText()
        mode = "new" if old_slug is None else self._ask_import_mode(source, default, old_name)
        if mode is None:
            return
        if mode == "replace":
            if not self._confirm_replace(profile, source, default):
                log(f"replace {old_slug}: cancelled at the confirm")
                return
            name = default
            log(f"import {source} ({path}) -> replace {old_slug} ({old_name!r}) with {name!r}: {n} mods, "
                f"{len(profile['files'])} files, {len(profile['skipped'])} skipped, problems={profile['problems']}")
            self._set_busy(f'Replacing "{old_name}" with "{name}" from {source}...')

            def job(report):
                return share.replace_profile(self.app_root, path, old_slug, self.ts_game, self.app_version,
                                             progress=report, game_name=self.game_name, source=source)
        else:
            if not self._confirm_discard():
                log("import: cancelled at the discard-changes prompt")
                return
            name = self._ask_name(
                "Import profile",
                f"{source} holds {n} mod{'s' if n != 1 else ''} and {len(profile['files'])} mod settings file"
                f"{'s' if len(profile['files']) != 1 else ''}. It becomes a new profile: VOLT sets up the mod loader "
                "for it, downloads every mod at the file's version, then puts the mod settings in place. Your other "
                "profiles aren't touched.",
                default,
            )
            if name is None:
                return
            log(f"import {source} ({path}) -> new load order {name!r}: {n} mods, {len(profile['files'])} files, "
                f"{len(profile['skipped'])} skipped, problems={profile['problems']}")
            self._set_busy(f'Importing "{name}" from {source}...')

            def job(report):
                return share.import_profile(self.app_root, path, name, self.ts_game, self.app_version,
                                            progress=report, game_name=self.game_name, source=source)

        def done(payload: dict) -> None:
            self._set_busy(None)
            replacing = mode == "replace"
            if replacing and "ok" in payload and payload["ok"].get("partial"):  # mods failed: ask, then finish
                keep_new = self._ask_replace_anyway(payload["ok"])
                try:
                    payload = {"ok": share.finish_replace(self.app_root, payload["ok"], keep_new=keep_new)}
                except (share.ProfileError, OSError, ValueError) as err:
                    payload = {"error": str(err)}
            if "error" in payload:
                old = self.current_load_order
                self._reload_load_order_picker(select_slug=old)  # a load order left half-built still lists
                if self.current_load_order != old:
                    self._apply_current_load_order_to_panes()
                self._apply_load_order_state()
                log(f"import ({mode}): failed{f', {old_name!r} kept' if replacing else ''}: {payload['error']}")
                self._warn("Couldn't replace profile" if replacing else "Couldn't import",
                           f'Couldn\'t replace "{old_name}".' if replacing else f'Couldn\'t import "{name}".',
                           means=payload["error"],  # bepinex_share's own words (what was kept, what to do)
                           tryit="Check your internet connection and try again in a minute.",
                           details=payload["error"])
                self.status_text.set_status_text(
                    f"Couldn't replace \"{old_name}\" - it's unchanged." if replacing else f"Couldn't import \"{name}\".", "error")
                return
            res = payload["ok"]
            log(f"import ({mode}): done -> {res['slug']}{f' replacing {old_slug}' if replacing else ''}: "
                f"{len(res['installed'])} of {res['listed']} installed, "
                f"{len(res['fallbacks'])} fallbacks, {len(res['failed'])} failed, {len(res['restored'])} files restored")
            self._settings.update({"last_load_order": res["slug"]})
            self._reload_load_order_picker(select_slug=res["slug"])
            self._apply_current_load_order_to_panes()
            kind = "warn" if res["failed"] or res["errors"] or res.get("replace_skipped") else "info"
            self.status_text.set_status_text(
                (f"Replaced \"{old_name}\" with \"{name}\"" if replacing else f"Imported \"{name}\"")
                + f": {len(res['installed'])} of {res['listed']} mods, {len(res['restored'])} settings files"
                + (f", {len(res['failed'])} failed" if res["failed"] else "") + ".", kind)
            QMessageBox.information(self, "Import finished", share.describe_import(res))
            self._start_update_check()

        self._run_job(f"import-replace-{old_slug}" if mode == "replace" else f"import-{name}", job, done,
                      progress=lambda text: self.status_text.set_status_text(text),
                      downloads=[self.ts_game.framework_package] + [m["full_name"] for m in profile["mods"]])

    def _import_code(self) -> None:
        """Import from code...: a profile code (r2modman / TMM / VOLT) ->
        downloaded from Thunderstore as a job into the cache, then the same
        import as a picked file (_import_profile)."""
        if self.game_dir is None or self._busy is not None:
            return
        text, ok = QInputDialog.getText(self, "Import from code", IMPORT_CODE_PROMPT)
        if not ok or not text.strip():
            log("import from code: cancelled")
            return
        try:
            code = share.parse_code(text)
        except ValueError as err:
            self._warn("Couldn't import", "That doesn't look like a profile code.",
                       means="A code looks like 01a0eadb-df03-ee4a-20f7-eccc823a5a5d. Nothing was downloaded.",
                       tryit="Copy the whole code again and paste it in.",
                       details=str(err))
            return
        log(f"import from code {code}: downloading")
        self._set_busy(f"Downloading profile {code} from Thunderstore...")

        def job(report):
            return share.fetch_code_profile(self.app_root, code, self.app_version)

        def done(payload: dict) -> None:
            self._set_busy(None)
            if "error" in payload:
                self._warn("Couldn't import", f"Couldn't download the profile for code {code}.",
                           means="The code may be mistyped or too old, or Thunderstore couldn't be reached. "
                                 "Nothing was changed.",
                           tryit="Check the code and your internet connection, then try again in a minute.",
                           details=payload["error"])
                self.status_text.set_status_text(f"Couldn't fetch profile {code}.", "error")
                return
            profile = payload["ok"]
            self.status_text.set_status_text(f"Fetched profile {code}: {len(profile['mods'])} mods.")
            self._import_profile(profile, profile["source"])

        self._run_job(f"fetch-code-{code}", job, done)

    def _import_local_mod(self) -> None:
        """Import... > Local mod (.zip)... (THUNDERSTORE.md §8b): the dialog
        picks and validates a package zip (a bad one is reported there, a
        package already in this load order refused there), then
        _install_package runs bepinex_load_orders.import_local_mod as its
        job - appended to Active and the baseline like any install (never
        an unsaved change, so no discard prompt), dependencies from
        Thunderstore, the update check re-run."""
        if self.current_load_order is None or self._busy is not None:
            return
        slug = self.current_load_order
        log(f"import local mod: dialog opened for {slug} ({self.load_order_picker.currentText()!r})")

        def blocked(ref: ts.PackageRef) -> str | None:
            if ref.full_name == self._framework or ref.full_name == self.ts_game.framework_package:
                return f"{ref.full_name} is this profile's mod loader - it's always installed."
            if ref.full_name in self._entries:
                return f"{ref.full_name} is already in this profile (v{self._entries[ref.full_name]['version']})."
            return None

        dialog = LocalModDialog(lo.inspect_local_package, blocked, self._share_dir(), parent=self)
        if not dialog.exec() or dialog.payload is None:
            log("import local mod: cancelled")
            return
        path, ref = dialog.payload["path"], dialog.payload["ref"]
        self._remember_share_dir(path)
        log(f"import local mod: {path} -> {slug} as {ref.key} (owner from {dialog.payload['info']['owner_source']})")
        self._install_package(ref, local_zip=path)

    def _export_code(self) -> None:
        """Export as code...: confirm (every time - it's an upload to a
        public service), then the on-screen lists as a .r2z uploaded to
        Thunderstore's profile service as a job; the code shown in a small
        dialog with Copy."""
        if self.current_load_order is None or self._busy is not None:
            return
        slug, lo_name = self.current_load_order, self.load_order_picker.currentText()
        if not self._confirm("Export as code", EXPORT_CODE_CONFIRM.format(name=lo_name), confirm_label="Upload"):
            log(f"export {slug} as code: cancelled at the upload confirm")
            return
        active, inactive = self._save_lists()
        log(f"export {slug} ({lo_name!r}) as code: {len(active)} active, {len(inactive)} inactive"
            f"{' (unsaved edits included)' if self._dirty() else ''}")
        self._set_busy(f'Uploading "{lo_name}" to Thunderstore...')

        def job(report):
            return share.export_code(self.app_root, slug, self.ts_game, active=active, inactive=inactive,
                                     app_version=self.app_version)

        def done(payload: dict) -> None:
            self._set_busy(None)
            if "error" in payload:
                self._warn("Export failed", f'Couldn\'t upload "{lo_name}".',
                           means="Your profile is unchanged; no code was made.",
                           tryit="Check your internet connection and try again in a minute, or use Export to file instead.",
                           details=payload["error"])
                self.status_text.set_status_text(f"Couldn't upload \"{lo_name}\".", "error")
                return
            res = payload["ok"]
            self.status_text.set_status_text(
                f"Uploaded \"{lo_name}\": {res['mods']} mods, {res['config_files']} settings files - code {res['code']}.")
            self._show_code(lo_name, res["code"])

        self._run_job(f"export-code-{slug}", job, done)

    def _show_code(self, lo_name: str, code: str) -> None:
        """The code dialog: the code in a read-only field, Copy, Close."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Profile code")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(GAP)
        text = _label(f'"{lo_name}" is uploaded. Anyone can import it with this code - in VOLT (Import... > Import from code...), '
                      "r2modman or Thunderstore Mod Manager:")
        text.setWordWrap(True)
        layout.addWidget(text)
        field = QLineEdit(code)
        field.setObjectName("profileCode")  # the recessed well, mono (theme.py, design step 3.4)
        field.setReadOnly(True)
        field.selectAll()
        layout.addWidget(field)
        buttons = QDialogButtonBox()
        copy = buttons.addButton("Copy code", QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: self._copy_text(code, f"Copied the profile code {code}."))
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.setMinimumWidth(460)
        # adjustSize() would take the wrapped label's height at its narrower
        # hint width, leaving empty space once the 460 minimum widens it:
        # size the height for the width the dialog actually gets.
        dialog.ensurePolished()
        width = max(460, dialog.sizeHint().width())
        dialog.resize(width, dialog.heightForWidth(width))
        log(f"code dialog shown for {lo_name!r}: {code}")
        dialog.exec()
        dialog.deleteLater()

    def _show_dependency_strings(self) -> None:
        """Export... > Dependency strings... (THUNDERSTORE.md §8d): the
        framework + every switched-on Active mod (the on-screen list, unsaved
        edits included) as `"Team-Package-Version",` lines in a read-only
        box with Copy - the code dialog's shape. Local imports are left out
        and counted."""
        if self.current_load_order is None or self._manifest is None:
            return
        lo_name = self.load_order_picker.currentText()
        res = share.dependency_strings(self._manifest, self._save_lists()[0])
        lines, n = res["lines"], len(res["lines"])
        log(f"dependency strings for {self.current_load_order} ({lo_name!r}): {n} listed, {res['local']} local omitted, "
            f"{res['invalid']} without a version omitted{' (unsaved edits included)' if self._dirty() else ''}")
        intro = (f"{n} dependency string{'' if n == 1 else 's'} for \"{lo_name}\" (the mod loader and every switched-on "
                 "Active mod) - paste them into the \"dependencies\" list of a modpack's manifest.json.")
        if res["local"]:
            intro += f" {res['local']} local mod{'' if res['local'] == 1 else 's'} omitted (not on Thunderstore)."
        if res["invalid"]:
            intro += f" {res['invalid']} mod{'' if res['invalid'] == 1 else 's'} without a valid version omitted."
        dialog = QDialog(self)
        dialog.setWindowTitle("Dependency strings")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(GAP)
        label = _label(intro)
        label.setTextFormat(Qt.TextFormat.PlainText)  # the load order's name is data
        label.setWordWrap(True)
        layout.addWidget(label)
        text = "\n".join(lines)
        if lines:
            field = QPlainTextEdit(text)
            field.setReadOnly(True)
            field.setProperty("mono", True)  # theme.py: the config window's raw box, mono 12px
            field.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            layout.addWidget(field)
        else:
            layout.addWidget(_label("Nothing to list.", muted=True))
        buttons = QDialogButtonBox()
        copy = buttons.addButton("Copy", QDialogButtonBox.ButtonRole.ActionRole)
        copy.setEnabled(bool(lines))
        copy.clicked.connect(lambda: self._copy_text(text, f"Copied {n} dependency string{'' if n == 1 else 's'}."))
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.setMinimumWidth(460)
        dialog.exec()
        dialog.deleteLater()

    def _save_lists(self) -> tuple[list[dict], list[str]]:
        """save_load_order's arguments from the panes: Active as
        {full_name, enabled} in order (the framework left out), Inactive as
        full_names."""
        active = [{"full_name": n, "enabled": self._toggles.get(n, True)} for n in self._active_ids()]
        return active, self.inactive_list.mod_ids()

    def _save_load_order(self) -> None:
        """Save (the one button): materializes the Active list + toggles into
        the load order's tree. Renames only - no network - so it runs here."""
        if self.current_load_order is None:
            return
        active, inactive = self._save_lists()
        off = sum(1 for a in active if not a["enabled"])
        counts = f"{len(active)} active ({off} off), {len(inactive)} inactive"
        try:
            manifest = lo.save_load_order(self.app_root, self.current_load_order, active, inactive)
        except (OSError, ValueError) as err:
            log(f"save load order {self.current_load_order} ({counts}) failed: {err!r}")
            self._warn("Save failed", "Couldn't save your changes.",
                       means="Your changes are still on screen, but the profile on disk may be only partly updated.",
                       tryit=f"Close {self.game_name} (and anything using the profile's files), then press Save again.",
                       details=f"Profile folder: {self._load_order_dir()}\n{err}")
            return
        log(f"saved load order {self.current_load_order} ({counts})")
        self._take_manifest(manifest)
        self._reset_baseline()
        self.status_text.set_status_text(f"Saved: {counts}.")

    # ---- rows ----
    def _display_name(self, mod_id: str) -> str:
        e = self._entries.get(mod_id)
        return (e["display_name"] or e["name"]) if e else mod_id

    def _mod_matches(self, mod_id: str, q: str) -> bool:
        e = self._entries.get(mod_id)
        if not e:
            return q.lower() in mod_id.lower()
        q = q.lower()
        return any(q in (e.get(k) or "").lower() for k in ("display_name", "name", "namespace", "full_name"))

    def _has_update(self, mod_id: str) -> bool:
        e, m = self._entries.get(mod_id), self._meta.get(mod_id)
        return bool(e and m and e.get("online_source", True) and ts.is_newer(m.get("latest_version") or "", e["version"]))

    def _updatable(self) -> list[str]:
        return [n for n in self._entries if self._has_update(n)]

    def _meta_text(self, mod_id: str) -> tuple[str, bool]:
        """Line 2 of a row: "v<version> · <state>", and whether it's warn-colored."""
        e = self._entries[mod_id]
        v = f"v{e['version']}" if e.get("version") else "v?"
        if mod_id in self._updating:
            return f"{v}  ·  updating...", False
        if not e.get("online_source", True):
            return f"{v}  ·  local mod", False
        if self._has_update(mod_id):
            return f"{v}  ·  update available", True
        if mod_id == self._framework:
            return f"{v}  ·  mod loader, always on", False
        m = self._meta.get(mod_id)
        when = ago(m.get("date_updated")) if m else None
        if when:
            return f"{v}  ·  Updated {when}", False
        if self._checking:
            return f"{v}  ·  checking...", False
        if mod_id in self._check_errors:
            return f"{v}  ·  update check failed", False
        return v, False

    def _row_info(self, mod_id: str) -> RowInfo | None:
        e = self._entries.get(mod_id)
        if e is None:
            return None
        meta, warn = self._meta_text(mod_id)
        pinned = mod_id == self._framework
        in_active = mod_id in self._toggles
        update = self._has_update(mod_id) and (pinned or in_active)
        errors = [t for sev, t in self._issues.get(mod_id, ()) if sev == "error"]
        m = self._meta.get(mod_id) or {}
        return RowInfo(
            name=self._display_name(mod_id),
            meta=meta,
            meta_warn=warn,
            pinned=pinned,
            toggle=None if pinned or not in_active else self._toggles[mod_id],
            update=update,
            warn=self._has_update(mod_id),
            error="\n".join(errors) or None,
            busy=mod_id in self._updating,
            update_tip=f"Update {self._display_name(mod_id)} to {m.get('latest_version')}" if update else "",
            disabled=in_active and not pinned and not self._toggles[mod_id],
            deprecated=bool(m.get("deprecated")),
            icon=self._row_icon(mod_id),
            files_missing=mod_id in self._missing_files,
        )

    def _row_tooltip(self, mod_id: str) -> str | None:
        e = self._entries.get(mod_id)
        if e is None:
            return None
        lines = [e["full_name"]]
        lines += [t for _sev, t in self._issues.get(mod_id, ())]
        if mod_id in self._check_errors:
            lines.append(f"Update check failed: {self._check_errors[mod_id]}")
        return "\n".join(lines)

    def _controls_enabled(self) -> bool:
        return self._busy is None and self.game_dir is not None

    def _on_selection_changed(self, source, other) -> None:
        mod_id = source.selected_mod_id()
        if mod_id is not None:
            log(f"selected {mod_id} in {self._pane_name(source)}")
            other.clearSelection()
            self._show_details(mod_id)
        elif other.selected_mod_id() is None:
            log(f"selection cleared ({self._pane_name(source)})")
            self._show_details(None)

    def _show_details(self, mod_id: str | None) -> None:
        e = self._entries.get(mod_id) if mod_id else None
        if e is None:
            self.details_panel.show_entry(None)
            return
        m = self._meta.get(mod_id) or {}
        self.details_panel.show_entry(
            e, latest=m.get("latest_version"), date_updated=m.get("date_updated"),
            icon=self._mod_icon(e), framework=mod_id == self._framework, deprecated=bool(m.get("deprecated")),
        )

    def _mod_folder(self, entry: dict) -> Path | None:
        """BepInEx/plugins/<Team-Package>/ when the mod put files there."""
        root = self._load_order_dir()
        if root is None:
            return None
        prefix = f"BepInEx/plugins/{entry['full_name']}/"
        if any(f.startswith(prefix) for f in entry.get("files", ())):
            return root / "BepInEx" / "plugins" / entry["full_name"]
        return None

    def _mod_icon(self, entry: dict) -> Path | None:
        folder = self._mod_folder(entry)
        return folder / "icon.png" if folder else None

    def _move(self, index, source, target) -> None:
        """Double-click: the row moves to the other pane (the framework row
        stays). Into Active: appended at the end, toggle on; into Inactive:
        in name order."""
        row = index.row() if index.isValid() else -1
        mod_id = source.mod_model.id_at(row)
        if mod_id is None:
            log(f"double-click in {self._pane_name(source)}: no mod at row {row}, nothing moved")
            return
        if mod_id == self._framework:
            log(f"double-click on the framework row ({mod_id}): pinned, nothing moved")
            return
        source.mod_model.remove_row(row)
        target_ids = target.mod_ids()
        if target is self.inactive_list:
            key = (natural_key(self._display_name(mod_id)), mod_id)
            pos = next((i for i, other in enumerate(target_ids)
                        if (natural_key(self._display_name(other)), other) > key), len(target_ids))
            self._toggles.pop(mod_id, None)
        else:
            pos = len(target_ids)
            self._toggles[mod_id] = True
        target.mod_model.insert_id(pos, mod_id)
        log(f"moved {mod_id} (row {row}) {self._pane_name(source)} -> {self._pane_name(target)} row {pos}; "
            f"now {len(self._active_ids())} active, {len(self.inactive_list.mod_ids())} inactive")
        target.setCurrentIndex(target.mod_model.index(pos))

    def _toggle(self, mod_id: str, on: bool) -> None:
        """A row's toggle: an unsaved edit like a move (history, dirty, undo)."""
        if mod_id not in self._toggles or mod_id == self._framework:
            return
        self._history.append(self._snapshot())
        self._toggles[mod_id] = on
        log(f"toggle: {mod_id} {'on' if on else 'off'} (unsaved)")
        self._apply_load_order_state()

    def _set_all_toggles(self, on: bool) -> None:
        """Enable all / Disable all (THUNDERSTORE.md §8a): every Active mod's
        toggle at once - the framework has none, so it's never switched off.
        One unsaved edit, one undo step; nothing to change = no edit at all."""
        what = "enable all" if on else "disable all"
        changing = [n for n, v in self._toggles.items() if v != on]
        if self.current_load_order is None or self._busy is not None or not changing:
            log(f"{what}: ignored ({'no load order' if self.current_load_order is None else 'busy' if self._busy else 'nothing to change'})")
            return
        self._history.append(self._snapshot())
        for n in changing:
            self._toggles[n] = on
        log(f"{what}: {len(changing)} mod{'s' if len(changing) != 1 else ''} switched {'on' if on else 'off'} (unsaved)")
        self._apply_load_order_state()

    # ---- dependency presence (THUNDERSTORE.md §3) ----
    def _update_issues(self) -> None:
        """An active, enabled mod whose declared dependency (the framework
        aside) isn't installed = error; installed but inactive / toggled off
        = warning (bepinex_load_orders.dependency_issues). Fills _issue_list,
        the rows' _issues and the "⚠ N · ✕ M" button."""
        deps: dict[str, list[dict]] = {}
        for issue in lo.dependency_issues(self._entries, self._active_ids(), self._toggles,
                                          self.ts_game.framework_package):
            deps.setdefault(issue["mod_id"], []).append(issue)
        # 0.6.27: each mod's "files" warning first, then its dependency issues, in list order (Active, then Inactive)
        self._issue_list = [
            issue for mod_id in self._active_ids() + self.inactive_list.mod_ids()
            for issue in ([lo.files_issue(mod_id, *self._missing_files[mod_id])] if mod_id in self._missing_files else [])
            + deps.get(mod_id, [])
        ]
        issues: dict[str, list[tuple[str, str]]] = {}
        for issue in self._issue_list:
            issues.setdefault(issue["mod_id"], []).append((issue["severity"], issue["text"]))
        self._issues = issues
        warnings = sum(1 for i in self._issue_list if i["severity"] == "warning")
        errors = sum(1 for i in self._issue_list if i["severity"] == "error")
        self.issues_label.setText(_issue_count_html(warnings, errors))
        self.issues_button.setVisible(bool(warnings or errors))

    def _show_issues(self) -> None:
        """The "⚠ N · ✕ M" button: the Warnings and errors window
        (screens/bepinex_issues_window.py) over the live issue list; its
        Install buttons run _install_missing."""
        log(f"issues window opened: {len(self._issue_list)} issues")
        BepInExIssuesWindow(
            lambda: self._issue_list, self._display_name, self._install_missing,
            is_busy=lambda: self._busy is not None, parent=self,
        ).exec()
        log("issues window closed")

    def _install_missing(self, packages: list[str], on_done=None, parent: QWidget | None = None) -> None:
        """Installs the missing dependencies `packages` (full_names, each at
        Thunderstore's latest, with their own dependencies - install_mod's
        policy) into the open load order as ONE job, one package after the
        other; a package that fails is reported, the rest still install.
        The shared path behind the issues window's Install / Install all
        missing and the row menu's Install missing dependencies. Refreshes
        the panes like Add mod; `on_done({"ok": {"installed", "failed":
        [(package, message)]}} | {"error": text})` runs last."""
        packages = list(dict.fromkeys(packages))
        if self.current_load_order is None or self._busy is not None or not packages:
            why = "no load order" if self.current_load_order is None else "busy" if self._busy else "nothing to install"
            log(f"install missing {packages}: ignored ({why})")
            if on_done is not None:
                on_done({"error": "The screen is busy." if self._busy else "Nothing to install."})
            return
        n = len(packages)
        self._set_busy(f"Installing {n} missing required mod{'s' if n != 1 else ''}...")
        slug = self.current_load_order

        def job(report):
            lo.plan_downloads(self.app_root, slug, self.ts_game, (ts.PackageRef.parse(n) for n in packages),
                              self.app_version)  # the bar's total up front (0.6.26)
            done, failed = [], []
            for i, name in enumerate(packages, 1):
                report(f"Installing {name} ({i} of {n})...")
                try:
                    res = lo.install_mod(self.app_root, slug, self.ts_game, ts.PackageRef.parse(name), self.app_version)
                except (ts.ThunderstoreError, PackageError, OSError, ValueError) as err:
                    log(f"install missing: {name} failed: {err!r}")
                    failed.append((name, str(err)))
                    continue
                done += [e["full_name"] for e in res["installed"]]
                failed += [(p.get("package", "?"), p.get("message", "")) for p in res["problems"]]
            return {"installed": done, "failed": failed}

        def finished(payload: dict) -> None:
            self._set_busy(None)
            if "error" in payload:
                self._refresh_after_change()
                self._warn("Couldn't install required mods", "Couldn't install the missing required mods.",
                           means="Some mods need other mods to work, and VOLT couldn't download those.",
                           tryit="Check your internet connection and try again in a minute.",
                           details=payload["error"], parent=parent)
                self.status_text.set_status_text("Couldn't install the missing required mods.", "error")
            else:
                res = payload["ok"]
                log(f"install missing: installed {res['installed']}, {len(res['failed'])} failed")
                self._absorb_installed(res["installed"])
                if res["failed"]:
                    self._warn("Some required mods couldn't be installed",
                               f"{len(res['failed'])} required mod(s) couldn't be installed.",
                               means="The mods that need them may not work until they're installed.",
                               tryit="Try again in a minute. If one keeps failing, it may have been removed from "
                                     "Thunderstore.",
                               details="\n".join(f"{name}: {msg}" for name, msg in res["failed"]), parent=parent)
                got = len(res["installed"])
                self.status_text.set_status_text(
                    f"Installed {got} missing required mod{'s' if got != 1 else ''}."
                    + (f" {len(res['failed'])} failed." if res["failed"] else ""),
                    "warn" if res["failed"] else "info",
                )
                self._start_update_check(max_age_s=RECHECK_AFTER_S)
            if on_done is not None:
                on_done(payload)

        self._run_job("install-missing", job, finished, progress=lambda text: self.status_text.set_status_text(text),
                      downloads=packages)

    # ---- update checking (THUNDERSTORE.md §3) ----
    def _start_update_check(self, force: bool = False, max_age_s: float | None = None) -> None:
        """Runs check_updates over the open load order off the GUI thread.
        `force` (Rescan): every package. Otherwise only the packages whose
        last check failed or is older than `max_age_s` seconds (the check
        after a change: RECHECK_AFTER_S) - or, without it, wasn't this
        session (opening the manager / a load order); skipped when that's
        none."""
        m = self._manifest
        if m is None or self._checking:
            return
        names = [n for n, e in self._entries.items() if e.get("online_source", True)]
        if not names:
            return
        if not force and "*" not in self._check_errors:  # "*": the last pass failed as a whole - redo it all
            cutoff = _SESSION_START if max_age_s is None else (
                datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).isoformat(timespec="seconds").replace("+00:00", "Z")
            stale = [n for n in names if n in self._check_errors or self._meta.get(n, {}).get("checked_at", "") < cutoff]
            if not stale:
                log(f"update check: every package checked since {cutoff}, skipped")
                return
            names = stale
        self._checking = True
        self._check_errors = {}
        log(f"update check: started for {len(names)} packages{' (all)' if force else ''}")
        self._apply_load_order_state()
        manifest, app_version, only = m, self.app_version, set(names)

        def job(report):
            return lo.check_updates(manifest, app_version, only=only)

        self._run_job("update-check", job, self._on_check_done)

    def _on_check_done(self, payload: dict) -> None:
        self._checking = False
        if "error" in payload:
            log(f"update check failed: {payload['error']}")
            self._check_errors = {"*": payload["error"]}
            self._apply_load_order_state()
            return
        result: dict = payload["ok"]
        now = _now()
        for name, r in result.items():
            if "error" in r:
                self._check_errors[name] = r["error"]
                continue
            self._meta[name] = {"latest_version": r["latest_version"], "date_updated": r["date_updated"],
                                "deprecated": r.get("deprecated", False), "checked_at": now}
        ts.write_meta_cache(self.app_root, self._meta)
        count = len(self._updatable())
        log(f"update check done: {count} updates, {len(self._check_errors)} failed")
        if self._busy is None:
            if count:
                self.status_text.set_status_text(
                    f"{count} mod{'s have' if count != 1 else ' has'} an update available.", "warn")
            elif self._check_errors:
                sep = ". " if self._check_error() == ts.RATE_LIMITED_MSG else ": "
                self.status_text.set_status_text(
                    f"Couldn't check {len(self._check_errors)} mod(s) for updates{sep}{self._check_error()}", "warn")
            else:
                self.status_text.set_status_text("All mods are up to date.")
        self._apply_load_order_state()
        if self.active_list.selected_mod_id() or self.inactive_list.selected_mod_id():
            self._show_details(self.active_list.selected_mod_id() or self.inactive_list.selected_mod_id())

    def _refresh_after_change(self, manifest: dict | None = None) -> None:
        """After a mod was added / removed / updated on disk: re-read the
        manifest, keep the on-screen order / toggles, and re-check."""
        self._take_manifest(manifest if manifest is not None else self._read_manifest())
        ids, toggles = self._snapshot()
        self._show_lists(ids, toggles)
        self._apply_load_order_state()

    def _update_one(self, mod_id: str) -> None:
        """The row's update button / the menu's Update: re-downloads and
        installs that one mod's latest version (update_mod), as a job."""
        if self._busy is not None or mod_id not in self._entries or mod_id in self._updating:
            return
        name = self._display_name(mod_id)
        self._updating.add(mod_id)
        self._set_busy(f"Updating {name}...")
        slug = self.current_load_order

        def job(report):
            return lo.update_mod(self.app_root, slug, self.ts_game, mod_id, self.app_version)

        def done(payload: dict) -> None:
            self._updating.discard(mod_id)
            self._set_busy(None)
            if "error" in payload:
                self._warn(f"Couldn't update {name}", f"Couldn't update {name}.",
                           means="It stays at the version you had.",
                           tryit="Check your internet connection and try again in a minute.",
                           details=payload["error"])
                self.status_text.set_status_text(f"Couldn't update {name}.", "error")
                return
            res = payload["ok"]
            self._refresh_after_change(res["manifest"])
            if res["updated"]:
                self.status_text.set_status_text(f"Updated {name} to {res['entry']['version']}.")
            else:
                self.status_text.set_status_text(f"{name} is already at its latest version.")
            self._start_update_check(max_age_s=RECHECK_AFTER_S)

        self._run_job(f"update-{mod_id}", job, done, downloads=[mod_id])

    def _reinstall(self, mod_id: str) -> None:
        """The row menu's Reinstall (0.6.27): the mod extracted again at its
        installed version (lo.reinstall_mod - the cached zip, else a download
        through the bar), putting back files deleted outside VOLT; its on/off
        state, place in the list and settings files stay. Not confirmed (it
        removes nothing). A local .zip mod whose zip VOLT no longer has gets
        the friendly error box instead."""
        if self._busy is not None or mod_id not in self._entries or mod_id in self._updating:
            return
        entry = self._entries[mod_id]
        name = self._display_name(mod_id)
        source = lo.reinstall_source(self.app_root, entry)
        log(f"reinstall {mod_id} {entry.get('version')}: asked, source={source}, files missing={self._missing_files.get(mod_id)}")
        if source is None:
            self._warn(f"Couldn't reinstall {name}", f"VOLT can't reinstall {name}.",
                       means=f"{name} was added from a .zip file on your computer, and VOLT's own copy of that "
                             "file is gone, so there is nothing to reinstall it from.",
                       tryit=f"Use Import > Local mod (.zip) to add the same file again, or Uninstall {name} "
                             "and get it from Thunderstore.",
                       details=f"{mod_id} {entry.get('version')}: no cached zip in {ts.package_cache_dir(self.app_root)}")
            return
        self._updating.add(mod_id)
        self._set_busy(f"Reinstalling {name}...")
        slug = self.current_load_order

        def job(report):
            return lo.reinstall_mod(self.app_root, slug, self.ts_game, mod_id, self.app_version)

        def done(payload: dict) -> None:
            self._updating.discard(mod_id)
            self._set_busy(None)
            if "error" in payload:
                self._refresh_after_change()  # whatever landed on disk shows (the marker follows the tree)
                self._warn(f"Couldn't reinstall {name}", f"Couldn't reinstall {name}.",
                           means="Its files that were already missing are still missing.",
                           tryit="Check your internet connection and try again in a minute. If it keeps failing, "
                                 f"Uninstall {name} and add it again.",
                           details=payload["error"])
                self.status_text.set_status_text(f"Couldn't reinstall {name}.", "error")
                return
            res = payload["ok"]
            log(f"reinstall {mod_id}: from the {res['source']}, {res['missing_before']} files were missing, "
                f"{res['missing_after']} still missing")
            self._refresh_after_change(res["manifest"])
            self.status_text.set_status_text(f"Reinstalled {name}.")

        self._run_job(f"reinstall-{mod_id}", job, done, downloads=[mod_id])

    def _update_all_clicked(self) -> None:
        if self._checking or self._busy is not None:
            return
        if not self._updatable():
            self._start_update_check(max_age_s=RECHECK_AFTER_S)  # the "Retry" state: the failed (and stale) packages
            return
        self._update_all()

    def _update_all(self) -> None:
        names = self._updatable()
        labels = {n: self._display_name(n) for n in names}  # read here, not on the job's thread
        self._updating |= set(names)
        self._set_busy(f"Updating {len(names)} mods...")
        slug = self.current_load_order

        def job(report):
            done, failed = [], []
            for n in names:
                report(f"Updating {labels[n]} ({len(done) + len(failed) + 1} of {len(names)})...")
                try:
                    lo.update_mod(self.app_root, slug, self.ts_game, n, self.app_version)
                    done.append(n)
                except (ts.ThunderstoreError, PackageError, OSError, ValueError) as err:
                    log(f"update all: {n} failed: {err!r}")
                    failed.append((n, str(err)))
            return {"done": done, "failed": failed}

        def finished(payload: dict) -> None:
            self._updating -= set(names)
            self._set_busy(None)
            if "error" in payload:
                self._refresh_after_change()
                self._warn("Update all failed", "Couldn't update your mods.",
                           means="Mods that weren't updated stay at the version you had.",
                           tryit="Check your internet connection and try again in a minute.",
                           details=payload["error"])
                return
            res = payload["ok"]
            self._refresh_after_change()
            if res["failed"]:
                self._warn("Some updates failed", f"{len(res['failed'])} of {len(names)} mods couldn't be updated.",
                           means="Those stay at the version you had; the others were updated.",
                           tryit="Check your internet connection and try again in a minute.",
                           details="\n".join(f"{self._display_name(n)}: {msg}" for n, msg in res["failed"]))
            self.status_text.set_status_text(
                f"Updated {len(res['done'])} of {len(names)} mods." if res["failed"] else f"Updated {len(res['done'])} mods.",
                "warn" if res["failed"] else "info",
            )
            self._start_update_check(max_age_s=RECHECK_AFTER_S)

        self._run_job("update-all", job, finished, progress=lambda text: self.status_text.set_status_text(text),
                      downloads=names)

    # ---- add / uninstall ----
    def _add_mod(self) -> None:
        if self.current_load_order is None or self._busy is not None:
            return
        text, ok = QInputDialog.getText(self, "Add mod", ADD_MOD_PROMPT.format(example=self.game.EXAMPLE_PACKAGE))
        if not ok or not text.strip():
            log("add mod: cancelled")
            return
        try:
            ref = parse_package_input(text)
        except ValueError:
            self._warn("Add mod", "VOLT didn't recognise that as a mod name.",
                       means="Add mod needs the mod's name as Thunderstore writes it (Author-ModName) or the address "
                             "of its thunderstore.io page.",
                       tryit=f"Copy the address from the mod's Thunderstore page, or use Browse Mods to search instead. "
                             f"Example name: {self.game.EXAMPLE_PACKAGE}.",
                       details=f"Typed: {text.strip()!r}")
            return
        if ref.full_name in self._entries:
            self._notice("Add mod", f"{ref.full_name} is already in this profile.")
            return
        self._install_package(ref)

    def _browse_mods(self) -> None:
        """Browse Mods...: the in-app Thunderstore browser over the open load
        order (screens/bepinex_browse_window.py); its Install is
        _install_package, so the panes refresh behind the window."""
        if self.current_load_order is None or self._busy is not None:
            return
        name = self.load_order_picker.currentText()
        log(f"browse mods window opened for {self.current_load_order} ({name!r})")
        window = BepInExBrowseWindow(
            self.ts_game, self.game_name, name,
            installed=lambda: self._entries, framework=self._framework, run_job=self._run_job,
            install=self._install_package, switch_version=self._switch_version, is_busy=lambda: self._busy is not None,
            app_version=self.app_version, parent=self,
        )
        self._extra_dl_bars = list(window.download_bars)  # the same bar state as the footer's (0.6.26)
        try:
            window.exec()
        finally:
            self._extra_dl_bars = []
        log("browse mods window closed")

    def _switch_version(self, full_name: str, version: str | None, on_done=None, parent: QWidget | None = None) -> None:
        """The browser's Versions tab (and its Update-to-latest button):
        re-installs an installed mod at `version` (None = the latest) in
        place - update_mod's path: files diffed, config kept, on-disk state
        and list position preserved - as a job; the panes refresh like an
        update. `on_done(payload)` runs last, on the GUI thread."""
        if self._busy is not None or full_name not in self._entries or full_name in self._updating:
            log(f"switch {full_name} -> {version or 'latest'}: ignored ({'busy' if self._busy else 'not installed / in flight'})")
            if on_done is not None:
                on_done({"error": "The screen is busy." if self._busy else f"{full_name} isn't in this profile."})
            return
        name = self._display_name(full_name)
        self._updating.add(full_name)
        self._set_busy(f"{'Updating' if version is None else 'Switching'} {name}{'' if version is None else f' to {version}'}...")
        slug = self.current_load_order

        def job(report):
            return lo.update_mod(self.app_root, slug, self.ts_game, full_name, self.app_version, version=version)

        def done(payload: dict) -> None:
            self._updating.discard(full_name)
            self._set_busy(None)
            if "error" in payload:
                self._warn(f"Couldn't {'update' if version is None else 'switch'} {name}",
                           f"Couldn't {'update' if version is None else 'switch'} {name}.",
                           means="It stays at the version you had.",
                           tryit="Check your internet connection and try again in a minute.",
                           details=payload["error"], parent=parent)
                self.status_text.set_status_text(f"Couldn't {'update' if version is None else 'switch'} {name}.", "error")
            else:
                res = payload["ok"]
                self._refresh_after_change(res["manifest"])
                if res["updated"]:
                    self.status_text.set_status_text(f"{name} is now {res['entry']['version']}.")
                else:
                    self.status_text.set_status_text(f"{name} already is {res['entry']['version']}.")
                self._start_update_check(max_age_s=RECHECK_AFTER_S)
            if on_done is not None:
                on_done(payload)

        self._run_job(f"switch-{full_name}", job, done, downloads=[full_name])

    def _install_package(self, ref: ts.PackageRef, on_done=None, parent: QWidget | None = None, *,
                         local_zip: Path | None = None) -> None:
        """Installs `ref` (its pinned version, else the latest) plus its
        dependencies into the open load order as a job (install_mod), then
        refreshes the panes - Add mod... and the browser's Install alike.
        With `local_zip` the job is import_local_mod (Import local mod: that
        zip instead of a download, same everything else).
        `on_done(payload)` runs last, on the GUI thread, when given;
        warnings are parented to `parent` (the browser) when given."""
        if self.current_load_order is None or self._busy is not None:
            log(f"install {ref.full_name}: ignored ({'no load order' if self.current_load_order is None else 'busy'})")
            if on_done is not None:
                on_done({"error": "The screen is busy." if self._busy else "No profile is open."})
            return
        source = f" from {local_zip.name}" if local_zip else ""
        self._set_busy(f"Installing {ref.full_name}{source}...")
        slug = self.current_load_order

        def job(report):
            if local_zip is not None:
                return lo.import_local_mod(self.app_root, slug, self.ts_game, local_zip, self.app_version)
            lo.plan_downloads(self.app_root, slug, self.ts_game, [ref], self.app_version)  # the bar's total up front (0.6.26)
            return lo.install_mod(self.app_root, slug, self.ts_game, ref, self.app_version)

        def done(payload: dict) -> None:
            self._set_busy(None)
            if "error" in payload:
                self._refresh_after_change()  # a dependency may have landed before the target failed
                self._warn(f"Couldn't install {ref.full_name}", f"Couldn't install {ref.full_name}{source}.",
                           means="It wasn't added to your profile.",
                           tryit="Check your internet connection and the mod's name, then try again in a minute."
                                 if local_zip is None else "Make sure the file is a Thunderstore mod .zip, then try again.",
                           details=payload["error"], parent=parent)
                self.status_text.set_status_text(f"Couldn't install {ref.full_name}.", "error")
                if on_done is not None:
                    on_done(payload)
                return
            res = payload["ok"]
            new = [e["full_name"] for e in res["installed"]]
            log(f"add mod: installed {new}{source}, {len(res['problems'])} problems")
            self._absorb_installed(new)
            if res["problems"]:
                self._warn("Some required mods couldn't be installed",
                           f"{ref.full_name} was installed, but {len(res['problems'])} mod(s) it needs couldn't be.",
                           means="It may not work until they're installed.",
                           tryit="Press the warnings button above Save (⚠ / ✕), then Install all missing.",
                           details="\n".join(f"{p.get('package', '?')}: {p.get('message', '')}" for p in res["problems"]),
                           parent=parent)
            extra = len(new) - 1
            if not new:  # already installed (install_mod's guard) - nothing changed
                self.status_text.set_status_text(f"{ref.full_name} is already in this profile.")
            else:
                self.status_text.set_status_text(
                    f"Installed {ref.full_name}{source}"
                    + (f" and {extra} required mod{'s' if extra != 1 else ''}" if extra > 0 else "") + ".")
            self._start_update_check(max_age_s=RECHECK_AFTER_S)
            if on_done is not None:
                on_done(payload)

        self._run_job(f"install-{ref.full_name}", job, done,
                      downloads=[] if local_zip is not None else [ref.full_name])  # a local zip: only its dependencies download

    def _absorb_installed(self, new: list[str]) -> None:
        """After an install landed on disk: the new mods (active + enabled
        already) join the on-screen Active list and the baseline alike, so
        an install is never itself an unsaved change; the manifest is
        re-read, the state re-applied."""
        ids, toggles = self._snapshot()
        self._take_manifest(self._read_manifest())
        self._show_lists(ids + [n for n in new if n not in ids], {**toggles, **{n: True for n in new}})
        base_ids, base_toggles = self._baseline
        self._baseline = (base_ids + [n for n in new if n not in base_ids], {**base_toggles, **{n: True for n in new}})
        self._apply_load_order_state()

    def _uninstall(self, mod_id: str) -> None:
        if mod_id == self._framework or mod_id not in self._entries or self._busy is not None:
            return
        name = self._display_name(mod_id)
        if not self._confirm(
            "Uninstall mod",
            f"Remove {name} ({mod_id}) from this profile? Its files are deleted from the profile (its settings "
            "files are kept). Other profiles aren't affected.",
            confirm_label="Uninstall",
        ):
            log(f"uninstall {mod_id}: cancelled")
            return
        try:
            manifest = lo.remove_mod(self.app_root, self.current_load_order, mod_id)
        except (OSError, ValueError) as err:
            self._warn(f"Couldn't uninstall {name}", f"Couldn't uninstall {name}.",
                       means="Some of its files may still be in the profile.",
                       tryit=f"Close {self.game_name}, then try again.",
                       details=str(err))
            return
        ids, toggles = self._snapshot()
        self._take_manifest(manifest)
        self._show_lists([n for n in ids if n != mod_id], toggles)
        base_ids, base_toggles = self._baseline
        self._baseline = ([n for n in base_ids if n != mod_id], {k: v for k, v in base_toggles.items() if k != mod_id})
        self._history = [([n for n in i if n != mod_id], {k: v for k, v in t.items() if k != mod_id}) for i, t in self._history]
        self._apply_load_order_state()
        self.status_text.set_status_text(f"Uninstalled {name}.")
        self._start_update_check(max_age_s=RECHECK_AFTER_S)

    # ---- Run: the BepInEx launch through Steam (THUNDERSTORE.md §2; bepinex_launch.py) ----
    def _run(self, modded: bool = True) -> None:
        """Modded: starts the game through Steam with the open load order's
        BepInEx injected (bepinex_launch.start), then watches for it to exit
        and tidies the game folder. Never saves: with unsaved changes it
        asks first, and the game gets the load order as it was last saved.
        `modded=False` is the Vanilla button: a plain Steam launch, nothing
        copied, no confirms, no load order needed (slug / tree / manifest
        may all be None - only the modded branches read them), the same
        recovery / already-running checks and the same busy lock while the
        game runs."""
        if self._busy is not None or self._launch is not None:
            log("run: ignored, the screen is busy")
            return
        reason = bl.platform_error()
        if reason:
            log(f"run: preflight failed (platform): {reason}")
            self._warn("Run failed", f"VOLT can't start {self.game_name} on this system.",
                       means="Starting games from VOLT only works on Windows for now.",
                       tryit="Start the game from Steam instead.",
                       details=reason)
            return
        exe = self.game.find_game_exe(self.game_dir)
        if exe is None:
            log(f"run: preflight failed (exe): game_dir={self.game_dir}, looked for {', '.join(self.game.GAME_EXES)}")
            self._warn("Run failed", f"VOLT couldn't find {self.game_name}'s .exe.",
                       means="The game folder in Settings may be wrong, or the game was moved or uninstalled.",
                       tryit="Open Settings and use Autodetect or Browse to set the game folder again.",
                       details=f"Game folder: {self.game_dir or '(not set)'}\nLooked for: {', '.join(self.game.GAME_EXES)}")
            return
        slug, name = self.current_load_order, self.load_order_picker.currentText()
        if modded and (slug is None or self._manifest is None):
            log("run: preflight failed (load order): none open")
            self._warn("Run failed", "No profile is open.",
                       means="Modded starts the game with a profile's mods, so it needs one.",
                       tryit="Pick a profile at the top, or make one with New profile. Vanilla works without one.")
            return
        tree = self._load_order_dir()
        if modded:
            missing = bl.framework_missing(tree, self._manifest)
            if missing:
                log(f"run: preflight failed (framework): tree={tree}, missing {missing}")
                self._warn(
                    "Run failed",
                    "This profile's mod loader is incomplete.",
                    means="Some files of the mod loader (BepInEx) are missing from the profile, so mods can't load.",
                    tryit="Press Rescan. If that doesn't help, make a new profile (or delete and recreate this one).",
                    details=f"Profile folder: {tree}\nMissing: {', '.join(missing)}",
                )
                return
        steam_exe = paths.find_steam_exe()
        if steam_exe is None:
            looked = ", ".join(str(p) for p in paths.steam_root_candidates()) or "(nowhere)"
            log(f"run: preflight failed (steam.exe): looked in {looked}")
            self._warn(
                "Run failed",
                "VOLT couldn't find Steam.",
                means=f"{self.game_name} is started through Steam, so Steam has to be installed.",
                tryit="Make sure Steam is installed, start it once, then try again.",
                details=f"Looked for steam.exe in: {looked}",
            )
            return
        launch_args = self._settings.get().get("launch_args") or ""
        try:
            extra_args = bl.parse_launch_args(launch_args)
        except ValueError as err:
            log(f"run: preflight failed (launch arguments {launch_args!r}): {err}")
            self._warn("Run failed", "The launch options in Settings can't be read.",
                       means="Something in Settings > Launch is mistyped (often a missing closing quote).",
                       tryit="Open Settings > Launch, fix or clear the text, then try again.",
                       details=f"Launch arguments: {launch_args!r}\n{err}")
            return
        mods_with_errors = [m for m, v in self._issues.items() if any(sev == "error" for sev, _ in v)]
        log(f"run: preflight ok ({'modded' if modded else 'vanilla'}): game_dir={self.game_dir}, exe={exe.name}, "
            f"load order={slug} ({name!r}), tree={tree}, steam={steam_exe}, dirty={'yes' if self._dirty() else 'no'}, "
            f"mods with dependency errors={len(mods_with_errors)}, launch args={extra_args}")
        if modded and self._dirty() and not self._confirm(
            "Unsaved profile changes",
            f"You have unsaved changes. Modded doesn't save them: {self.game_name} starts with the profile "
            "as it was last saved.",
            confirm_label="Run without saving",
        ):
            log("run: cancelled at the unsaved-changes prompt (nothing saved)")
            return
        n = len(mods_with_errors)
        if modded and n and not self._confirm(
            "Missing required mods",
            f"{n} active mod{'s need' if n != 1 else ' needs'} other mods that aren't installed, so the game will skip "
            f"{'them' if n != 1 else 'it'}. Start anyway?",
            confirm_label="Start anyway",
        ):
            log("run: cancelled at the missing-dependencies prompt")
            return
        if modded and (Path(self.game_dir) / BEPINEX_DIR).is_dir() and not self._confirm(
            "Another mod loader in the game folder",
            f"{self.game_name}'s folder already has its own copy of the mod loader (BepInEx), probably from another mod "
            "manager. VOLT uses this profile's copy instead and leaves that one alone, so the mods installed there "
            "won't load. Continue?",
            confirm_label="Continue",
        ):
            log("run: cancelled at the foreign-BepInEx prompt")
            return
        try:
            bl.start(
                self.app_root, self.game_dir, tree, self._manifest, appid=self.game.STEAM_APPID, exe_name=exe.name,
                steam_exe=steam_exe, load_order=slug or "", load_order_name=name, modded=modded, extra_args=extra_args,
            )
        except (bl.LaunchError, OSError) as err:
            log(f"run: failed: {err!r}")
            self._warn("Run failed", f"Couldn't start {self.game_name}.",
                       means=str(err),
                       tryit=f"Make sure Steam is running and {self.game_name} isn't already open, then try again.",
                       details=str(err))
            return
        self._begin_watch(exe_name=exe.name, load_order_name=name, modded=modded, phase="starting")

    def _recover_launch(self) -> None:
        """On open: a launch record left by a previous VOLT session means the
        game is still running (re-attach: busy + watch until it exits, then
        clean up) or the last run's loader files are still in the game
        folder (clean up now, say so)."""
        try:
            rec = bl.recover(self.app_root)
        except OSError as err:
            log(f"run: recovery failed: {err!r}")
            self._warn("Couldn't check the last run", "VOLT couldn't check how the last game session ended.",
                       means="Some mod loader files may still be in the game folder. They don't affect normal "
                             "Steam launches.",
                       tryit="Press Modded or Vanilla; VOLT tidies the game folder before every start.",
                       details=str(err))
            return
        state = rec["state"]
        if state == "none":
            return
        record = rec["record"]
        name = record.get("load_order_name") or record.get("load_order") or "?"
        if state == "running":
            self._begin_watch(exe_name=record["exe_name"], load_order_name=name, modded=bool(record.get("modded", True)),
                              phase="running")
            return
        if state == "incomplete":
            self._warn_cleanup_failed(rec["result"])
            self.status_text.set_status_text(
                f"Mod loader files from the last run are still in the {self.game_name} folder.", "warn")
        else:
            self.status_text.set_status_text(
                f"Removed leftover mod loader files from the {self.game_name} folder (the last run wasn't tidied up).", "warn")

    def _begin_watch(self, *, exe_name: str, load_order_name: str, modded: bool, phase: str) -> None:
        """Busy until the game (by image name) has been seen and is gone."""
        self._launch = {"exe_name": exe_name, "load_order_name": load_order_name, "modded": modded,
                        "phase": phase, "started": time.monotonic()}
        what = f'profile "{load_order_name}"' if modded else "vanilla, no mods"
        if phase == "running":
            self._set_busy(f"{self.game_name} is running ({what}), started by a previous VOLT session."
                           + (" VOLT tidies the game folder when it exits." if modded else ""))
        else:
            self._set_busy(f"Launching {self.game_name} through Steam ({what})...")
        self._poll_timer.start(bl.POLL_INTERVAL_S * 1000)

    def _poll_launch(self) -> None:
        """One tick of the watch: tasklist off the GUI thread, then _on_poll."""
        if self._launch is None:
            return
        exe_name = self._launch["exe_name"]
        self._run_job("launch-poll", lambda report: bl.running_pids(exe_name), self._on_poll)

    def _on_poll(self, payload: dict) -> None:
        st = self._launch
        if st is None:
            return
        pids = payload.get("ok") or set()
        elapsed = time.monotonic() - st["started"]
        what = f'profile "{st["load_order_name"]}"' if st["modded"] else "vanilla, no mods"
        if st["phase"] == "starting":
            if pids:
                st["phase"], st["started"] = "running", time.monotonic()
                log(f"run: {st['exe_name']} running (pids {sorted(pids)}) after {elapsed:.0f}s")
                if st["modded"] and not self._settings.get()["has_launched"]:
                    self._remember({"has_launched": True})  # the checklist's step 4 (0.6.23)
                self._set_busy(f"{self.game_name} is running ({what})."
                               + (" VOLT tidies the game folder when it exits." if st["modded"] else ""))
            elif elapsed >= bl.START_TIMEOUT_S:
                log(f"run: {st['exe_name']} didn't start within {bl.START_TIMEOUT_S}s")
                self._end_watch(f"{self.game_name} didn't start within {bl.START_TIMEOUT_S // 60} minutes", "warn")
                return
        elif not pids:
            log(f"run: {st['exe_name']} exited after {_duration(elapsed)}")
            self._end_watch(f"{self.game_name} exited after {_duration(elapsed)}", "info")
            return
        self._poll_timer.start(bl.POLL_INTERVAL_S * 1000)

    def _end_watch(self, what: str, kind: str) -> None:
        """The game is gone (or never came): a modded run's cleanup (as a
        job - a locked file is retried for a few seconds), then the status."""
        st, self._launch = self._launch, None
        self._poll_timer.stop()
        if not st["modded"]:
            self._set_busy(None)
            self.status_text.set_status_text(f"{what}.", kind)
            return
        self._set_busy(f"{what} - tidying the game folder...")

        def done(payload: dict) -> None:
            self._set_busy(None)
            result = payload.get("ok") or {"removed": [], "restored": [], "failed": [("?", payload.get("error", ""))]}
            if result["failed"]:
                self._warn_cleanup_failed(result)
                self.status_text.set_status_text(
                    f"{what} - some mod loader files are still in the {self.game_name} folder.", "warn")
            else:
                self.status_text.set_status_text(f"{what} - game folder restored.", kind)

        self._run_job("launch-cleanup", lambda report: bl.cleanup(self.app_root), done)

    def _warn_cleanup_failed(self, result: dict) -> None:
        names = ", ".join(n for n, _ in result["failed"])
        first = result["failed"][0][1]
        self._warn(
            "Couldn't restore the game folder",
            f"Some mod loader files are still in the {self.game_name} folder.",
            means="They're harmless: normal Steam launches ignore them. VOLT tries again next time.",
            tryit=f"Close {self.game_name} fully, then open this manager again or press Modded or Vanilla.",
            details=f"Files: {names}\nFirst error: {first}",
        )

    # ---- right-click menu ----
    def _show_mod_menu(self, pane, pos) -> None:
        index = pane.indexAt(pos)
        mod_id = pane.mod_model.id_at(index.row()) if index.isValid() else None
        e = self._entries.get(mod_id) if mod_id else None
        if e is None:
            return
        pane.setCurrentIndex(index)
        folder = self._mod_folder(e)
        page = package_page_url(self.ts_game.community, e)
        site = e.get("website_url") or ""
        is_fw = mod_id == self._framework
        idle = self._busy is None
        log(f"context menu: {mod_id} in {self._pane_name(pane)} (folder={folder}, update={self._has_update(mod_id)}, "
            f"missing deps={lo.mod_missing_dependencies(self._entries, mod_id, self.ts_game.framework_package)}, "
            f"files missing={self._missing_files.get(mod_id)})")
        menu = QMenu(pane)

        def item(label: str, enabled, fn) -> None:
            action = menu.addAction(label)
            action.setEnabled(bool(enabled))
            action.triggered.connect(lambda: fn())

        item("Open folder", folder, lambda: self._open_folder(folder))
        item("Open on Thunderstore", True, lambda: self._open_url(page))
        item("Open website", site, lambda: self._open_url(site))
        item("Copy Thunderstore name", True, lambda: self._copy_text(e["full_name"], f'Copied "{e["full_name"]}".'))
        item("Edit config...", True, lambda: self._edit_config(e.get("name") or ""))
        menu.addSeparator()
        missing = lo.mod_missing_dependencies(self._entries, mod_id, self.ts_game.framework_package)
        if missing:  # only a mod with missing dependencies gets the entry (Active or Inactive alike)
            item(f"Install missing required mods ({len(missing)})", idle, lambda: self._install_missing(missing))
        item("Update", idle and self._has_update(mod_id) and mod_id not in self._updating, lambda: self._update_one(mod_id))
        item("Reinstall", idle and mod_id not in self._updating, lambda: self._reinstall(mod_id))  # 0.6.27
        item("Uninstall...", idle and not is_fw, lambda: self._uninstall(mod_id))
        menu.exec(pane.viewport().mapToGlobal(pos))
        menu.deleteLater()

    # ---- header row 1: .paths-bar ----
    def _build_paths_bar(self) -> QWidget:
        bar = QWidget()
        column = QVBoxLayout(bar)
        column.setContentsMargins(BAR_SIDE, 8, BAR_SIDE, 0)
        column.setSpacing(6)  # .paths-bar gap between its two rows
        row = QHBoxLayout()
        row.setSpacing(GAP)
        self.games_button = _games_button()  # far left: back to game select
        row.addWidget(self.games_button)
        row.addSpacing(16 - GAP)
        self.settings_button = _button("Settings")
        row.addWidget(self.settings_button)
        row.addSpacing(16 - GAP)
        row.addWidget(_label("Paths:", muted=True))
        self.game_link = _button("Game", variant="link")
        self.load_order_link = _button("Profile", variant="link")
        self.bepinex_link = _button("BepInEx", variant="link")
        row.addWidget(self.game_link)
        row.addWidget(_label("/", muted=True))
        row.addWidget(self.load_order_link)
        row.addWidget(_label("/", muted=True))
        row.addWidget(self.bepinex_link)
        row.addSpacing(16 - GAP)
        self.storefront_tag = QLabel("Steam")
        self.storefront_tag.setProperty("role", "tag")
        row.addWidget(self.storefront_tag)
        self.version_label = _label(f"V. O. L. T. v{self.app_version}", muted=True)
        self.version_label.setProperty("role", "wordmark")  # theme.py: the Circuit wordmark
        row.addWidget(self.version_label)
        row.addStretch(1)
        self.help_button = _button("Help")
        row.addWidget(self.help_button)
        column.addLayout(row)
        self.path_line = _PathLine()
        self.path_line.setContentsMargins(2, 0, 0, 0)  # padding-left: 2px
        column.addWidget(self.path_line)
        return bar

    # ---- header row 2: .loadorder-bar ----
    def _build_load_order_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("loadOrderBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(BAR_SIDE, 6, BAR_SIDE, 6)
        row.setSpacing(GAP)
        row.addWidget(_label("Profile", muted=True))
        self.load_order_picker = QComboBox()
        self.load_order_picker.setMinimumWidth(220)
        self.load_order_picker.setEnabled(False)
        self.load_order_picker.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.load_order_picker.customContextMenuRequested.connect(self._show_load_order_menu)
        row.addWidget(self.load_order_picker)
        self.new_button = _button("New profile...")
        self.copy_button = _button("Copy to new...")
        row.addWidget(self.new_button)
        row.addWidget(self.copy_button)
        self.dirty_label = QLabel("Unsaved changes")
        self.dirty_label.setProperty("role", "dirty")
        self.dirty_label.setVisible(False)
        row.addWidget(self.dirty_label)
        self.undo_button = _button("↺")
        self.undo_button.setObjectName("undoButton")
        self.undo_button.setFixedSize(24, 24)
        self.undo_button.setToolTip("Undo the most recent change to the active list (Ctrl+Z)")
        self.undo_button.setVisible(False)
        row.addWidget(self.undo_button)
        row.addStretch(1)
        self.update_all_button = _button("Update all")
        row.addWidget(self.update_all_button)
        return bar

    # ---- the get-started checklist band (0.6.23): between the profile bar and the content row ----
    def _build_checklist(self) -> QWidget:
        """A new band (PLAN.md §10 (f)): the content row's side margins, 8px
        above (the content row keeps its own 8px under it); hidden until
        _apply_first_run says otherwise. Steps: Settings, New profile,
        Browse Mods (the existing actions), then the informational Run."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(BAR_SIDE, 8, BAR_SIDE, 0)
        self.checklist = ChecklistStrip(
            self.game_name,
            (lambda: self._show_settings(), lambda: self._new_load_order(), lambda: self._browse_mods(), None),
            lambda: self._hide_checklist(),
        )
        row.addWidget(self.checklist)
        box.setVisible(False)
        self._checklist_box = box
        return box

    # ---- .content-row ----
    def _build_content_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(BAR_SIDE, 8, BAR_SIDE, 8)
        row.setSpacing(GAP)
        self._grid = QWidget()
        grid = QHBoxLayout(self._grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(GAP)
        inactive_pane, self.inactive_search, self.inactive_eye, self.inactive_list = self._build_pane("Inactive")
        active_pane, self.active_search, self.active_eye, self.active_list = self._build_pane("Active", draggable=True)
        self.details_panel = ThunderstoreDetailsPanel()
        for column, stretch, min_width in zip((self.details_panel, inactive_pane, active_pane), GRID_STRETCH, GRID_MIN_WIDTH):
            column.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            column.setMinimumWidth(min_width)
            grid.addWidget(column, stretch)
        row.addWidget(self._grid, 1)
        self._no_game = self._build_no_game_message()
        row.addWidget(self._no_game, 1)
        actions = self._build_actions_column()
        row.addWidget(actions)
        # Circuit panel shadows (painters.py: a cached 9-slice this screen
        # paints behind the four panels; the lists themselves are untouched)
        # and the dot grid inside the empty details pane.
        painters.install_shadows(self, (self.details_panel, self.inactive_list, self.active_list, actions, self.checklist))
        panel = self.details_panel
        painters.install_empty_grid(panel, lambda: panel.details_empty.isVisibleTo(panel), over_default=True)
        return row

    def _build_no_game_message(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setSpacing(GAP)
        layout.addStretch(1)
        self._no_game_text = _label("", muted=True)
        for label in (_label(f"Couldn't find {self.game_name}"), self._no_game_text):
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
        locate = QPushButton(f"Locate {self.game_name} folder...")
        locate.setProperty("variant", "primary")
        locate.clicked.connect(lambda: self._browse_path("game"))
        retry = QPushButton("Try autodetect again")
        retry.clicked.connect(lambda: self._autodetect_paths())
        buttons = QHBoxLayout()
        buttons.setSpacing(GAP)
        buttons.addStretch(1)
        buttons.addWidget(locate)
        buttons.addWidget(retry)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return box

    def _build_pane(self, title: str, *, draggable: bool = False):
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title_label = painters.TerminalLabel(title)  # a Circuit terminal label (role pane-title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        search = QLineEdit()
        search.setPlaceholderText(f"Search {title.lower()}...")
        eye = search.addAction(_eye_icon(False), QLineEdit.ActionPosition.TrailingPosition)
        eye.setToolTip(_EYE_TOOLTIP[False])
        eye.setEnabled(False)
        search.setEnabled(False)
        layout.addWidget(search)

        def on_search_changed() -> None:
            s = mod_list.search
            title_label.setText(f"{title} [{s.count_text()}]")
            eye.setIcon(_eye_icon(s.dim))
            eye.setToolTip(_EYE_TOOLTIP[s.dim])
            no_matches.setVisible(s.no_matches)
            if drag_hint is not None:
                drag_hint.setVisible(s.hiding)

        mod_list = BepInExModListView(
            self._display_name,
            draggable=draggable,
            name=title,
            matches=self._mod_matches,
            on_search_changed=on_search_changed,
            tooltip=self._row_tooltip,
            row_info=self._row_info,
            controls_enabled=self._controls_enabled,
            on_update=self._update_one,
            on_toggle=self._toggle,
        )
        mod_list.setEnabled(False)
        mod_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        mod_list.customContextMenuRequested.connect(lambda pos: self._show_mod_menu(mod_list, pos))
        # the dot grid inside the list while it shows no rows (painters.py)
        painters.install_empty_grid(mod_list.viewport(), lambda: painters.list_is_empty(mod_list))
        if draggable:  # the Active list: the copper load-order rail (painters.py; DESIGN.md §3.2)
            painters.install_rail(mod_list)
        list_cell = QGridLayout()
        list_cell.setContentsMargins(0, 0, 0, 0)
        list_cell.addWidget(mod_list, 0, 0)
        no_matches = _label("No matches", muted=True)
        no_matches.setContentsMargins(12, 12, 12, 12)
        no_matches.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        no_matches.setVisible(False)
        list_cell.addWidget(no_matches, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        if draggable:
            # the Active pane: the first-run card over its empty dot grid while no
            # profile is open (PLAN.md §10 (c), 0.6.23) - centred in the list's
            # cell, above it; the list underneath is untouched
            self._active_pane = pane
            self.first_run_card = card = EmptyStateCard(
                fr.fill(fr.PROFILE_CARD, self.game_name), lambda: self._new_load_order(),
                lambda: self._show_action_menu(card.import_button, self._import_menu_items()),
            )
            card.follow(mod_list)
            card.setVisible(False)
            list_cell.addWidget(card, 0, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(list_cell, 1)
        drag_hint = None
        if draggable:
            drag_hint = _label("Clear the search to drag mods.", muted=True)
            drag_hint.setVisible(False)
            layout.addWidget(drag_hint)
        search.textChanged.connect(lambda text: mod_list.set_search(query=text))
        eye.triggered.connect(lambda: mod_list.set_search(dim=not mod_list.search.dim))
        on_search_changed()
        return pane, search, eye, mod_list

    # ---- .actions-column ----
    def _build_actions_column(self) -> QFrame:
        column = _panel()
        column.setFixedWidth(ACTIONS_WIDTH)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)
        self.import_button = _button("Import...")
        self.import_button.setToolTip(IMPORT_TOOLTIP)
        self.export_button = _button("Export...")
        self.export_button.setToolTip(EXPORT_TOOLTIP)
        # Enable all / Disable all: a row of links right under Export...
        # (THUNDERSTORE.md §8a, placed by the user 2026-09-28)
        self.enable_all_button = _button("Enable all", variant="link")
        self.enable_all_button.setToolTip(ENABLE_ALL_TOOLTIP)
        self.disable_all_button = _button("Disable all", variant="link")
        self.disable_all_button.setToolTip(DISABLE_ALL_TOOLTIP)
        bulk_row = QHBoxLayout()
        bulk_row.setSpacing(GAP)
        bulk_row.addWidget(self.enable_all_button)
        bulk_row.addWidget(self.disable_all_button)
        self.rescan_button = _button("Rescan")
        self.rescan_button.setToolTip("Read the open profile from disk again and check for updates.")
        # Config: the Edit config window, no search query (placed by the user
        # 2026-09-30, between Rescan and the Get mods label)
        self.config_button = _button("Config")
        self.config_button.setToolTip("Change the settings of the open profile's mods.")
        self.add_mod_button = _button("Add mod...", variant="accent-outline")
        self.add_mod_button.setToolTip("Install a mod (and any mods it needs) by its Thunderstore name or address.")
        self.browse_button = _button("Browse Mods...", variant="accent-outline")
        self.browse_button.setToolTip(BROWSE_TOOLTIP.format(game=self.game_name))
        # Group labels (step 3.1, DESIGN.md §15 decision 6: LOAD ORDER over
        # Import, GET MODS over Add mod, LAUNCH over Save): copper terminal
        # labels with a side rule, inserted into the existing groups - no
        # button moves, the stretch pays for their height.
        self.group_labels = [painters.TerminalLabel(t, rule="side") for t in ("Profile", "Get mods", "Launch")]
        for label in self.group_labels:
            # the mockup's .glabel is a 12px box with margin-bottom -2px (6px
            # to its button under the groups' 8px spacing); a layout can't
            # overlap, so a 10px box: the same 6px, text / rule 1px higher
            # (caps only - nothing hangs below the baseline to clip)
            label.setFixedHeight(10)
        top = self._group(self.import_button, self.export_button)
        top.insertWidget(0, self.group_labels[0])
        top.addLayout(bulk_row)
        top.addWidget(self.rescan_button)
        top.addWidget(self.config_button)
        top.addWidget(self.group_labels[1])
        for button in (self.add_mod_button, self.browse_button):
            top.addWidget(button)
        layout.addLayout(top)
        layout.addStretch(1)
        self.issues_button = _button("", variant="issue-count")
        self.issues_button.setToolTip("Show warnings and errors")
        self.issues_button.setEnabled(True)
        self.issues_label = QLabel(_issue_count_html(0, 0))
        self.issues_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.issues_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner = QHBoxLayout(self.issues_button)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(self.issues_label)
        self.issues_button.setVisible(False)
        layout.addLayout(self._group(self.issues_button))
        self.save_button = _button("Save", variant="primary")
        # Vanilla sits right above Modded (the button that was "Run"), placed
        # by the user 2026-09-28; both carry the play triangle, same icon.
        self.vanilla_button = _button("Vanilla", variant="vanilla")
        self.run_button = _button("Modded", variant="primary")
        for button, tip in ((self.vanilla_button, VANILLA_TOOLTIP), (self.run_button, MODDED_TOOLTIP)):
            button.setToolTip(tip.format(game=self.game_name))
            # the triangle in the button's label color (dark ink on the primary Modded)
            button.setIcon(_play_icon(theme.INK, theme.DISABLED_FILL_TEXT) if button is self.run_button else _play_icon())
            button.setIconSize(QSize(PLAY_ICON_PX, PLAY_ICON_PX))
        launch = self._group(self.save_button, self.vanilla_button, self.run_button)
        launch.insertWidget(0, self.group_labels[2])
        layout.addLayout(launch)
        return column

    @staticmethod
    def _group(*buttons: QPushButton) -> QVBoxLayout:
        group = QVBoxLayout()
        group.setSpacing(8)
        for button in buttons:
            group.addWidget(button)
        return group

    # ---- footer ----
    def _build_footer(self) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        divider = QFrame()
        divider.setObjectName("actionDivider")
        divider.setFixedHeight(1)
        divider_row = QHBoxLayout()
        divider_row.setContentsMargins(BAR_SIDE, 0, BAR_SIDE, 0)
        divider_row.addWidget(divider)
        column.addLayout(divider_row)
        footer = QFrame()
        footer.setObjectName("statusBar")
        row = QHBoxLayout(footer)
        row.setContentsMargins(BAR_SIDE, 4, BAR_SIDE, 14)
        row.setSpacing(0)
        prompt = QLabel(">")  # the copper terminal prompt (design step 3.4)
        prompt.setProperty("role", "status-prompt")
        row.addWidget(prompt)
        self.status_text = _StatusText()
        row.addWidget(self.status_text, 1)
        # 0.6.25: docked right, as RimWorld's SteamCMD row; hidden until a job downloads (_render_dl)
        self.download_bar = PackageDownloadBar()
        self.download_bar.setVisible(False)
        row.addWidget(self.download_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(footer)
        return box


