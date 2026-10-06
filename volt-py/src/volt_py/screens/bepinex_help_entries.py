"""The Help window's entries (screens/help_window.py) for every Thunderstore/
BepInEx game's manager screen (screens/bepinex_main_screen.py). Since 0.6.24
(PLAN.md §10 (h)) written as tasks ("How do I add a mod?") in plain words,
not one entry per button: every button and feature is still named in some
entry, and the row right-click menu keeps one grouped entry, as RimWorld's
(rimworld_help_entries.py).

0.6.28 (PLAN.md §11 (g)): every name is a short question - "How do I
<task>?" or "What ...?" - of at most NAME_MAX characters, so it
fits the Help rail (240px) on one line; no game name in a name.
"long" is plain-text paragraphs (blank line between) and list lines
("1. " steps, "- " items) that help_window.TextBlocks lays out; button and
menu names are quoted as on screen (a trailing "..." left off).

Plain data, no Qt. The window sorts by name itself (the "How do I" entries
group together, then the "What is" ones); kept here in a getting-going ->
mods -> sharing -> trouble order. Update an entry whenever a feature it
describes changes.

Shared by every game in bepinex_games.GAMES: "{game}" becomes the game
module's NAME and "{example_package}" its EXAMPLE_PACKAGE (a well-known
Team-Package of that community); Steam is literal - every Thunderstore game
here is Steam-only (paths.find_steam_app, bepinex_launch). A game whose
screen truly differs sets, in its own module, HELP_OVERRIDES (entry name ->
the fields to replace, same placeholders) and/or HELP_EXTRA (whole entries
appended at the end). Valheim needs neither: help_entries(valheim) is,
string for string, the old VALHEIM_HELP_ENTRIES
(tools/checks/volt_py_bepinex_games.py).
"""


NAME_MAX = 28  # the rail's one-line cap (tools/checks/volt_py_help_window.py measures it)


def _fill(text: str, values: dict) -> str:
    # Plain replace, not str.format: an entry's text may hold literal braces.
    # A value ending in "." (R.E.P.O.) at a sentence's end keeps one full stop.
    for key, value in values.items():
        text = text.replace("{" + key + "}.", value.rstrip(".") + ".").replace("{" + key + "}", value)
    return text


def help_entries(game) -> list[dict]:
    """`game`'s Help entries: BEPINEX_HELP_ENTRIES with its HELP_OVERRIDES
    merged in by name, then its HELP_EXTRA, every string filled from it."""
    values = {"game": game.NAME, "example_package": game.EXAMPLE_PACKAGE}
    overrides = getattr(game, "HELP_OVERRIDES", {})
    entries = [{**e, **overrides.get(e["name"], {})} for e in BEPINEX_HELP_ENTRIES]
    entries += list(getattr(game, "HELP_EXTRA", ()))
    return [{k: _fill(v, values) for k, v in e.items()} for e in entries]


