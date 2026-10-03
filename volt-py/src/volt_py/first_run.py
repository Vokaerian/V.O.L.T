"""First-run guidance (PLAN.md §10 (c)-(g), v0.6.23): the plain words and
the Qt-free state behind it - the empty-state card in the Active pane, the
"needs a profile" tooltips, the first-open "Create your first profile?"
prompt and the get-started checklist (Thunderstore games), and the
game-select welcome panel. The widgets are screens/first_run_widgets.py;
each screen decides when to show them from the functions below, so
tools/checks/volt_py_first_run.py tests every rule without Qt.

Audience: someone who has never modded a game. No jargon in anything here.
Thunderstore games say "profile" (0.6.22); RimWorld keeps "load order".
"""

# ---- the empty-state card (Active pane, no profile / load order open) ----
# Thunderstore wording approved by the user verbatim (2026-10-03).
PROFILE_CARD = {
    "title": "Let's set up your first profile.",
    "body": (
        "A profile is your own saved list of mods for {game}. Make one to get started. "
        "You can make more later and switch between them."
    ),
    "create": "Create a profile",
    "import": "Import one someone shared",
}
# RimWorld's, in its own vocabulary (drafted 0.6.23, awaiting the user's OK).
LOAD_ORDER_CARD = {
    "title": "Let's set up your first load order.",
    "body": (
        "A load order is your own saved list of mods for {game}, in the order the game loads them. "
        "Make one to get started. You can make more later and switch between them."
    ),
    "create": "Create a load order",
    "import": "Import one someone shared",
}

# ---- tooltips of controls disabled only because nothing is open ----
NO_PROFILE_TIP = "Create a profile first."
NO_LOAD_ORDER_TIP = "Create a load order first."

# ---- the first-open prompt (Thunderstore games, zero profiles) ----
FIRST_PROFILE_TITLE = "Create your first profile?"
FIRST_PROFILE_TEXT = (
    "VOLT will set up a fresh profile for {game}. This downloads the mod loader (a small download) "
    "and takes a minute."
)
FIRST_PROFILE_NAME = "Default"
FIRST_PROFILE_OK = "Create"
FIRST_PROFILE_CANCEL = "Not now"

# ---- the get-started checklist (Thunderstore games) ----
CHECKLIST_TITLE = "Get started"
# The fourth step names the button as it reads on screen ("Modded"; the
# brief said "Press Run" - there is no Run button on these screens).
STEPS = (
    "Tell VOLT where {game} is installed",
    "Create a profile",
    "Add some mods",
    "Press Modded to play",
)
STEP_TIPS = (
    "Open Settings and choose the folder {game} is installed in.",
    "Make a new profile (the same as the New profile... button).",
    "Open Browse Mods to find mods for {game} and add them to this profile.",
    "Press Modded, at the bottom right, to start {game} with your mods. "
    "This step ticks itself off after the first time.",
)
STEP_DONE_TIP = "Done."
HIDE_LABEL = "Hide"
HIDE_TIP = "Hide this checklist. It won't come back for {game}."

# ---- the welcome panel (game select, once) ----
WELCOME_TITLE = "Welcome to VOLT."
WELCOME_BODY = (
    "VOLT helps you add mods to your games and keep them organised, so you can try different setups "
    "without breaking anything. Pick a game below to begin."
)
WELCOME_OK = "Got it"


def fill(texts: dict, game: str) -> dict:
    """`texts` with "{game}" replaced (plain replace, as the Help entries)."""
    return {k: v.replace("{game}", game) for k, v in texts.items()}


def show_card(*, game_found: bool, open_slug, active_rows: int) -> bool:
    """The empty-state card shows in the Active pane's empty dot grid while
    the game is found, nothing is open and the Active list has no rows
    (RimWorld can fill Active with no load order open: no card over rows)."""
    return bool(game_found) and open_slug is None and active_rows == 0


def needs_profile_tip(*, game_found: bool, busy: bool, open_slug) -> bool:
    """A control that needs a profile is disabled *only* for want of one:
    the game is found, nothing else is running, nothing is open. Any other
    reason (no game, busy) keeps the control's own tooltip."""
    return bool(game_found) and not busy and open_slug is None


def first_profile_prompt(*, game_found: bool, busy: bool, profiles: int) -> bool:
    """Ask "Create your first profile?" when the manager opens: game found,
    idle, and not one profile yet."""
    return bool(game_found) and not busy and profiles == 0


def checklist(*, game_found: bool, profiles: int, mods: int, launched: bool, dismissed: bool) -> dict:
    """The four steps' state, derived live except `launched` / `dismissed`
    (settings has_launched / checklist_dismissed): done (4 bools), next
    (index of the first step not done, None when all are), visible (not
    dismissed and something left to do). `mods` = mods in the open profile
    beyond the framework (0 with none open)."""
    done = (bool(game_found), profiles > 0, mods > 0, bool(launched))
    nxt = next((i for i, d in enumerate(done) if not d), None)
    return {"done": done, "next": nxt, "visible": not dismissed and nxt is not None}
