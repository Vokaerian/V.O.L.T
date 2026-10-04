"""Words and Qt-free decisions for the self-update UI (0.6.30, PLAN.md §12;
screens/update_dialog.py + the Settings "Updates" rows): the dialog's
headline, the release notes as paragraphs / headings / list rows for
help_window.TextBlocks(markup=True) + the full-notes link, Settings' status line, the download counter, the
busy reason, the failed-apply notice, and the two worker bodies (the
startup check, the manual check). Stdlib + volt_py.update only, so
tools/checks/volt_py_update_ui.py runs it headless (the first_run.py /
first_run_widgets.py split).
"""

import re
import threading
from datetime import datetime

from volt_py import update
from volt_py.applog import log

TITLE = "Update VOLT"
NOTES_HEADING = "What's new"
NO_NOTES = "This release has no notes."
NOTES_LINK = "Full release notes on GitHub"
UPDATE_NOW = "Update now"
OPEN_PAGE = "Open releases page"
LATER = "Later"
SKIP = "Skip this version"
CANCEL = "Cancel"
CANCELLING = "Cancelling..."
CHECK = "Check for updates"
CHECKING = "Checking..."
CHECK_ON_START = "Check for updates when VOLT starts"
CHECK_ON_START_TIP = "Once per start, a second after the window opens. Never updates anything without asking."
SETTINGS_NOTE = ("VOLT checks GitHub for a newer version and asks before installing it. "
                 "Your games, profiles and settings are kept.")
CHECKING_LINE = "Checking GitHub for a newer VOLT..."
UNPACKING = "Checking and unpacking the update..."
UNPACKING_DETAIL = "This takes a few seconds."
RESTARTING = "Restarting VOLT..."
RESTARTING_DETAIL = ("VOLT closes now and opens again by itself in a few seconds, as the new version. "
                     "Your games, profiles and settings are kept.")
ERROR_TITLE = "Update"
CHECK_ERROR_TITLE = "Check for updates"
FAILED_APPLY_TITLE = "Update didn't finish"

# Both managers' Games-button tooltip while it is disabled (SCOPE.md §3: busy,
# a game running, a SteamCMD download...). The update dialog reuses that rule
# and its reason: VOLT can't restart while it couldn't leave the manager.
GAMES_BLOCK_PREFIX = "Can't go back to game select "
UPDATE_BLOCK_PREFIX = "Can't update VOLT "
BUSY_FALLBACK = "Can't update VOLT while this manager is busy. Let it finish first."

MB = 1024 * 1024
CLEANUP_WAIT_S = 30
# Set once the startup worker's cleanup_leftovers() is done, so a download
# started in the first seconds never lands in an update/ folder being emptied.
CLEANUP_DONE = threading.Event()


def version_text(version) -> str:
    """(0, 6, 31) / "v0.6.31" -> "0.6.31"."""
    if isinstance(version, tuple):
        return ".".join(str(p) for p in version)
    return str(version).strip().lstrip("v")


def headline(new, current: str) -> str:
    return f"VOLT {version_text(new)} is available (you have {current})"


def downloading(new) -> str:
    return f"Downloading VOLT {version_text(new)}..."


def up_to_date(current: str) -> str:
    return f"You're up to date ({current})."


def available_line(new) -> str:
    return f"VOLT {version_text(new)} is available."


def busy_text(games_tooltip: str | None) -> str:
    """The disabled Games button's tooltip ("Can't go back to game select
    until this finishes: Updating 3 mods...") -> "Can't update VOLT until
    this finishes: Updating 3 mods..."."""
    tip = (games_tooltip or "").strip()
    if tip.startswith(GAMES_BLOCK_PREFIX):
        return UPDATE_BLOCK_PREFIX + tip[len(GAMES_BLOCK_PREFIX):]
    return BUSY_FALLBACK


def size_text(n: int) -> str:
    return f"{n / MB:.1f} MB"


def progress_text(done: int, total: int | None) -> str:
    return f"{size_text(done)} of {size_text(total)}" if total else size_text(done)


def percent(done: int, total: int | None) -> float:
    return min(100.0, 100.0 * done / total) if total else 0.0


def status_line(current: str, last_check: str | None, now: datetime | None = None) -> str:
    """Settings' muted line: "You have VOLT 0.6.30. Last checked today at
    14:02." - last_check is update.json's UTC ISO time, shown local."""
    when = "Not checked yet."
    if last_check:
        try:
            d = datetime.fromisoformat(str(last_check)).astimezone()
        except (TypeError, ValueError):
            d = None
        if d is not None:
            now = (now or datetime.now()).astimezone()
            day = "today" if d.date() == now.date() else f"{d.day} {d:%b %Y}"
            when = f"Last checked {day} at {d:%H:%M}."
    return f"You have VOLT {current}. {when}"


def failed_apply(log_text: str) -> tuple[str, str, str]:
    """(what, means, try) for cleanup_leftovers' report of a failed copy."""
    what = "The last update didn't finish copying."
    if "nothing was copied" in log_text:
        means = "VOLT is still the old version. Nothing was changed."
    else:
        means = ("Some of VOLT's files may not have been updated, so this copy can be part old, part new. "
                 "It usually still works.")
    tryit = ("Use \"Check for updates\" in Settings to try again. If it fails again, download VOLT from its "
             "releases page on GitHub and copy the new files over this folder (your games folder is kept).")
    return what, means, tryit


