"""RimWorld's entries for the Help window (screens/help_window.py). Since
0.6.24 (PLAN.md §10 (h)) written as tasks ("How do I add a mod?") in plain
words, not one entry per button; RimWorld keeps its own words (load order,
Workshop, Push, Sync, SteamCMD). Every button and feature is still named in
some entry, and the mod right-click menu keeps one grouped entry (decided
with the user, PLAN.md §7 / RIMWORLD.md).

0.6.28 (PLAN.md §11 (g)): every name is a short question - "How do I
<task>?" or "What ...?" - of at most NAME_MAX characters, so it
fits the Help rail (240px) on one line; no game name in a name.
"long" is plain-text paragraphs (blank line between) and list lines
("1. " steps, "- " items) that help_window.TextBlocks lays out; button and
menu names are quoted as on screen (a trailing "..." left off).

Plain data, no Qt. The window sorts by name itself (the "How do I" entries
group together, then the "What" ones); kept here in a getting-going ->
mods -> playing -> sharing -> trouble order. Update an entry whenever a
feature it describes changes.
"""

NAME_MAX = 28  # the rail's one-line cap (tools/checks/volt_py_help_window.py measures it)

RIMWORLD_HELP_ENTRIES: list[dict] = [
    # ---- getting going ----
    {
        "name": "How do I get started?",
        "short": "Tell VOLT where RimWorld is, make a load order, then press Modded to play.",
        "long": (
            "1. Open \"Settings\" and press \"Autodetect paths\" to find RimWorld and its Config folder.\n"
            "2. Press \"New load order\". While you have none, the empty Active list shows a card with the same "
            "button.\n"
            "3. Move the mods you want into the Active list and put them in order.\n"
            "4. Press \"Save\", then \"Push\" or \"Modded\".\n\n"
            "Point at any greyed-out button to see why it's greyed out (\"Create a load order first.\", for "
            "example)."
        ),
    },
    {
        "name": "How do I change settings?",
        "short": "Press Settings at the top of the window.",
        "long": (
            "Settings has three tabs:\n"
            "- \"General\": RimWorld's game, local mods and Config folders (\"Browse\", or \"Autodetect paths\" to "
            "find them) and Animations (on, off, or follow Windows).\n"
            "- \"Steam\": how Workshop mods are downloaded. \"Check for missing Workshop mods\" downloads every "
            "active mod that isn't on your computer yet.\n"
            "- \"Troubleshooting\": opens VOLT's log, a step-by-step record of what VOLT did.\n\n"
            "The links next to \"Paths:\" at the top open the Game, Mods, Config and load order folders. They're "
            "greyed out until that folder is known."
        ),
    },
    {
        "name": "What is a load order?",
        "short": "A load order is your own saved list of mods for RimWorld, in the order the game loads them.",
        "long": (
            "Mods near the top of the Active list load first, and some mods only work when they load after "
            "others.\n\n"
            "You can have as many load orders as you like. Pick one in the drop-down at the top; VOLT asks first "
            "if the open one has unsaved changes.\n\n"
            "Each one is saved as its own folder in VOLT's folder. The \"Load order\" link next to \"Paths:\" "
            "opens it."
        ),
    },
    {
        "name": "How do I make a load order?",
        "short": "Press New load order and type a name.",
        "long": (
            "It starts with Core and your DLC in the Active list and every other mod in Inactive.\n\n"
            "\"Copy to new\" saves what's on screen right now (unsaved changes included) as a new load order, "
            "with its own copies of any Offline mods.\n\n"
            "To delete a load order, right-click the drop-down and choose \"Delete\". Its own game data and "
            "Offline copies go with it, but your mods aren't touched."
        ),
    },
    # ---- mods ----
    {
        "name": "How do I add a mod?",
        "short": "Subscribe to it on the Steam Workshop, press Rescan, then double-click it in the Inactive list.",
        "long": (
            "1. Subscribe to the mod on the Steam Workshop.\n"
            "2. Press \"Rescan\". VOLT looks through your mod folders again (do this whenever you add, remove or "
            "update mods while VOLT is open).\n"
            "3. Double-click the mod in the Inactive list. Double-clicking moves a mod between the Inactive and "
            "Active lists.\n\n"
            "You can also paste a Workshop link or ID into \"Import\" > \"From Steam Workshop\".\n\n"
            "A mod that's in your list but not on your computer shows as pending, with a \"Download\" or "
            "\"Subscribe\" button on its row. A mod you install by hand goes in the game's Mods folder."
        ),
    },
    {
        "name": "How do I sort my mods?",
        "short": "Press Sort, or drag mods up and down the Active list.",
        "long": (
            "\"Sort\" follows your own rules first, then community rules, each mod's own load-order rules, the "
            "mods it needs, and finally the alphabet.\n\n"
            "To add your own rule for a mod, right-click it and choose \"Rules\".\n\n"
            "Undo (the ↺ while you have unsaved changes, or Ctrl+Z) takes back one change at a time, and "
            "\"Save\" keeps the new order. Dragging is off while a search is hiding mods."
        ),
    },
    {
        "name": "How do I search my mods?",
        "short": "Type in the search box above the list.",
        "long": (
            "It matches a mod's name, author or package ID (the mod's unique name inside RimWorld). The eye at "
            "the end of the box switches between hiding the mods that don't match and just dimming them.\n\n"
            "Right-click a mod and choose \"Filter by\" to show only mods by the same author or with the same "
            "color.\n\n"
            "\"Mod color\", in the same menu, tags a mod with a color."
        ),
    },
    {
        "name": "How do I save my changes?",
        "short": "Press Save, which is outlined in yellow while you have unsaved changes.",
        "long": (
            "\"Save\" keeps the load order in VOLT.\n\n"
            "RimWorld doesn't use it until you press \"Push\", or \"Modded\" for a load order with its own game "
            "data.\n\n"
            "Saving also clears the undo history."
        ),
    },
    # ---- playing ----
    {
        "name": "How do I play with mods?",
        "short": "Press Push to make RimWorld use your load order, then start the game, or press Modded.",
        "long": (
            "\"Push\" saves the load order and writes it into RimWorld's ModsConfig.xml (the file in the Config "
            "folder that RimWorld reads its mod list from), keeping a backup of the old one.\n\n"
            "\"Modded\" starts RimWorld with the last pushed list, or with the load order's own list when its "
            "own game data is on. It never saves or pushes for you and warns about unsaved changes.\n\n"
            "\"Vanilla\" starts a clean RimWorld with only Core and your DLC, in its own data folder, so your "
            "usual saves aren't touched.\n\n"
            "VOLT locks its buttons while the game runs."
        ),
    },
    {
        "name": "How do I separate saves?",
        "short": "Right-click the load order drop-down and turn on Own game data.",
        "long": (
            "With it on, \"Modded\" keeps that load order's saves, settings and mod settings in its own folder. "
            "It starts fresh with no saves; your usual ones stay where they are.\n\n"
            "Turning it off keeps that folder on disk, and deleting the load order deletes it.\n\n"
            "It's off for new load orders."
        ),
    },
    {
        "name": "How do I stop mod updates?",
        "short": "Make it Offline: the load order gets its own frozen copy that Steam updates don't change.",
        "long": (
            "1. Turn on the load order's \"Own game data\".\n"
            "2. Press \"Offline mods\" (under \"Rescan\") and tick the mods to copy, or right-click a mod and "
            "choose \"Make Offline\".\n\n"
            "VOLT uses that copy for this load order only, marked with an Offline badge, and tells you when the "
            "live mod has changed. \"Refresh Offline copy\" (or \"Refresh changed\") copies it again.\n\n"
            "\"Make live again\" (or \"Delete\" on an Offline mod) deletes the copy.\n\n"
            "When you press \"Modded\", the Offline mods are linked into the game's Mods folder and removed when "
            "the game closes."
        ),
    },
    # ---- Steam ----
    {
        "name": "How do I use SteamCMD?",
        "short": "Choose a SteamCMD option in Settings > Steam, then press Download on a mod's row.",
        "long": (
            "SteamCMD is Valve's own download tool. VOLT uses it to put Workshop mods straight into the Mods "
            "folder, without the Steam app.\n\n"
            "Its progress shows at the bottom of the window, where you can pause and resume it.\n\n"
            "\"Sync\" then turns those downloads into real Steam subscriptions and removes VOLT's copies once "
            "Steam has its own (Steam must be running).\n\n"
            "For a GOG copy of RimWorld, VOLT keeps the downloads in the Mods folder for good, and \"Fetch\" puts "
            "a missing mod back from VOLT's downloads."
        ),
    },
    {
        "name": "How do I remove a mod?",
        "short": "Right-click the mod and choose Unsubscribe, Delete or Remove completely.",
        "long": (
            "- \"Unsubscribe\" removes a Steam subscription.\n"
            "- \"Delete\" removes a mod VOLT downloaded with SteamCMD.\n"
            "- \"Remove completely\" lists every copy VOLT can find first, then deletes them and takes the mod out "
            "of the load order. Tick the box to also delete VOLT's saved download.\n\n"
            "\"Remove completely\" won't remove Core, your DLC, or a mod Steam still has you subscribed to "
            "(unsubscribe first)."
        ),
    },
    {
        "name": "What's the right-click menu?",
        "short": "Right-click any mod in either list for more things you can do with it.",
        "long": (
            "The grey line at the top says where the mod comes from (Steam Workshop, SteamCMD copy, Local mod and "
            "so on). Options that don't apply are greyed out.\n\n"
            "- \"Open folder\" shows its files; \"Open URL in browser\" and \"Open URL in Steam\" open its "
            "Workshop page.\n"
            "- \"Copy to clipboard\" copies its link, package ID or folder.\n"
            "- \"Filter by\" and \"Mod color\" are for searching, and \"Rules\" adds your own sort rules.\n"
            "- \"Make Offline\", \"Make live again\" and \"Refresh Offline copy\" handle Offline copies.\n"
            "- \"Download\" or \"Subscribe\", \"Unsubscribe\", \"Delete\", \"Fetch\" and \"Remove completely\" get "
            "or remove the mod's files."
        ),
    },
    # ---- sharing ----
    {
        "name": "How do I share a load order?",
        "short": "Press Export and choose Rentry, Clipboard or .xml.",
        "long": (
            "- \"Rentry (share link)\" puts your list on a rentry.co page and copies its link for you to send.\n"
            "- \"Clipboard (RimSort)\" copies the list as text in RimSort's format.\n"
            "- \".xml (RimPy)\" saves a file RimPy can open.\n\n"
            "\"Export\" is greyed out while the Active list is empty."
        ),
    },
    {
        "name": "How do I import a mod list?",
        "short": "Press Import and choose where the list comes from.",
        "long": (
            "You can import from the clipboard, a RimPy .xml file, a rentry.co page, a save file's mod list "
            "(\"Read from save\"), or the Steam Workshop.\n\n"
            "A Workshop collection asks whether to add to your list, replace it, or start a new load order.\n\n"
            "Import fills the Active list of the open load order, so it needs one open. VOLT asks before "
            "replacing unsaved changes."
        ),
    },
    # ---- trouble ----
    {
        "name": "How do I fix a broken mod?",
        "short": "Check the warnings button, press Sort, and test with fewer mods until the problem goes away.",
        "long": (
            "The ⚠ / ✕ button lists mods in the wrong order (warnings, which \"Sort\" usually fixes) and mods "
            "that are missing a mod they need or clash with another (errors).\n\n"
            "To find the mod causing it:\n"
            "1. Move half of your mods to Inactive.\n"
            "2. Press \"Save\", then \"Push\", and test the game.\n"
            "3. Bring mods back in smaller groups until you find the one.\n\n"
            "\"Vanilla\" checks whether RimWorld itself works without any mods."
        ),
    },
    {
        "name": "What are scan issues?",
        "short": "Mod folders VOLT couldn't read as mods; the button only shows when there are some.",
        "long": (
            "The button says how many, like \"2 scan issues\".\n\n"
            "Its window explains each one: a missing folder, a folder with no About.xml (the file that describes "
            "a mod), an About.xml that can't be read, or two mods with the same package ID.\n\n"
            "From there you can open the folder, or ignore the issue so it stops showing."
        ),
    },
    {
        "name": "How do I get help?",
        "short": "Press Report a problem at the top of this window and send the file it saves to whoever is helping you.",
        "long": (
            "The file is a .zip with VOLT's log for RimWorld (a step-by-step record of what VOLT did) and a short "
            "note with VOLT's version, your Windows version and the load order's name.\n\n"
            "When something fails, the message has a \"Copy details\" button that copies the technical details to "
            "paste into a message.\n\n"
            "Settings > Troubleshooting can also open the log."
        ),
    },
]
