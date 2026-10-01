"""RimWorld's entries for the Help window (screens/help_window.py): one per
button/control on the main screen, with the mod right-click menu grouped
into a single entry (decided with the user, PLAN.md §7 / RIMWORLD.md).

Plain data, no Qt. The window sorts by name itself, so order here doesn't
matter; kept roughly in on-screen order (header, load-order bar, panes,
actions column) to make it easy to check against the screen. Update an
entry whenever the control it describes changes.
"""

from volt_py.offline_mods import OFFLINE_RUN_TEXT

RIMWORLD_HELP_ENTRIES: list[dict] = [
    # ---- header ----
    {
        "name": "Settings",
        "short": "Opens the Settings window, where you tell VOLT where RimWorld and its files live.",
        "long": (
            "General has the game, local mods and config folders (Browse for the game and config ones), "
            "Autodetect to find a RimWorld install for you, and the Animations setting. Steam lets you choose how "
            "Workshop mods are downloaded and "
            "check for Workshop mods that are missing. Troubleshooting opens VOLT's log file (or the one from "
            "the previous run), which is handy when reporting a problem."
        ),
    },
    {
        "name": "Paths: Game folder",
        "short": "Opens RimWorld's install folder in your file explorer.",
        "long": (
            "This is the \"Game\" link next to \"Paths:\" at the top of the window. It's greyed out until a game "
            "folder is set in Settings. Hover it to see the full path."
        ),
    },
    {
        "name": "Paths: Mods folder",
        "short": "Opens the game's local Mods folder in your file explorer.",
        "long": (
            "This is the \"Mods\" link next to \"Paths:\" at the top of the window. It's the Mods folder inside "
            "the game folder, where manually installed mods go. Steam Workshop mods live elsewhere, in Steam's "
            "own Workshop folder."
        ),
    },
    {
        "name": "Paths: Config folder",
        "short": "Opens RimWorld's Config folder in your file explorer.",
        "long": (
            "This is the \"Config\" link next to \"Paths:\" at the top of the window. The Config folder holds "
            "ModsConfig.xml, the file RimWorld reads to decide which mods to load, which is what Push writes to. "
            "It's greyed out until a config folder is set in Settings."
        ),
    },
    {
        "name": "Paths: Load order folder",
        "short": "Opens the selected load order's own folder in your file explorer.",
        "long": (
            "This is the \"Load order\" link next to \"Paths:\" at the top of the window. Each load order is "
            "saved as its own folder inside VOLT's load-orders folder, holding its loadorder.json. It's greyed "
            "out until a load order is selected, and works even before a game folder is set. Hover it to see "
            "the full path."
        ),
    },
    # ---- load-order bar ----
    {
        "name": "Load order picker",
        "short": "Switches between your saved load orders.",
        "long": (
            "Pick a load order from the dropdown to show its Active and Inactive lists. If the one you're "
            "leaving has unsaved changes, VOLT asks before discarding them. Right-click the dropdown to turn "
            "the load order's own game data on or off, or to delete it."
        ),
    },
    {
        "name": "New load order",
        "short": "Starts a new load order under a name you choose, with Core and your DLC active.",
        "long": (
            "Core and every installed DLC start out in the Active list, in release order; every other installed "
            "mod starts in the Inactive list, so you can build the rest of the Active list from there. "
            "If the current load order has unsaved changes, VOLT asks before discarding them. The new load order "
            "becomes the one that's open."
        ),
    },
    {
        "name": "Copy to new",
        "short": "Saves a copy of the current lists as a new load order.",
        "long": (
            "The new load order gets exactly what's on screen right now, in the same order, including any "
            "changes you haven't saved yet. You'll be asked for a name, and the copy becomes the one that's "
            "open. The original load order stays as it was last saved. Its Offline mods get their own, separate "
            "copies in the new load order, made in the background right after."
        ),
    },
    {
        "name": "Undo (↺)",
        "short": "Undoes your last change to the Active list.",
        "long": (
            "The ↺ button only shows while there are unsaved changes; Ctrl+Z does the same as clicking it, "
            "except in a text box, where it undoes your typing. Each click steps back one change: a "
            "drag, a mod moved in or out, a Sort, and so on. There's no redo, and changes to the Inactive list "
            "alone aren't tracked. Saving clears the undo history."
        ),
    },
    {
        "name": "Delete load order",
        "short": "Right-click the load order picker to delete a saved load order.",
        "long": (
            "VOLT asks you to confirm first, because this can't be undone. The saved list is removed, along with "
            "the load order's own game data (its saves and settings) and its Offline mod copies if it has any; "
            "your mods themselves aren't touched. If you delete the load order that's open, VOLT switches to another saved one, or shows an "
            "empty screen if none are left."
        ),
    },
    # ---- panes ----
    {
        "name": "Search box",
        "short": "Filters a list to the mods that match what you type.",
        "long": (
            "The Inactive and Active lists each have their own search box. It matches a mod's name, author or "
            "package ID, and updates as you type. Clear the box to see every mod again."
        ),
    },
    {
        "name": "Search eye icon",
        "short": "Chooses whether search hides the mods that don't match or just dims them.",
        "long": (
            "The eye sits at the right end of each list's search box. By default, mods that don't match are "
            "hidden. Click the eye to keep every mod visible instead, with non-matches dimmed and matches "
            "highlighted, which helps you see where a mod sits in the whole list. Click again to switch back."
        ),
    },
    {
        "name": "Drag to reorder",
        "short": "Drag mods up and down the Active list to change their load order.",
        "long": (
            "Only the Active list can be reordered, and mods near the top load first. Dragging is turned off "
            "while that list's search is hiding mods; clear the search or switch the eye icon to dimming to "
            "drag again. To move a mod between Inactive and Active, double-click it."
        ),
    },
    {
        "name": "Mod right-click menu",
        "short": "Right-click any mod in either list for more things you can do with it.",
        "long": (
            "Open folder shows the mod's files, Open URL goes to a Workshop mod's page, Filter by narrows the list "
            "to mods by the same author or color, Copy to clipboard copies its URL, package ID or folder path, Mod color tags "
            "it with a color, Rules creates or shows your own sort rules for it, and Make Offline gives the open load "
            "order its own frozen copy of the mod when its Own game data is on (Make live again, or Delete on an "
            "Offline mod, deletes only that copy; Refresh Offline copy re-copies it from the live mod). With Settings > Steam set to "
            "download with SteamCMD and sync later, Download fetches a missing Workshop mod with SteamCMD (even one "
            "the list only knows by its package ID, when VOLT can find its Workshop ID), and Subscribe turns a mod "
            "VOLT downloaded that way into a real Steam subscription, exactly like the Sync button but for that one "
            "mod (Steam must be running); with the Steam client setting, Subscribe itself subscribes a missing mod on "
            "Steam; the next item reads Unsubscribe for a Steam subscription or Delete for a SteamCMD download, which "
            "removes it from the Mods folder; for a GOG install, Fetch puts a missing mod back from VOLT's SteamCMD "
            "download cache (or downloads it) and Delete removes it. Remove completely deletes a mod's files from "
            "every place VOLT looks for mods, including a leftover folder Steam isn't subscribed to, and takes it "
            "out of the load order after listing exactly what it will delete; it keeps the download cache unless "
            "you tick the box and refuses RimWorld's own Core/DLC and anything Steam still has you subscribed to "
            "(use Unsubscribe first). Options that don't apply to a mod are greyed out (a row that isn't installed yet "
            "only shows the ones that can apply to it, such as Download), and the greyed line at the top says where "
            "the mod comes from (Steam Workshop, SteamCMD copy, Local mod and so on), as the details pane's Source "
            "row does."
        ),
    },
    # ---- actions column ----
    {
        "name": "Import",
        "short": "Brings a mod list into the Active list from somewhere else.",
        "long": (
            "You can import from the clipboard, a RimPy .xml file, a rentry.co page, a save file's mod list, or "
            "the Steam Workshop. A Workshop link or ID adds that mod to your list; a Workshop collection asks "
            "whether to add to your list, replace it, or start a new load order. If an import would replace "
            "your list and you have unsaved changes, VOLT asks before discarding them."
        ),
    },
    {
        "name": "Export",
        "short": "Sends your current mod list somewhere else to share or back up.",
        "long": (
            "Rentry makes a rentry.co share link you can send to others. Clipboard copies the list as text in "
            "RimSort's format. .xml saves a file RimPy can open. Export is greyed out while the Active list is "
            "empty."
        ),
    },
    {
        "name": "Rescan",
        "short": "Checks your mod folders again for mods you've added, removed or updated.",
        "long": (
            "Use this after installing or deleting mods while VOLT is open. Your Active list stays as it is, "
            "including unsaved changes and undo history; the Inactive list is rebuilt from what's on disk now."
        ),
    },
    {
        "name": "Sort",
        "short": "Automatically puts the Active list in a sensible load order.",
        "long": (
            "Sort follows, in order of priority: your own rules, community rules, each mod's own load-order "
            "rules from its About.xml, then dependencies, and finally alphabetical order. It only changes the "
            "list on screen, like a manual reorder: click Save to keep it, or Undo to go back."
        ),
    },
    {
        "name": "Save",
        "short": "Saves the Active and Inactive lists to the open load order.",
        "long": (
            "This only saves VOLT's own copy of the load order; RimWorld won't use it until you Push, or until "
            "you click Modded for a load order with its own game data. The Save button is outlined in yellow while "
            "there are unsaved changes, and saving also clears the undo history."
        ),
    },
    {
        "name": "Sync",
        "short": "Turns Workshop mods VOLT downloaded itself into real Steam subscriptions.",
        "long": (
            "Mods downloaded through VOLT's own downloader get subscribed on Steam, and VOLT's copy is removed "
            "once Steam has finished downloading its own. This needs Steam running and can take a little while; "
            "Steam may show RimWorld as running during it. If every Workshop mod is already subscribed, there's "
            "nothing to do."
        ),
    },
    {
        "name": "Scan issues",
        "short": "Lists mod folders VOLT couldn't read as mods.",
        "long": (
            "This button only shows when there's a problem, labeled with how many (\"2 scan issues\"). The "
            "window explains each one: a missing folder, a folder with no About.xml, an About.xml that can't be "
            "read, or two mods sharing the same package ID. From there you can open the folder or ignore the "
            "issue so it stops showing."
        ),
    },
    {
        "name": "Warnings & errors",
        "short": "Shows problems with your Active list, grouped by mod.",
        "long": (
            "This button only shows when there's something to report, as \"⚠ warnings · ✕ errors\". Warnings "
            "are mods loading in the wrong order for their rules. Errors are missing dependencies or mods that "
            "conflict with each other. Sort fixes most warnings; errors usually mean adding or removing a mod."
        ),
    },
    {
        "name": "Push",
        "short": "Saves your load order and makes RimWorld use it next time it starts.",
        "long": (
            "Push saves the load order in VOLT, then writes the Active list to RimWorld's ModsConfig.xml in the "
            "Config folder, keeping a backup of the old file. If there are unsaved changes, VOLT confirms before "
            "saving them. It needs the Config folder set in Settings. A load order with its own game data doesn't "
            "need a Push to play it with Modded."
        ),
    },
    {
        "name": "Modded",
        "short": "Starts RimWorld with the open load order.",
        "long": (
            "Modded never saves or pushes for you. With the load order's own game data on, RimWorld starts with "
            "its saved mod list and its own saves and settings; with it off, RimWorld uses its usual data "
            "folder and whatever mod list was last pushed, so Push first. If you have unsaved changes, VOLT warns "
            "you first, and while the game runs VOLT keeps Modded, Vanilla, Games and Settings locked. With own game data "
            "on, the load order's active Offline mods are linked into the game's Mods folder for the run and removed "
            "again when the game closes (even after a crash, the next time VOLT starts)."
        ),
    },
    {
        "name": "Vanilla",
        "short": "Starts a clean RimWorld: only Core and your DLCs, no mods of any kind.",
        "long": (
            "Vanilla uses its own data folder, vanilla-data in VOLT's folder, so it has its own saves and settings "
            "and never touches your normal RimWorld data folder (your usual saves don't show up there). Before "
            "every start VOLT resets its mod list to Core plus your installed DLCs, so a mod switched on in-game "
            "last time doesn't stay on. It doesn't need a load order open, and like Modded it keeps VOLT locked "
            "until the game exits."
        ),
    },
    {
        "name": "Own game data",
        "short": "Gives a load order its own saves, settings and mod config.",
        "long": (
            "Right-click the load order picker and choose Own game data to turn it on or off; it's off for new "
            "load orders. When it's on, Modded runs keep their saves, settings and mod config in the load "
            "order's own data folder, starting fresh with default settings and no saves, while your existing "
            "ones stay with the normal RimWorld folder (Vanilla has its own separate data folder too, and never "
            "touches either). Turning it off keeps that folder on disk, and deleting the load order deletes it."
        ),
    },
    {
        "name": "Offline mods",
        "short": "Gives a load order its own frozen copy of chosen mods, which Steam updates no longer change.",
        "long": (
            "With the load order's Own game data on, click Offline mods (right under Rescan) to tick the mods to "
            "copy into the load order, or right-click a single mod and choose Make Offline; Make live again (or "
            "Delete on an Offline mod) deletes the copy, and works even with Own game data off. For that load "
            "order only, VOLT uses the copy instead of the live mod, and an Offline badge marks it; when the live "
            "mod changes later, the row's tooltip, the details pane and the dialog's Live column say so, and "
            "Refresh Offline copy (or Refresh changed) copies it afresh. " + OFFLINE_RUN_TEXT
        ),
    },
]