# ---- release notes: GitHub's markdown body as help_window.TextBlocks(markup=True) text ----
_HEADING = re.compile(r"(#{1,6})\s+(.*?)(?:\s+#+)?")
_STAR_BULLET = re.compile(r"[-*+]\s+(.+)")
_NESTED = re.compile(r"(?: {2,}|\t)\s*(?:[-*+]|\d+[.)])\s+.*")  # an indented (sub-)bullet
_RULE = re.compile(r"(?:[-*_]\s*){3,}")
_RANGE = re.compile(r"(?:v?\d+(?:\.\d+)*|initial)\s*(?:->|\u2192)\s*v?\d+(?:\.\d+)*")
_LEAD = re.compile(r"(\*\*|__)(.+?)\1(.*)")


def _inline(s: str) -> str:
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)  # images -> alt text
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)  # links -> their text
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)  # bold
    s = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"\1", s)  # *italic*
    s = re.sub(r"~~(.+?)~~", r"\1", s)
    return s.replace("`", "").replace("**", "")  # an unpaired ** too: never raw


def notes_url(release) -> str:
    """The release's GitHub page (update.Release.url), else its tag page built from the repo."""
    return release.url or f"{update.RELEASES_PAGE}/tag/{release.tag}"


def notes_text(body: str | None) -> str:
    """A release body (GitHub markdown, HISTORY_PUSH.md's shape, MEMORY_OPS.md
    §7d) as the text help_window.TextBlocks(markup=True) shows: the summary
    paragraph(s); each heading its own "# Title" paragraph (a "##" line, a
    version-range heading and a repeat of the heading just shown are dropped);
    top-level bullets as "- " rows, a bold lead-in kept as a leading "**Lead.**"
    (TextBlocks shows it bold); nested (indented) bullets dropped - GitHub has
    the detail. A rule is a paragraph break; other bold / italic / code / link
    marks and HTML drop out. "# " and a leading "**" are the only marks left."""
    text = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    text = re.sub(r"</?[A-Za-z][^>\n]*>", "", text)  # stray HTML tags (GitHub allows them)
    out: list[str] = []
    last_heading = None  # the heading just shown, until any other text follows it
    nested = False  # inside a dropped sub-bullet: its indented continuation lines go too
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if nested and line and raw[:1] in " \t":
            continue
        nested = bool(_NESTED.fullmatch(raw.rstrip()))
        if nested:
            continue
        if _RULE.fullmatch(line):
            out.append("")
            continue
        m = _HEADING.fullmatch(line)
        if m:
            title = _inline(m.group(2)).strip()
            if len(m.group(1)) != 2 and title and title != last_heading and not _RANGE.fullmatch(title):
                out += ["", "# " + title, ""]
                last_heading = title
            continue
        if line:
            last_heading = None
        m = _STAR_BULLET.fullmatch(line)
        if m:
            lead = _LEAD.fullmatch(m.group(1))
            lead_text = _inline(lead.group(2)).strip() if lead else ""
            out.append(f"- **{lead_text}**{_inline(lead.group(3))}" if lead_text else "- " + _inline(m.group(1)))
            continue
        out.append(_inline(line))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# ---- worker bodies (screens/update_dialog.start_job runs them on a thread) ----
def startup_work(_job=None) -> dict:
    """Worker: cleanup_leftovers(), then (check_on_startup) the check. Never
    raises: a failed check is logged and dropped (the startup check is silent)."""
    out = {"report": None, "release": None}
    try:
        out["report"] = update.cleanup_leftovers()
    finally:
        CLEANUP_DONE.set()
    try:
        if not update.should_check_on_startup():
            log("[update] startup check: off (check_on_startup false)")
            return out
        rel = update.fetch_latest()
    except Exception as err:  # silent at startup: logged only
        log(f"[update] startup check failed (silent): {err!r}")
        return out
    current = update.current_version()
    if rel is None or not update.is_newer(rel.version, current):
        log(f"[update] startup check: up to date ({current}; latest {rel.tag if rel else 'none'})")
    elif update.is_skipped(rel.tag):
        log(f"[update] startup check: {rel.tag} is newer but skipped by the user")
    else:
        log(f"[update] startup check: {rel.tag} available (running {current})")
        out["release"] = rel
    return out


def check_now(_job=None):
    """Worker for Settings' manual check: the release when newer, else None.
    Raises UpdateCheckError (shown: the manual check always answers)."""
    rel = update.fetch_latest()
    current = update.current_version()
    newer = rel is not None and update.is_newer(rel.version, current)
    log(f"[update] manual check: latest {rel.tag if rel else 'none'}, running {current} -> "
        f"{'update available' if newer else 'up to date'}"
        + (" (skipped earlier; shown anyway: a manual check)" if newer and update.is_skipped(rel.tag) else ""))
    return rel if newer else None
