"""Valheim's entries for the Help window (screens/help_window.py): one per
button/control on the Valheim manager screen (screens/bepinex_main_screen.py),
the row right-click menu grouped into one entry, as RimWorld's
(rimworld_help_entries.py; the list THUNDERSTORE.md §6 scoped, written
against what the screen actually does today).

Plain data, no Qt. The window sorts by name itself; kept roughly in
on-screen order (header, load-order bar, panes, rows, actions column).
Update an entry whenever the control it describes changes. The next
BepInEx game copies this file and swaps the game name.
"""

VALHEIM_HELP_ENTRIES: list[dict] = [
    # ---- header ----
    {
        "name": "Settings",
        "short": "Opens the Settings window, where you tell VOLT where Valheim is installed.",
        "long": (
            "General shows the game folder with a Browse button, plus Autodetect to find your Steam install for "
            "you. It's the only path Valheim needs: every load order keeps its mods and their BepInEx config in "
            "its own folder under VOLT's data folder, never inside the game. Troubleshooting opens VOLT's log "
            "file (or the one from the previous run), which is handy when reporting a problem. Its Clean cache "
            "button deletes downloaded mod files that no load order uses any more, to free up space - a "
            "Thunderstore mod just downloads again if you install it later."
        ),
    },
    {
        "name": "Paths: Game folder",
        "short": "Opens Valheim's install folder in your file explorer.",
        "long": (
            "This is the \"Game\" link next to \"Paths:\" at the top of the window. It's greyed out until a game "
            "folder is set. Hover it to see the full path. The line under the links spells out the game folder "
            "and the open load order's BepInEx folder."
        ),
    },
    {
        "name": "Paths: Load order folder",
        "short": "Opens the currently open load order's own folder.",
        "long": (
            "This is the \"Load order\" link next to \"Paths:\". Each load order is a complete, separate BepInEx "
            "install under VOLT's data folder: its loadorder.json (what's installed and switched on) sits beside "
            "its BepInEx folder. Greyed out while no load order is open; it follows the picker."
        ),
    },
    {
        "name": "Paths: BepInEx folder",
        "short": "Opens the open load order's BepInEx folder (plugins, config, patchers...).",
        "long": (
            "This is the \"BepInEx\" link next to \"Paths:\". Inside are core (BepInEx itself), plugins (one "
            "subfolder per mod), config (every mod's settings files, kept across updates) and patchers. Greyed "
            "out while no load order is open."
        ),
    },
    {
        "name": "Help",
        "short": "Opens this window.",
        "long": "Pick an entry on the left to read what that part of the screen does.",
    },
    # ---- load-order bar ----
    {
        "name": "Load order picker",
        "short": "Switches between your saved load orders.",
        "long": (
            "The drop-down in the second row. Each load order is its own BepInEx install with its own mods, so "
            "switching costs nothing - nothing is copied around. If the open load order has unsaved changes, "
            "VOLT asks before switching. Right-click the picker to delete the open load order."
        ),
    },
    {
        "name": "New load order",
        "short": "Creates an empty load order with BepInEx set up in it.",
        "long": (
            "Asks for a name, then downloads BepInExPack for Valheim from Thunderstore (or takes it from VOLT's "
            "cache if another load order already fetched it) and installs it into the new load order's folder, "
            "so it's ready to run right away. That framework package is pinned at the top of the Active list."
        ),
    },
    {
        "name": "Copy to new",
        "short": "Duplicates the open load order, mods and settings included, under a new name.",
        "long": (
            "Copies the whole load order folder - BepInEx, every installed mod, their config files and which "
            "ones are switched on - and opens the copy. Unsaved changes on screen are applied to the copy."
        ),
    },
    {
        "name": "Undo",
        "short": "Takes back the most recent change to the Active list.",
        "long": (
            "The ↺ button that appears next to \"Unsaved changes\" whenever the lists differ from what's saved. "
            "Each click restores the lists (order, membership and toggles) from before the previous change. "
            "Ctrl+Z does the same, except while you're typing in a text box (there it undoes the typing). "
            "There's no redo."
        ),
    },
    {
        "name": "Update all",
        "short": "Downloads and installs the newest version of every mod that has one.",
        "long": (
            "The button at the right end of the second row. VOLT checks Thunderstore for updates when the "
            "manager opens, when you switch to a load order it hasn't checked yet, after a mod is added, "
            "removed or updated, and on Rescan. While updates are waiting the button turns yellow and shows how "
            "many; click it to update them all. \"Up to date\" means none are waiting; \"Update check failed · "
            "Retry\" means Thunderstore couldn't be reached - click to try again. Updating never changes which "
            "mods are switched on. The same check spots mods deprecated on Thunderstore: their rows get a red "
            "Deprecated pill before the name (in either list) and the details panel a yellow warning that the mod "
            "may no longer be maintained, until a later check finds it no longer deprecated."
        ),
    },
    {
        "name": "Delete load order",
        "short": "Removes a load order and everything in it from disk.",
        "long": (
            "Right-click the load order picker and choose Delete. The load order's whole folder goes - its "
            "BepInEx install and every mod in it - after a confirmation. Downloaded packages stay in VOLT's "
            "cache, and the game itself is never touched."
        ),
    },
    {
        "name": "Edit config",
        "short": "View, edit or delete the config files the load order's mods have written.",
        "long": (
            "Click Config in the actions column (under Rescan), or right-click the load order picker (or any mod "
            "row) and choose Edit config..., to open the load "
            "order's BepInEx/config folder: every file in it, listed flat on the left with a search box, a sort "
            "and a \"Show all files\" switch for the non-text data some mods keep there. Click a file to load it "
            "on the right: a BepInEx .cfg becomes a settings form - each setting with its description, type, "
            "default and the right control (a drop-down, check boxes, a number, a color swatch, a text box) - and "
            "any other file (.json, .yml, .txt) is shown as raw text. Save writes your changes, Revert drops them, "
            "Delete removes the file (a mod writes a fresh default one on the next run) and Open externally opens "
            "it in your usual editor. Until the load order has been run once only BepInEx's own "
            "BepInEx.cfg is there, since BepInEx creates each mod's config file on first launch."
        ),
    },
    # ---- panes ----
    {
        "name": "Search box",
        "short": "Filters a list by mod or author name.",
        "long": (
            "Each list has its own search box. Typing hides every row that doesn't match the mod's name, its "
            "author (the Thunderstore team) or its package name. The count in the list's title shows how many "
            "match."
        ),
    },
    {
        "name": "Search eye icon",
        "short": "Switches a search between hiding non-matches and dimming them.",
        "long": (
            "The eye at the right end of a search box. Closed (the default) hides rows that don't match. Open "
            "shows every row, with the non-matches dimmed and the matches marked with a blue bar. Drag-reorder "
            "is off while rows are hidden."
        ),
    },
    {
        "name": "Drag to reorder",
        "short": "Drag a row in the Active list to change its position.",
        "long": (
            "Press on a row in the Active list and move it; the other rows slide aside, and the row lands where "
            "you release it. The framework row at the top can't be moved and nothing can be dropped above it. "
            "The order is only for you: BepInEx works out the real load order from each mod's own dependency "
            "information, so it never changes how the game loads."
        ),
    },
    {
        "name": "Moving mods between lists",
        "short": "Double-click a row to move it to the other list.",
        "long": (
            "Double-clicking an Inactive mod appends it to the Active list, switched on; double-clicking an "
            "Active mod moves it to Inactive. An inactive mod stays installed in the load order, just switched "
            "off on disk when you Save, so moving it back never downloads anything. The framework row can't "
            "be moved."
        ),
    },
    {
        "name": "Per-mod on/off toggle",
        "short": "Switches an Active mod off without removing it from the list.",
        "long": (
            "The pill at the right end of every Active row except the framework's. Off keeps the mod in the "
            "list, at its position, but its files are disabled when you Save - a quick, reversible way to "
            "leave one mod out for a test. Blue means on. A switched-off row shows a yellow Disabled pill before "
            "its name, and the name turns grey and struck through. The framework row has no toggle: a load "
            "order can't start without it. Enable all / Disable all (under Export...) set every Active toggle at "
            "once - still unsaved until Save, one Undo puts them back, and the framework always stays on."
        ),
    },
    {
        "name": "Per-mod update button",
        "short": "The yellow ↑ on a row: installs that one mod's newest version.",
        "long": (
            "Shown on an Active row (the framework included) only while Thunderstore has a newer version than "
            "the installed one - its second line then reads \"update available\" in yellow. Click it to "
            "download and install just that mod's latest version; \"Update all\" does every mod at once. "
            "The mod's config files are kept."
        ),
    },
    {
        "name": "Framework row (BepInExPack)",
        "short": "The pinned first row of the Active list: BepInEx itself.",
        "long": (
            "Every load order is built on Thunderstore's BepInExPack for Valheim, installed when the load order "
            "is created. It's pinned at the top of Active, can't be dragged, switched off, moved to Inactive or "
            "uninstalled, and gets the yellow update button like any mod when a newer pack is out."
        ),
    },
    {
        "name": "Mod right-click menu",
        "short": "Open the mod's folder or pages, copy its package name, edit config, install missing dependencies, update or uninstall it.",
        "long": (
            "Right-click a row in either list. Open folder opens the mod's own subfolder under BepInEx/plugins, "
            "Open on Thunderstore its Thunderstore page and Open website its own site, when it has one. Copy "
            "package name copies the Team-Package name Thunderstore uses, and Edit config... opens the load order's "
            "config files with the search pre-filled with this mod's name. Install missing dependencies (N) "
            "appears only on a mod whose dependencies aren't installed and fetches them - each at its latest "
            "version, with whatever they need themselves - into the Active list; Update is available while a "
            "newer version is out; Uninstall... removes the mod's files from this load order (its config files "
            "are kept; other load orders aren't affected) after a confirmation."
        ),
    },
    {
        "name": "Warnings and errors",
        "short": "The \"⚠ N · ✕ M\" button: mods whose dependencies aren't there, with a fix for the missing ones.",
        "long": (
            "Appears above Save while an Active, switched-on mod declares a dependency that isn't installed in "
            "this load order (an error, marked ✕ on the row) or is installed but inactive or switched off (a "
            "warning). Click it for the window: one entry per problem, grouped by mod, with what it means and "
            "what fixes it. A missing dependency has an Install button right there (its latest version, with "
            "whatever it needs itself, added to the Active list), and Install all missing at the top does them "
            "all at once; a dependency that's merely inactive or switched off is fixed by activating or "
            "switching it back on, so it has no button. Adding a mod installs its dependencies with it, so this "
            "mostly shows up after something was uninstalled or switched off."
        ),
    },
    # ---- actions column ----
    {
        "name": "Rescan",
        "short": "Re-reads the open load order from disk and checks for updates again.",
        "long": (
            "Reloads what's installed and switched on from the load order's own folder, dropping any unsaved "
            "changes on screen (it asks first), then runs the update check again."
        ),
    },
    {
        "name": "Add mod",
        "short": "Installs a Thunderstore package into the open load order.",
        "long": (
            "Asks for a package: its Team-Package name (as on Thunderstore, e.g. ValheimModding-Jotunn) or the "
            "address of its thunderstore.io page. VOLT downloads its latest version (or takes it from the "
            "cache), installs any of its dependencies that aren't in the load order yet, and appends it to the "
            "Active list switched on. Downloads are shared: a package fetched once is reused by every load "
            "order. It's the shortcut for when you already know the package; Browse Mods is the same install "
            "with searching built in."
        ),
    },
    {
        "name": "Browse Mods",
        "short": "Opens the in-app Thunderstore browser to find Valheim mods and install them into the open load order.",
        "long": (
            "Search by name, narrow by category, and sort by most downloaded (the starting order), last updated, "
            "top rated or newest - each page comes straight from Thunderstore as you ask for it, so nothing is "
            "downloaded until you press Install. A card's Install button adds that mod (and any dependencies it "
            "needs) to the Active list, exactly like Add mod, and the browser stays open so you can keep going. "
            "Click a card itself for the mod's page: Details (its README, with the dependency check underneath), "
            "Required (each dependency and whether it's already in the load order - click one to open its own page), Versions (every release, each "
            "with its own Install) and Changelog, plus the latest version's facts and categories on the right - the "
            "version selector in the header decides what the big Install button installs, and it says how many "
            "extra packages come along. Back to results, Esc or Backspace go one step back - to the mod you came "
            "from through Required, else to the grid where you left it; "
            "the X (or Esc on the grid) closes the browser. Show deprecated and Show NSFW, next to the X, add "
            "those mods to the results alongside the rest (both start off each time the browser opens); a "
            "deprecated mod's card has a red Deprecated pill, and its page opens with a yellow warning that it "
            "may no longer be maintained."
        ),
    },
    {
        "name": "Import",
        "short": "Creates a new load order from a .r2z profile file - VOLT's or r2modman / Thunderstore Mod Manager's.",
        "long": (
            "Pick \"Import from file...\" and choose the file; VOLT asks for a name (the file's own profile name is "
            "offered) and always makes a new load order - an existing one is never changed. It sets up BepInEx at the "
            "file's version, downloads every listed mod at exactly the version in the file (if Thunderstore no longer "
            "has that version, the latest is installed and the summary says so; a mod that can't be fetched at all is "
            "listed as failed and the rest still install), puts the file's config files in place, and switches off "
            "the mods the file has switched off. A file made for another game is refused. Mod files never travel in "
            "the file itself, so an import needs an internet connection. \"Import from code...\" takes a profile code "
            "instead - VOLT's, r2modman's or Thunderstore Mod Manager's - downloads that profile from Thunderstore and "
            "then imports it exactly the same way. \"Local mod (.zip)...\" is different: it installs one mod from "
            "a Thunderstore package zip on your computer into the open load order (added to Active, its missing "
            "dependencies downloaded), marked as a local package that's never checked for updates."
        ),
    },
    {
        "name": "Export",
        "short": "Saves the open load order as a .r2z profile file that VOLT and r2modman / Thunderstore Mod Manager can read.",
        "long": (
            "Pick \"Export to file...\" and choose where to save it (the load order's name is the default file name). "
            "The file holds the mod list as shown on screen right now - unsaved changes included, like Copy to new - "
            "with each mod's version and on/off state, plus every file in the load order's BepInEx config folder, "
            "so a friend's import gets your settings too. Inactive mods are written as switched off (that's what "
            "another mod manager understands); VOLT itself restores them to Inactive. Mod files aren't included - "
            "they're downloaded again on import. \"Export as code...\" uploads the same profile to Thunderstore's public "
            "profile-sharing service (after asking you to confirm - anyone with the code can fetch it, and it can't be "
            "taken back) and shows a short code with a Copy button; VOLT, r2modman and Thunderstore Mod Manager can all "
            "import it. \"Dependency strings...\" lists the framework and every switched-on Active mod as "
            "\"Team-Package-Version\" lines, ready to copy into a modpack's manifest.json (locally imported mods "
            "aren't on Thunderstore, so they're left out)."
        ),
    },
    {
        "name": "Modded and Vanilla",
        "short": "The two play buttons: Modded starts Valheim with the open load order, Vanilla without mods or BepInEx.",
        "long": (
            "Modded copies the load order's two BepInEx loader files (winhttp.dll and doorstop_config.ini) into the "
            "Valheim folder - anything already there under those names is set aside - and starts the game through "
            "Steam with launch arguments that point BepInEx at the load order's own folder, so the game install "
            "itself stays as it is; when the game exits, the copied files are removed and anything set aside is put "
            "back. Vanilla starts Valheim through Steam as it is, with nothing copied and no BepInEx - it needs "
            "no load order open. Either way "
            "the screen stays locked while Valheim runs, and a game left running when VOLT closes is picked up "
            "again the next time this screen opens. Neither button saves: with unsaved changes Modded asks first "
            "and Valheim gets the load order as it was last saved, and it also asks before starting with mods "
            "whose dependencies aren't installed."
        ),
    },
    {
        "name": "Save",
        "short": "Writes the Active list and every toggle into the load order for real.",
        "long": (
            "The one save there is: every Active, switched-on mod gets its files enabled in the load order's "
            "BepInEx folder, everything else (Inactive mods, toggled-off mods) gets them disabled, and the "
            "order is remembered. Nothing is downloaded and the game install is never touched. Turns yellow "
            "while there are unsaved changes."
        ),
    },
]