BEPINEX_HELP_ENTRIES: list[dict] = [
    # ---- getting going ----
    {
        "name": "How do I get started?",
        "short": "Tell VOLT where {game} is, make a profile, add some mods, then press Modded to play.",
        "long": (
            "The \"Get started\" list under the profile bar walks you through those four steps and ticks each one "
            "off. Click a step to go straight to it, or press \"Hide\" to put the list away for good.\n\n"
            "While you have no profile, the empty Active list shows a card with \"Create a profile\" and \"Import "
            "one someone shared\".\n\n"
            "Point at any greyed-out button to see why it's greyed out (\"Create a profile first.\", for example)."
        ),
    },
    {
        "name": "How do I find the game?",
        "short": "Open Settings and press Autodetect, or press Browse and pick the game folder.",
        "long": (
            "1. Press \"Settings\" at the top of the window.\n"
            "2. On the \"General\" tab, press \"Autodetect paths\". It looks in Steam's usual library folders.\n"
            "3. If that doesn't find {game}, press \"Browse\" and pick the game folder yourself.\n\n"
            "To find the folder, right-click {game} in Steam and choose Manage > Browse local files.\n\n"
            "That's the only folder VOLT needs: your mods live in VOLT's own folder, never inside the game. "
            "The \"Game\" link next to \"Paths:\" at the top opens the game folder, and the line under the links "
            "shows the full paths."
        ),
    },
    {
        "name": "How do I change settings?",
        "short": "Press Settings at the top of the window.",
        "long": (
            "Settings has three tabs:\n"
            "- \"General\": the game folder (\"Browse\", \"Autodetect paths\"), Animations (on, off, or follow "
            "Windows) and \"Open data folder\", which shows VOLT's own folder for {game}.\n"
            "- \"Launch\": extra start options for the game, like -console, used by both \"Modded\" and "
            "\"Vanilla\".\n"
            "- \"Troubleshooting\": open or copy VOLT's log, copy a short summary for a bug report, free up space "
            "with \"Clean up downloads\", and \"Reset installation\" for a damaged game install."
        ),
    },
    {
        "name": "What is a profile?",
        "short": "A profile is your own saved list of mods for {game}, and you can have as many as you like.",
        "long": (
            "Each profile has its own copy of the mod loader, its own mods and its own mod settings, all kept in "
            "VOLT's folder. Switching between profiles is instant and nothing is copied around.\n\n"
            "Pick one in the \"Profile\" drop-down at the top. If the open one has unsaved changes, VOLT asks "
            "first.\n\n"
            "The \"Profile\" link next to \"Paths:\" opens the open profile's folder."
        ),
    },
    {
        "name": "How do I make a profile?",
        "short": "Press New profile, type a name, and VOLT sets it up for you.",
        "long": (
            "VOLT downloads the mod loader (BepInEx) from Thunderstore, or reuses one it already has, so the new "
            "profile is ready to play right away.\n\n"
            "\"Copy to new\" makes a copy of the open profile instead: its mods, their settings, and any changes "
            "you haven't saved yet.\n\n"
            "To delete a profile, right-click the \"Profile\" drop-down and choose \"Delete\". Its mods are "
            "removed from disk after you confirm; the game itself isn't touched."
        ),
    },
    # ---- mods ----
    {
        "name": "How do I add a mod?",
        "short": "Press Browse Mods, find the mod, and press Install.",
        "long": (
            "\"Browse Mods\" searches Thunderstore, the site {game} mods come from. Type a name, pick a category, "
            "or change the sort order.\n\n"
            "\"Install\" adds the mod, plus any other mods it needs, to your Active list. The browser stays open "
            "so you can keep going.\n\n"
            "Click a mod's card to read about it, see which mods it needs, or pick an older version. \"Back to "
            "results\", Esc or Backspace go back, and the X closes the browser. \"Show deprecated\" and \"Show "
            "NSFW\", next to the X, add those mods to the results.\n\n"
            "If you already know a mod's name (like {example_package}) or its thunderstore.io address, \"Add "
            "mod\" installs it straight away.\n\n"
            "While mods download, a download bar at the bottom right of the screen and of the browser shows which "
            "mod VOLT is getting and how many of them are done."
        ),
    },
    {
        "name": "How do I turn off a mod?",
        "short": "Click its switch to turn it off, double-click it to move it to Inactive, or right-click it and choose Uninstall.",
        "long": (
            "The switch at the right of an Active mod turns it off but keeps its place. A switched-off mod shows "
            "a yellow \"Disabled\" label.\n\n"
            "Double-clicking moves a mod between the Active and Inactive lists. Inactive mods stay downloaded, so "
            "moving one back is instant.\n\n"
            "\"Enable all\" and \"Disable all\" (under \"Export\") flip every switch at once.\n\n"
            "None of this takes effect until you press \"Save\". \"Uninstall\" is different: it removes the mod "
            "from this profile right away (its settings files are kept)."
        ),
    },
    {
        "name": "How do I save my changes?",
        "short": "Press Save, which turns yellow while you have unsaved changes.",
        "long": (
            "\"Save\" writes your Active list and every switch into the profile, so the game uses them next time. "
            "Nothing is downloaded and the game folder isn't touched.\n\n"
            "Undo (the ↺ next to \"Unsaved changes\", or Ctrl+Z) takes back your last change, one step at a "
            "time.\n\n"
            "\"Rescan\" reads the profile from disk again and checks for updates. It asks first if that would "
            "drop unsaved changes."
        ),
    },
    {
        "name": "How do I play with mods?",
        "short": "Press Modded to start {game} with the open profile, or Vanilla to start it without any mods.",
        "long": (
            "\"Modded\" copies two small mod loader files into the {game} folder and starts the game through "
            "Steam. It removes them again when you quit, so your game install stays as it was.\n\n"
            "\"Vanilla\" needs no profile and copies nothing.\n\n"
            "VOLT locks its buttons while the game runs, and picks a running game up again if you reopen it.\n\n"
            "Neither button saves. With unsaved changes \"Modded\" asks first, and it also asks before starting "
            "with mods that are missing a mod they need."
        ),
    },
    {
        "name": "How do I update my mods?",
        "short": "Press Update all at the right of the profile bar, or the yellow ↑ on a single mod.",
        "long": (
            "VOLT checks Thunderstore for newer versions when this screen opens, when you switch profiles, after "
            "you add or remove a mod, and on \"Rescan\".\n\n"
            "While updates are waiting, \"Update all\" turns yellow and shows how many. \"Update check failed · "
            "Retry\" means Thunderstore couldn't be reached.\n\n"
            "Updating keeps each mod's settings and never changes which mods are switched on.\n\n"
            "A red \"Deprecated\" label means the mod's author no longer looks after it."
        ),
    },
    {
        "name": "How do I search my mods?",
        "short": "Type in the search box above the list.",
        "long": (
            "It matches a mod's name, its author or its Thunderstore name. The eye at the end of the box switches "
            "between hiding the mods that don't match and just dimming them.\n\n"
            "You can drag mods up and down the Active list, but the order is only for you: the mod loader works "
            "out the real load order itself. Dragging is off while the search is hiding mods.\n\n"
            "Each mod shows its icon from Thunderstore, or a plain square if VOLT has none for it."
        ),
    },
    {
        "name": "How do I edit mod settings?",
        "short": "Press Config, or right-click a mod and choose Edit config.",
        "long": (
            "\"Config\" lists the settings files the open profile's mods have written. Click one to change it.\n\n"
            "Most files become a form, with a description for each setting; others show as plain text.\n\n"
            "- \"Save\" writes your changes.\n"
            "- \"Revert\" drops them.\n"
            "- \"Delete\" removes the file (the mod writes a fresh one next time).\n"
            "- \"Open externally\" opens it in your usual editor.\n\n"
            "A mod only writes its settings file after the game has been started with it once."
        ),
    },
    {
        "name": "What's the right-click menu?",
        "short": "Right-click any mod for its folder, its Thunderstore page, its settings and more.",
        "long": (
            "- \"Open folder\" shows the mod's files.\n"
            "- \"Open on Thunderstore\" and \"Open website\" open its pages.\n"
            "- \"Copy Thunderstore name\" copies its name in the Author-ModName form.\n"
            "- \"Edit config\" opens its settings files.\n"
            "- \"Install missing required mods\" fetches the mods it needs.\n"
            "- \"Update\" installs a newer version when there is one.\n"
            "- \"Reinstall\" puts the same version back if its files went missing.\n"
            "- \"Uninstall\" removes it from this profile after you confirm.\n\n"
            "Options that can't be used right now are greyed out."
        ),
    },
    {
        "name": "What are required mods?",
        "short": "Many mods need other mods to work (their dependencies), and VOLT installs those for you.",
        "long": (
            "Adding a mod also installs every mod it needs that you don't have yet.\n\n"
            "If one goes missing later, the ⚠ / ✕ button above \"Save\" shows it. ✕ means not installed; ⚠ means "
            "installed but inactive or switched off.\n\n"
            "Click that button for the list. It has an \"Install\" button for each missing mod and \"Install all "
            "missing\" at the top.\n\n"
            "Fix a ⚠ by switching the needed mod back on or moving it to Active.\n\n"
            "The same button also warns about mods that get in each other's way: see \"What are conflict warnings?\"."
        ),
    },
    {
        "name": "What are conflict warnings?",
        "short": "Some mods get in each other's way, and VOLT tells you before you launch.",
        "long": (
            "VOLT checks the switched-on mods in the Active list for mods that get in each other's way, and lists "
            "what it finds under the ⚠ / ✕ button above \"Save\":\n"
            "- \"Incompatible mod\" (✕): a mod says it won't run beside another one, so the mod loader skips it.\n"
            "- \"Shared files differ\" (⚠): two mods bring different copies of the same file.\n"
            "- \"Possible duplicate\" (⚠): two mods look like copies of the same mod.\n\n"
            "VOLT only advises: it never switches anything off for you. Click the button to see what each warning "
            "means and what to try.\n\n"
            "\"Needed by\" in a mod's details shows which installed mods rely on it, which helps you decide which "
            "one to keep."
        ),
    },
    {
        "name": "What is BepInEx?",
        "short": "BepInEx is the mod loader: the part that lets {game} load mods at all.",
        "long": (
            "Every profile has its own copy, pinned at the top of the Active list. It can't be moved, switched "
            "off or removed, and it gets updates like any mod.\n\n"
            "The \"BepInEx\" link next to \"Paths:\" opens its folder in the open profile: plugins holds your mods "
            "and config their settings.\n\n"
            "If {game}'s own folder already has BepInEx in it, VOLT asks before starting the game and leaves that "
            "copy alone."
        ),
    },
    # ---- sharing ----
    {
        "name": "How do I share my profile?",
        "short": "Press Export and choose Export to file or Export as code.",
        "long": (
            "\"Export to file\" saves a .r2z file (the profile format VOLT, r2modman and Thunderstore Mod Manager "
            "all read) with your mod list, versions, switches and mod settings. The mods themselves aren't in it: "
            "they download again on the other computer.\n\n"
            "\"Export as code\" uploads the same thing to Thunderstore and gives you a short code to send. Anyone "
            "with the code can get it and it can't be taken back, so leave out private settings like server "
            "passwords.\n\n"
            "\"Dependency strings\" is for modpack makers: it lists your mods as Author-ModName-Version lines."
        ),
    },
    {
        "name": "How do I import a profile?",
        "short": "Press Import and choose Import from file or Import from code.",
        "long": (
            "With a profile open, VOLT asks whether to add it as a new profile or replace the open one. A "
            "replacement only happens once the import has finished, so if it fails your profile stays as it "
            "was.\n\n"
            "VOLT sets up the mod loader, downloads every mod at the version in the file (or the newest one, if "
            "that version is gone) and puts the mod settings in place, so you need an internet connection.\n\n"
            "A profile made for another game is refused.\n\n"
            "\"Local mod (.zip)\" is different: it installs one mod from a Thunderstore .zip on your computer, "
            "and that mod is never checked for updates."
        ),
    },
    # ---- trouble ----
    {
        "name": "How do I fix a broken mod?",
        "short": "Press Troubleshoot first; if it finds nothing, switch mods off in groups until the problem goes away.",
        "long": (
            "Start with \"Troubleshoot\" at the top right. It reads the game's log from the last launch of this "
            "profile and tells you which mod went wrong, and what to try.\n\n"
            "To find the mod causing it yourself:\n"
            "1. Switch off the mod you added last, or half of your mods.\n"
            "2. Press \"Save\", then \"Modded\", and see if the problem is gone.\n"
            "3. Switch mods back on in smaller groups until you find the one.\n\n"
            "The ⚠ / ✕ button above \"Save\" lists mods that are missing a mod they need, and conflict warnings: "
            "mods that block each other or look like two copies of the same mod. A mod marked \"Files missing\" "
            "lost some of its files outside VOLT (deleted, or moved away by an antivirus program). Right-click it and choose \"Reinstall\" to put them back.\n\n"
            "\"Update all\" often helps, and \"Config\" lets you change a mod's settings.\n\n"
            "If the game itself seems damaged, Settings > Troubleshooting > \"Reset installation\" deletes the "
            "game folder and has Steam download it again. Your profiles are kept."
        ),
    },
    {
        "name": "What does Troubleshoot do?",
        "short": "It reads the game's log from your last launch and explains, in plain words, what went wrong.",
        "long": (
            "Press \"Troubleshoot\" at the top right after a launch with \"Modded\". VOLT reads the log the game "
            "wrote, groups the same error into one row, and for each problem says what happened, what it means and "
            "what to try.\n\n"
            "The first error of the run is listed first: later problems often follow from it, so fix that one "
            "first. Tick \"Show harmless messages too\" to see messages that are known not to matter.\n\n"
            "A word on each problem says how sure VOLT is:\n"
            "- certain: the log or the mods' files prove it.\n"
            "- likely: the error points at that mod, but another mod may still be the cause.\n"
            "- possible: a warning, or the error names no mod.\n\n"
            "VOLT keeps your last 10 launches with \"Modded\". Pick one next to \"Last run\":\n"
            "- \"What changed since it last worked\" lists the mods added, removed, updated or switched on or off "
            "since your last run that worked (or the run before it). Problems that weren't there then say "
            "\"New since\".\n"
            "- A run \"probably worked\" when the mods finished loading and you played 5 minutes or more.\n"
            "- Mark a run \"worked\" or \"didn't work\" if VOLT got it wrong: your mark always wins.\n\n"
            "The \"Mod contents\" tab shows what each mod's files are made of, and warns when two mods contain "
            "copies of the same code. VOLT only gives advice: it never changes your profile by itself. \"Copy "
            "summary\" copies the findings, without your folder paths, to paste when you ask someone for help."
        ),
    },
    {
        "name": "What are patch details?",
        "short": "A one-off recording of which game code each mod changes, shown in Troubleshoot's \"Mod contents\" tab.",
        "long": (
            "Tick \"Record patch details on next launch\" in Settings > Troubleshooting, or press that button in "
            "Troubleshoot > \"Mod contents\". Then start the profile with \"Modded\" and wait for the main menu.\n\n"
            "For that one launch the mod loader writes down every game method a mod changes. When the game has "
            "closed, VOLT reads that into a list: \"Game methods\" shows which mods change the same part of the "
            "game, and each mod shows the game code it changes.\n\n"
            "It switches itself off after that launch and puts the mod loader's own setting back, even if VOLT or "
            "the game was closed in between. That launch's log file is about 5 times bigger than usual; the next "
            "launch writes a normal one again.\n\n"
            "It's safe: your mods and their settings don't change. Changes made with MonoMod hooks aren't in the "
            "list."
        ),
    },
    {
        "name": "How do I get help?",
        "short": "Press Report a problem at the top of this window and send the file it saves to whoever is helping you.",
        "long": (
            "The file is a .zip with VOLT's log for {game} (a step-by-step record of what VOLT did) and a short "
            "note with VOLT's version, your Windows version and the profile name.\n\n"
            "When something fails, the message has a \"Copy details\" button that copies the technical details to "
            "paste into a message.\n\n"
            "Settings > Troubleshooting can also open or copy the log."
        ),
    },
]
