"""The Thunderstore/BepInEx game manager screen (THUNDERSTORE.md §3), built
for Valheim (VALHEIM.md PLAN item 3, stage 3b) against the signed-off design
https://claude.ai/artifact/KeNe4nnwPVmCgfxrpbXBCZ - and game-agnostic: the
screen takes the game's own module (valheim.py's shape: NAME, SLUG, GAME,
autodetect, is_game_root, find_game_exe) plus that game's Help entries, so
the next BepInEx game (Lethal Company, R.E.P.O.) is screens/<game>_main_screen.py
wrapping this class with its module, exactly as screens/valheim_main_screen.py
does. Same shell as RimWorld's screen (screens/rimworld_main_screen.py, whose
small shared pieces - the notice, the status text, the eye icon, the button
helpers - are imported from it rather than copied); the data layer is
bepinex_load_orders.py (a load order IS a BepInEx tree; its manifest says
what's installed), thunderstore.py (metadata, downloads, the shared package
cache and the per-package metadata cache) and bepinex_install.py.

Top to bottom (the mockup):
  paths bar      Settings | Paths: Game / Load order / BepInEx | storefront tag | version ... Help
                 <game folder>  /  <the open load order's BepInEx folder>   (muted, 12px)
  load-order bar Load order [picker] New.. Copy.. [Unsaved changes ↺] ... [⚠ N updates · Update all]
  content row    [details | inactive | active] (1.2 : 1 : 1) + actions column (150px)
  footer         divider; [status text]

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
  - Rows are two lines (screens/bepinex_mod_list.py): name, then version ·
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
    added / removed / updated and on Rescan; the load-order bar's "Update
    all" button carries the live count (warn-outline while > 0; "Up to
    date" / "Checking for updates..." / "Update check failed · Retry"
    otherwise). What it learns per package (latest version, date_updated)
    is kept in <APP-ROOT>/cache/package-meta.json, so rows show a
    last-updated date before this run's check finishes.
  - Paths: Game (the install), Load order (load-orders/<slug>/) and BepInEx
    (its BepInEx/ subfolder); the latter two follow the picker and are
    disabled with no load order open.
  - "Add mod..." (a Team-Package name or a thunderstore.io package URL)
    installs one package plus its dependencies into the open load order
    (install_mod) - the stand-in for the mod browser (stage 3f) until it
    exists, so a load order can hold more than the framework. "Browse
    Mods...", Import... / Export... (stage 3e) and Run (stage 3c, the
    Doorstop launch) are on the screen as designed but disabled until
    their stage lands - never a stub that half-works.
  - Row right-click: Open folder (BepInEx/plugins/<Team-Package>), Open on
    Thunderstore, Open website, Copy package name, Edit config..., Update
    (when one is available), Uninstall... (remove_mod, confirmed; not the
    framework).
  - Edit config... (THUNDERSTORE.md §7; screens/bepinex_config_window.py):
    the open load order's BepInEx/config/ files, browsed and edited in a
    split-pane window. Scoped to the whole load order, not a mod (no
    reliable file-to-package mapping exists), so it opens from the
    load-order picker's right-click menu and from every row's menu alike -
    the row entry just pre-fills the search with the package name when
    that matches a file.

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
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from volt_py import bepinex_load_orders as lo, theme, thunderstore as ts
from volt_py.app_root import resolve_app_root
from volt_py.applog import clip, init_log, log
from volt_py.bepinex_install import PackageError
from volt_py.mods import natural_key
from volt_py.paths import norm
from volt_py.screens.bepinex_config_window import BepInExConfigWindow
from volt_py.screens.bepinex_mod_list import BepInExModListView, RowInfo
from volt_py.screens.bepinex_settings_window import BepInExSettingsWindow
from volt_py.screens.help_window import HelpWindow
from volt_py.screens.rimworld_main_screen import (
    ACTIONS_WIDTH,
    BAR_SIDE,
    GAP,
    GRID_MIN_WIDTH,
    GRID_STRETCH,
    NOTICE_BOTTOM,
    SOURCE_LABEL,
    _EYE_TOOLTIP,
    _Notice,
    _StatusText,
    _button,
    _eye_icon,
    _issue_count_html,
    _label,
    _panel,
)
from volt_py.settings import SettingsStore

STAGE_TOOLTIP = {
    "import": "Import comes in a later update (load-order sharing).",
    "export": "Export comes in a later update (load-order sharing).",
    "browse": "The in-app mod browser comes in a later update. Add mod... installs a package by name meanwhile.",
    "run": "Run comes in a later update (the BepInEx launch). Until then, start the game from Steam.",
}
ADD_MOD_PROMPT = (
    "Thunderstore package to install, with its dependencies, into the open load order.\n"
    "A package name (Team-Package, e.g. ValheimModding-Jotunn) or its thunderstore.io page URL:"
)
# thunderstore.io/c/<community>/p/<Team>/<Package>/ (the site) or /package/<Team>/<Package>/ (older links).
_PACKAGE_URL = re.compile(r"thunderstore\.io/(?:c/[^/]+/p|package)/([A-Za-z0-9_]+)/([A-Za-z0-9_]+)/?", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# Packages checked at or after this moment count as "checked this session": a
# switch back to a load order doesn't re-ask Thunderstore for them (ISO
# timestamps compare as text).
_SESSION_START = _now()


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
    """The mockup's .details: the package icon (BepInEx/plugins/<Team-Package>/
    icon.png, when installed), Name / Author / Version ("2.30.2 installed
    (2.31.0 available)" in --warn when newer) / Last updated / Website (a
    link) and the description. details_panel.py's DetailsPanel is
    RimWorld-shaped (authors, path, package id, About/Preview.png), so this
    is its own class with the same frame and layout."""

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
        self.details_icon = QLabel()
        self.details_icon.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        body_layout.addWidget(self.details_icon)

        form = QFormLayout()  # .details-grid
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(4)
        self.details_fields: dict[str, QLabel] = {}
        for key, title, rich in (
            ("name", "Name", False),
            ("author", "Author", False),
            ("version", "Version", True),
            ("updated", "Last updated", False),
            ("website", "Website", True),
        ):
            value = self.details_fields[key] = _details_text(rich)
            form.addRow(_label(title, muted=True), value)
        body_layout.addLayout(form)

        self.details_description = _details_text()
        self.details_description.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.details_description)
        scroll.viewport().setAutoFillBackground(False)
        self.details_description.setAutoFillBackground(False)
        body_layout.addWidget(scroll, 1)
        layout.addWidget(body, 1)
        self._icon_source = None

    def show_entry(self, entry: dict | None, *, latest: str | None = None, date_updated=None,
                   icon: Path | None = None, framework: bool = False) -> None:
        shown = entry is not None
        self.details_empty.setVisible(not shown)
        self.details_body.setVisible(shown)
        if not shown:
            return
        f = self.details_fields
        f["name"].setText(entry["display_name"] or entry["name"])
        f["author"].setText(entry["namespace"])
        ver = f"{entry['version'] or '?'} installed"
        if latest and ts.is_newer(latest, entry["version"]):
            ver += f' &nbsp; <span style="color:{theme.WARN}">({latest} available)</span>'
        elif framework:
            ver += f' &nbsp; <span style="color:{theme.MUTED}">(framework, required)</span>'
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
        from PySide6.QtCore import QSize

        # A 256x256 Thunderstore icon: at most 35% of the panel's height, as
        # DetailsPanel's preview (.details-preview max-height: 35%).
        box = QSize(self.width() - 20, int(self.height() * 0.35))
        if pixmap.width() > box.width() or pixmap.height() > box.height():
            pixmap = pixmap.scaled(box, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.details_icon.setPixmap(pixmap)
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
    `game`: that game's module (valheim.py's shape); `help_entries`: its
    Help window entries."""

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
        layout.addLayout(self._build_content_row(), 1)
        layout.addWidget(self._build_footer())

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
        self._issues: dict[str, list[tuple[str, str]]] = {}  # full_name -> [(severity, text)]

        self.app_root = resolve_app_root(game.SLUG)
        self._log_path: Path | None = init_log(self.app_root)
        log(f"app root: {self.app_root} ({self.game_name})")
        self._settings = SettingsStore(self.app_root)
        self._meta: dict[str, dict] = ts.read_meta_cache(self.app_root)
        log(f"package metadata cache: {len(self._meta)} packages")
        self._connect_signals()
        self._resolve_paths()
        self._reload_load_order_picker()
        self._apply_paths()
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
                f'"{picked}" doesn\'t look like a {self.game_name} install folder '
                f"(expected {self.game.DATA_DIR} or the game executable inside it).",
                parent,
            )
            return
        try:
            self._settings.update({"game_dir": picked, "game_source": "manual"})
        except OSError as err:
            self._warn("Couldn't save settings", str(err), parent)
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
                self._warn("Couldn't save settings", str(err), parent)
                return
        self._reload_for_paths()
        if found["game"]:
            self._notice("Autodetect", f"Found {self.game_name} (Steam) at {found['game']['game_dir']}.")
        else:
            self._warn("Autodetect", f"Autodetect didn't find a {self.game_name} install. Please locate it manually.", parent)

    def _show_settings(self) -> None:
        log("settings window opened")
        BepInExSettingsWindow(
            self.game_name, self._paths_state, self._browse_path, self._autodetect_paths, self._warn,
            self._log_path, self,
        ).exec()
        log("settings window closed")

    def _show_help(self) -> None:
        log("help window opened")
        HelpWindow(self._help_entries, parent=self).exec()
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
        self.copy_button.setEnabled(ready and has_lo)
        self.rescan_button.setEnabled(ready and has_lo)
        self.add_mod_button.setEnabled(ready and has_lo)
        self.save_button.setEnabled(ready and has_lo)
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

    def _apply_update_button(self) -> None:
        """The load-order bar's permanent update element (THUNDERSTORE.md §3):
        the live count + Update all while there are updates, else its state."""
        button = self.update_all_button
        count = len(self._updatable())
        if self._checking:
            text, enabled, variant, tip = "Checking for updates...", False, "", ""
        elif count:
            text, enabled, variant = f"⚠ {count} update{'s' if count != 1 else ''} · Update all", self._busy is None, "warn-outline"
            tip = "Download and install the latest version of every mod in this load order that has one."
        elif self._check_errors and self.current_load_order is not None:
            first = next(iter(self._check_errors.values()))
            text, enabled, variant, tip = "Update check failed · Retry", self._busy is None, "", first
        elif self._entries and all(n in self._meta for n in self._entries if self._entries[n].get("online_source", True)):
            text, enabled, variant, tip = "Up to date", False, "", "Every mod in this load order is at its latest version."
        else:
            text, enabled, variant, tip = "Update all", False, "", ""
        button.setText(text)
        button.setEnabled(enabled)
        button.setToolTip(tip)
        if button.property("variant") != variant:
            button.setProperty("variant", variant)
            button.style().unpolish(button)
            button.style().polish(button)

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
        self.settings_button.setEnabled(True)
        self.settings_button.clicked.connect(lambda: self._show_settings())
        self.help_button.setEnabled(True)
        self.help_button.clicked.connect(lambda: self._show_help())
        self.game_link.clicked.connect(lambda: self._open_folder(self.game_dir))
        self.load_order_link.clicked.connect(lambda: self.current_load_order and self._open_folder(self._load_order_dir()))
        self.bepinex_link.clicked.connect(lambda: self.current_load_order and self._open_folder(self._bepinex_dir()))
        self.rescan_button.clicked.connect(lambda: self.rescan())
        self.add_mod_button.clicked.connect(lambda: self._add_mod())
        active_model = self.active_list.mod_model
        for signal in (active_model.rowsAboutToBeInserted, active_model.rowsAboutToBeRemoved,
                       active_model.rowsAboutToBeMoved):
            signal.connect(lambda *_: self._history.append(self._snapshot()))
        for signal in (active_model.rowsInserted, active_model.rowsRemoved, active_model.rowsMoved):
            signal.connect(lambda *_: self._apply_load_order_state())
        self.undo_button.clicked.connect(lambda: self._undo())
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
        for link, path in ((self.load_order_link, self._load_order_dir()), (self.bepinex_link, self._bepinex_dir())):
            link.setEnabled(path is not None)
            link.setToolTip(str(path) if path else "")
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
    def _warn(self, title: str, message: str, parent: QWidget | None = None) -> None:
        log(f"warning shown: {title}: {message}")
        QMessageBox.warning(parent if parent is not None else self, title, message)

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

    def _confirm(self, title: str, message: str, *, confirm_label: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, message, QMessageBox.StandardButton.Cancel, self)
        confirm = box.addButton(confirm_label, QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        confirmed = box.clickedButton() is confirm
        log(f"confirm shown: {title}: {message} -> {confirm_label if confirmed else 'Cancel'}")
        return confirmed

    def _confirm_discard(self) -> bool:
        return not self._dirty() or self._confirm(
            "Unsaved changes", "Discard unsaved changes to the current list?", confirm_label="Discard changes"
        )

    # ---- background jobs ----
    def _run_job(self, name: str, fn, on_done, *, progress=None) -> None:
        """Runs fn(report) on a daemon thread; on_done({"ok": result} or
        {"error": text}) then runs on the GUI thread. report(text) reaches
        `progress` (GUI thread) when given."""
        carrier = _JobDone()
        carrier.done.connect(lambda payload: self._finish_job(carrier, on_done, payload), Qt.ConnectionType.QueuedConnection)
        if progress is not None:
            carrier.progress.connect(progress, Qt.ConnectionType.QueuedConnection)

        def run() -> None:
            try:
                payload = {"ok": fn(carrier.progress.emit)}
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
        on_done(payload)

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
            self._warn("Couldn't load load order", str(err))
            return None

    def _take_manifest(self, manifest: dict | None) -> None:
        self._manifest = manifest
        self._entries = lo.installed(manifest) if manifest else {}
        fw = manifest.get("framework") if manifest else None
        self._framework = fw["full_name"] if fw else None

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
            "Delete load order",
            f'Delete "{name}"? Its whole folder - the BepInEx install and every mod in it - is removed from disk. '
            "This can't be undone.\n\nDownloaded packages stay in VOLT's cache; the game itself isn't touched.",
            confirm_label="Delete",
        ):
            log(f"delete load order {slug} ({name!r}): cancelled")
            return
        res = lo.delete_load_order(self.app_root, slug)
        if res.get("skipped"):
            self._warn("Couldn't delete everything",
                       f"{len(res['skipped'])} file(s) couldn't be removed (in use?):\n"
                       + "\n".join(str(s.get("path", s)) for s in res["skipped"][:10]))
        old = self.current_load_order
        self._reload_load_order_picker(select_slug=old)
        if self.current_load_order == old:
            self._apply_load_order_state()
            return
        self._settings.update({"last_load_order": self.current_load_order})
        self._apply_current_load_order_to_panes()
        self._start_update_check()

    def _ask_name(self, title: str, message: str | None = None) -> str | None:
        name, ok = QInputDialog.getText(self, title, f"{message}\n\nName:" if message else "Name:")
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
            "New load order",
            f"A new load order gets its own BepInEx install: {self.ts_game.framework_package} is downloaded "
            "from Thunderstore (or taken from VOLT's cache) and set up for it right away.",
        )
        if name is None:
            return
        self._set_busy(f"Creating load order \"{name}\" - installing {self.ts_game.framework_package}...")

        def job(report):
            return lo.create_load_order(self.app_root, name, self.ts_game, self.app_version)

        def done(payload: dict) -> None:
            self._set_busy(None)
            if "error" in payload:
                self._warn("Couldn't create load order", payload["error"])
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

        self._run_job("create-load-order", job, done)

    def _copy_to_new_load_order(self) -> None:
        """Copies the open load order's whole tree under a new name, then
        applies the on-screen lists / toggles to the copy (so unsaved edits
        are what the copy holds), and opens it."""
        if self.current_load_order is None:
            return
        name = self._ask_name("Copy to new load order")
        if name is None:
            return
        src = self.current_load_order
        try:
            manifest = lo.copy_load_order(self.app_root, src, name)
            if self._dirty():
                manifest = lo.save_load_order(self.app_root, manifest["slug"], *self._save_lists())
        except (OSError, ValueError) as err:
            log(f"Copy to new load order: {src} -> {name!r} failed: {err!r}")
            self._warn("Couldn't copy load order", str(err))
            return
        log(f"Copy to new load order: {src} -> {manifest['slug']} ({name!r})")
        self._settings.update({"last_load_order": manifest["slug"]})
        self._reload_load_order_picker(select_slug=manifest["slug"])
        self._apply_current_load_order_to_panes()
        self.status_text.set_status_text(f"Copied to \"{name}\".")

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
            self._warn("Save failed", str(err))
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
            return f"{v}  ·  local package", False
        if self._has_update(mod_id):
            return f"{v}  ·  update available", True
        if mod_id == self._framework:
            return f"{v}  ·  framework, required", False
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
            icon=self._mod_icon(e), framework=mod_id == self._framework,
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

    # ---- dependency presence (THUNDERSTORE.md §3) ----
    def _update_issues(self) -> None:
        """An active, enabled mod whose declared dependency (the framework
        aside) isn't installed = error; installed but inactive / toggled off
        = warning. Fills _issues and the "⚠ N · ✕ M" button."""
        issues: dict[str, list[tuple[str, str]]] = {}
        active = set(self._active_ids())
        for mod_id in active:
            if not self._toggles.get(mod_id, True):
                continue
            e = self._entries.get(mod_id)
            for dep in (e or {}).get("dependencies", ()):
                try:
                    d = ts.PackageRef.parse(dep).full_name
                except ValueError:
                    continue
                if d == self._framework or d == mod_id:
                    continue
                if d not in self._entries:
                    issues.setdefault(mod_id, []).append(("error", f"requires {d}, which isn't installed"))
                elif d not in active:
                    issues.setdefault(mod_id, []).append(("warning", f"requires {d}, which is inactive"))
                elif not self._toggles.get(d, True):
                    issues.setdefault(mod_id, []).append(("warning", f"requires {d}, which is switched off"))
        self._issues = issues
        warnings = sum(1 for v in issues.values() for sev, _ in v if sev == "warning")
        errors = sum(1 for v in issues.values() for sev, _ in v if sev == "error")
        self.issues_label.setText(_issue_count_html(warnings, errors))
        self.issues_button.setVisible(bool(warnings or errors))

    def _show_issues(self) -> None:
        lines = []
        for mod_id, items in self._issues.items():
            name = self._display_name(mod_id)
            lines += [f"{'✕' if sev == 'error' else '⚠'} {name} {text}" for sev, text in items]
        log(f"issues shown: {len(lines)}")
        QMessageBox.information(
            self, "Warnings and errors",
            "\n".join(lines) if lines else "No issues.",
        )

    # ---- update checking (THUNDERSTORE.md §3) ----
    def _start_update_check(self, force: bool = False) -> None:
        """Runs check_updates over the open load order off the GUI thread.
        Without `force`, skipped when every package was already checked
        this session (a switch to an already-known load order)."""
        m = self._manifest
        if m is None or self._checking:
            return
        names = [n for n, e in self._entries.items() if e.get("online_source", True)]
        if not names:
            return
        if not force and all(n in self._meta and self._meta[n].get("checked_at", "") >= _SESSION_START for n in names):
            log("update check: every package already checked this session, skipped")
            return
        self._checking = True
        self._check_errors = {}
        log(f"update check: started for {len(names)} packages")
        self._apply_load_order_state()
        manifest, app_version = m, self.app_version

        def job(report):
            return lo.check_updates(manifest, app_version)

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
            self._meta[name] = {"latest_version": r["latest_version"], "date_updated": r["date_updated"], "checked_at": now}
        ts.write_meta_cache(self.app_root, self._meta)
        count = len(self._updatable())
        log(f"update check done: {count} updates, {len(self._check_errors)} failed")
        if self._busy is None:
            if count:
                self.status_text.set_status_text(
                    f"{count} mod{'s have' if count != 1 else ' has'} an update available.", "warn")
            elif self._check_errors:
                self.status_text.set_status_text(
                    f"Couldn't check {len(self._check_errors)} package(s) for updates: "
                    f"{next(iter(self._check_errors.values()))}", "warn")
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
                self._warn(f"Couldn't update {name}", payload["error"])
                self.status_text.set_status_text(f"Couldn't update {name}.", "error")
                return
            res = payload["ok"]
            self._refresh_after_change(res["manifest"])
            if res["updated"]:
                self.status_text.set_status_text(f"Updated {name} to {res['entry']['version']}.")
            else:
                self.status_text.set_status_text(f"{name} is already at its latest version.")
            self._start_update_check(force=True)

        self._run_job(f"update-{mod_id}", job, done)

    def _update_all_clicked(self) -> None:
        if self._checking or self._busy is not None:
            return
        if not self._updatable():
            self._start_update_check(force=True)  # the "Retry" state
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
                self._warn("Update all failed", payload["error"])
                return
            res = payload["ok"]
            self._refresh_after_change()
            if res["failed"]:
                self._warn("Some updates failed",
                           "\n".join(f"{self._display_name(n)}: {msg}" for n, msg in res["failed"]))
            self.status_text.set_status_text(
                f"Updated {len(res['done'])} of {len(names)} mods." if res["failed"] else f"Updated {len(res['done'])} mods.",
                "warn" if res["failed"] else "info",
            )
            self._start_update_check(force=True)

        self._run_job("update-all", job, finished, progress=lambda text: self.status_text.set_status_text(text))

    # ---- add / uninstall ----
    def _add_mod(self) -> None:
        if self.current_load_order is None or self._busy is not None:
            return
        text, ok = QInputDialog.getText(self, "Add mod", ADD_MOD_PROMPT)
        if not ok or not text.strip():
            log("add mod: cancelled")
            return
        try:
            ref = parse_package_input(text)
        except ValueError:
            self._warn("Add mod", f'"{text.strip()}" isn\'t a Thunderstore package name (Team-Package) or package URL.')
            return
        if ref.full_name in self._entries:
            self._notice("Add mod", f"{ref.full_name} is already in this load order.")
            return
        self._set_busy(f"Installing {ref.full_name}...")
        slug = self.current_load_order

        def job(report):
            return lo.install_mod(self.app_root, slug, self.ts_game, ref, self.app_version)

        def done(payload: dict) -> None:
            self._set_busy(None)
            if "error" in payload:
                self._refresh_after_change()  # a dependency may have landed before the target failed
                self._warn(f"Couldn't install {ref.full_name}", payload["error"])
                self.status_text.set_status_text(f"Couldn't install {ref.full_name}.", "error")
                return
            res = payload["ok"]
            new = [e["full_name"] for e in res["installed"]]
            log(f"add mod: installed {new}, {len(res['problems'])} problems")
            # The new mods are on disk as active + enabled already: they join
            # the on-screen Active list and the baseline alike, so an install
            # is never itself an unsaved change.
            ids, toggles = self._snapshot()
            self._take_manifest(self._read_manifest())
            self._show_lists(ids + [n for n in new if n not in ids], {**toggles, **{n: True for n in new}})
            base_ids, base_toggles = self._baseline
            self._baseline = (base_ids + [n for n in new if n not in base_ids], {**base_toggles, **{n: True for n in new}})
            self._apply_load_order_state()
            if res["problems"]:
                self._warn("Some dependencies couldn't be installed",
                           "\n".join(f"{p.get('package', '?')}: {p.get('message', '')}" for p in res["problems"]))
            extra = len(new) - 1
            self.status_text.set_status_text(
                f"Installed {ref.full_name}" + (f" and {extra} dependenc{'ies' if extra != 1 else 'y'}" if extra > 0 else "") + ".")
            self._start_update_check(force=True)

        self._run_job(f"install-{ref.full_name}", job, done)

    def _uninstall(self, mod_id: str) -> None:
        if mod_id == self._framework or mod_id not in self._entries or self._busy is not None:
            return
        name = self._display_name(mod_id)
        if not self._confirm(
            "Uninstall mod",
            f"Remove {name} ({mod_id}) from this load order? Its files are deleted from the load order's "
            "BepInEx folder (its config files are kept). Other load orders aren't affected.",
            confirm_label="Uninstall",
        ):
            log(f"uninstall {mod_id}: cancelled")
            return
        try:
            manifest = lo.remove_mod(self.app_root, self.current_load_order, mod_id)
        except (OSError, ValueError) as err:
            self._warn(f"Couldn't uninstall {name}", str(err))
            return
        ids, toggles = self._snapshot()
        self._take_manifest(manifest)
        self._show_lists([n for n in ids if n != mod_id], toggles)
        base_ids, base_toggles = self._baseline
        self._baseline = ([n for n in base_ids if n != mod_id], {k: v for k, v in base_toggles.items() if k != mod_id})
        self._history = [([n for n in i if n != mod_id], {k: v for k, v in t.items() if k != mod_id}) for i, t in self._history]
        self._apply_load_order_state()
        self.status_text.set_status_text(f"Uninstalled {name}.")
        self._start_update_check(force=True)

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
        log(f"context menu: {mod_id} in {self._pane_name(pane)} (folder={folder}, update={self._has_update(mod_id)})")
        menu = QMenu(pane)

        def item(label: str, enabled, fn) -> None:
            action = menu.addAction(label)
            action.setEnabled(bool(enabled))
            action.triggered.connect(lambda: fn())

        item("Open folder", folder, lambda: self._open_folder(folder))
        item("Open on Thunderstore", True, lambda: self._open_url(page))
        item("Open website", site, lambda: self._open_url(site))
        item("Copy package name", True, lambda: self._copy_text(e["full_name"], f'Copied "{e["full_name"]}".'))
        item("Edit config...", True, lambda: self._edit_config(e.get("name") or ""))
        menu.addSeparator()
        item("Update", idle and self._has_update(mod_id) and mod_id not in self._updating, lambda: self._update_one(mod_id))
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
        self.settings_button = _button("Settings")
        row.addWidget(self.settings_button)
        row.addSpacing(16 - GAP)
        row.addWidget(_label("Paths:", muted=True))
        self.game_link = _button("Game", variant="link")
        self.load_order_link = _button("Load order", variant="link")
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
        row.addWidget(_label("Load order", muted=True))
        self.load_order_picker = QComboBox()
        self.load_order_picker.setMinimumWidth(220)
        self.load_order_picker.setEnabled(False)
        self.load_order_picker.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.load_order_picker.customContextMenuRequested.connect(self._show_load_order_menu)
        row.addWidget(self.load_order_picker)
        self.new_button = _button("New load order...")
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
        self.undo_button.setToolTip("Undo the most recent change to the active list")
        self.undo_button.setVisible(False)
        row.addWidget(self.undo_button)
        row.addStretch(1)
        self.update_all_button = _button("Update all")
        row.addWidget(self.update_all_button)
        return bar

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
        row.addWidget(self._build_actions_column())
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
        title_label = QLabel(title)
        title_label.setProperty("role", "pane-title")
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
        list_cell = QGridLayout()
        list_cell.setContentsMargins(0, 0, 0, 0)
        list_cell.addWidget(mod_list, 0, 0)
        no_matches = _label("No matches", muted=True)
        no_matches.setContentsMargins(12, 12, 12, 12)
        no_matches.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        no_matches.setVisible(False)
        list_cell.addWidget(no_matches, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(list_cell, 1)
        drag_hint = None
        if draggable:
            drag_hint = _label("Clear the filter to drag-reorder.", muted=True)
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
        self.import_button.setToolTip(STAGE_TOOLTIP["import"])
        self.export_button = _button("Export...")
        self.export_button.setToolTip(STAGE_TOOLTIP["export"])
        self.rescan_button = _button("Rescan")
        self.rescan_button.setToolTip("Re-read the open load order from disk and check for updates again.")
        self.add_mod_button = _button("Add mod...", variant="accent-outline")
        self.add_mod_button.setToolTip("Install a Thunderstore package (and its dependencies) into the open load order.")
        self.browse_button = _button("Browse Mods...", variant="accent-outline")
        self.browse_button.setToolTip(STAGE_TOOLTIP["browse"])
        layout.addLayout(self._group(self.import_button, self.export_button, self.rescan_button,
                                     self.add_mod_button, self.browse_button))
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
        self.run_button = _button("Run", variant="primary")
        self.run_button.setToolTip(STAGE_TOOLTIP["run"])
        layout.addLayout(self._group(self.save_button, self.run_button))
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
        self.status_text = _StatusText()
        row.addWidget(self.status_text, 1)
        column.addWidget(footer)
        return box


