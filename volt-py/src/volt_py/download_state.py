"""The SteamCMD download row's state (App.jsx's `dl` + lists.js
applyDownloadEvent + the DownloadBar.jsx derivations), pure Python - no Qt.

screens/download_bar.py paints a DownloadState; the RimWorld main screen
owns the one shared instance (`_dl`): every _download_via_steamcmd call in
flight merges into it (`active` counts the calls, not the items), so two
downloads started close together show as one row with one Pause, exactly
as the Electron app's single `dl` object does. None = no row shown.

The Thunderstore managers' footer bar (0.6.25, screens/bepinex_main_screen.py)
reuses the same state with Thunderstore full_names ("Team-Package") as the
ids: seed_packages / apply_package_event / package_label at the end - mods,
not bytes, no pause, no speed.

Every function here returns a new state (the JS `setDl((d) => ...)`
updates); nothing is mutated, so the screen's own reference stays valid
across a queued-signal delivery.
"""

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
from math import floor, isfinite
from typing import NamedTuple


class Current(NamedTuple):
    """The item SteamCMD is on right now (dl.cur): its Workshop id, percent
    (0-100) and bytes/s (None on a first sample or a non-advance, as
    steam_cmd.create_progress_parser reports it)."""

    id: str
    percent: float
    speed: float | None


@dataclass(frozen=True)
class DownloadState:
    """App.jsx `dl`, field for field:
      rows / wids  everything requested since the row appeared (Resume
                   re-runs `rows` unchanged); wids = their Workshop ids
      done         Workshop ids SteamCMD reported finished (ok or not)
      failed       Workshop id -> why, for the items SteamCMD reported failed
      cur          the item in progress, or None
      active       _download_via_steamcmd calls in flight
      cancelled    one of them came back cancelled (folded into `paused`
                   once the last one settles)
      paused       every call settled and at least one was cancelled: the
                   row stays, the button shows Resume
      pausing      Pause clicked, waiting for the run to really stop (the
                   button is disabled meanwhile)"""

    rows: tuple[str, ...] = ()
    wids: tuple[str, ...] = ()
    done: tuple[str, ...] = ()
    failed: dict[str, str] = field(default_factory=dict)
    cur: Current | None = None
    active: int = 0
    cancelled: bool = False
    paused: bool = False
    pausing: bool = False
    checking: bool = False  # Thunderstore (0.6.34): plan_downloads' pre-pass is still working out the total


def _uniq(*seqs) -> tuple[str, ...]:
    return tuple(dict.fromkeys(x for seq in seqs for x in seq))


def start_download(d: DownloadState | None, rows, wids) -> DownloadState:
    """A _download_via_steamcmd call starts (App.jsx downloadViaSteamCmd's
    setDl): the row appears (or the new rows / Workshop ids merge into the
    one already shown, deduped, order kept), one more call is active, and a
    paused row is downloading again."""
    base = d if d is not None else DownloadState()
    return replace(base, rows=_uniq(base.rows, rows), wids=_uniq(base.wids, wids), active=base.active + 1, paused=False)


def settle_download(d: DownloadState | None, paused: bool) -> DownloadState | None:
    """A _download_via_steamcmd call settled (its `finally`): one call fewer
    is active; `paused` = that call came back cancelled with something still
    missing. While other calls are still running the row stays as it is (the
    cancellation remembered); once the last one settles the row either flips
    to paused (something was cancelled - the button shows Resume, no current
    item) or goes away (None)."""
    if d is None:
        return None
    active = d.active - 1
    cancelled = d.cancelled or paused
    if active > 0:
        return replace(d, active=active, cancelled=cancelled)
    if cancelled:
        return replace(d, active=0, cancelled=False, paused=True, pausing=False, cur=None)
    return None


def apply_download_event(d: DownloadState | None, ev: dict | None) -> DownloadState | None:
    """lists.js applyDownloadEvent over one steam_cmd live event (its
    snake_case dicts: {"type": "progress", "id", "percent", "speed_bytes_per_sec",
    ...} / {"type": "item-done", "id", "ok", "message"}). An event for an id
    this row doesn't track, or of any other type, changes nothing."""
    if d is None or not ev or ev.get("id") not in d.wids:
        return d
    wid = ev["id"]
    if ev.get("type") == "progress":
        return replace(d, cur=Current(wid, ev["percent"], ev.get("speed_bytes_per_sec")))
    if ev.get("type") != "item-done":
        return d
    failed = dict(d.failed)
    if ev.get("ok"):
        failed.pop(wid, None)
    else:
        failed[wid] = ev.get("message") or "failed"
    return replace(
        d,
        done=d.done if wid in d.done else (*d.done, wid),
        failed=failed,
        cur=None if d.cur is not None and d.cur.id == wid else d.cur,
    )


def percent_of(d: DownloadState) -> float:
    """The pill's fill, 0-100 (DownloadBar.jsx `percent`): finished items
    plus the current item's fraction, over every item requested; capped at
    100; 0 with nothing requested."""
    total = len(d.wids)
    if not total:
        return 0.0
    completed = len(d.done)
    cur_frac = d.cur.percent / 100 if d.cur is not None and d.cur.id not in d.done else 0.0
    return min(100.0, (completed + cur_frac) / total * 100)


def format_speed(bps) -> str:
    """DownloadBar.jsx formatSpeed: "-" for no / non-finite speed, "X.X MB/s"
    from 1 MiB/s up (one decimal), else "N KB/s" (rounded, no decimal)."""
    if bps is None or isinstance(bps, bool) or not isinstance(bps, (int, float)) or not isfinite(bps):
        return "-"
    if bps >= 1024 * 1024:
        return f"{_js_to_fixed_1(bps / (1024 * 1024))} MB/s"
    return f"{_js_round(bps / 1024)} KB/s"


def _js_round(x: float) -> int:
    """JS Math.round: halves go up (Python's round() goes to even)."""
    return int(floor(x + 0.5))


def _js_to_fixed_1(x: float) -> str:
    """JS Number.toFixed(1): the double's exact value rounded half up to one
    decimal - 1.25 -> "1.3" (Python's :.1f rounds half to even, "1.2"), while
    1.15, really 1.1499..., -> "1.1" (a `round(x * 10)` would say 1.2:
    x * 10 is 11.5 once rounded to a double). Decimal(x) is that exact value."""
    return str(Decimal(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


_ARRAY_INDEX_MAX = 2**32 - 2  # the largest JS array index


def _js_entries_order(keys) -> list[str]:
    """The order JS Object.entries lists string keys in: canonical array
    indices ("0".."4294967294", no leading zeros) first, ascending by value,
    then every other key in insertion order. Workshop ids are numeric strings
    below that limit today, so Electron's failure tooltip lists them by id."""
    keys = list(keys)
    indices = [k for k in keys if k.isdigit() and (k == "0" or k[0] != "0") and int(k) <= _ARRAY_INDEX_MAX]
    return sorted(indices, key=int) + [k for k in keys if k not in indices]


def speed_text(d: DownloadState) -> str:
    """The speed cell: "-" while paused, else the current item's speed."""
    if d.paused:
        return "-"
    return format_speed(d.cur.speed if d.cur is not None else None)


def label_text(d: DownloadState) -> str:
    return "Paused" if d.paused else "Downloading..."


def toggle_tooltip(d: DownloadState) -> str:
    """The pause/resume button's title / aria-label."""
    return "Resume download" if d.paused else "Pause download"


def count_text(d: DownloadState) -> str:
    """`{completed} / {total}` (the JSX renders the two numbers around " / ")."""
    return f"{len(d.done)} / {len(d.wids)}"


def failure_tooltip(d: DownloadState, titles: dict[str, str]) -> str:
    """The warning icon's title: one `<title or 'Workshop item <id>'>: <why>`
    line per failed item, in the order the JS's Object.entries gives them
    (_js_entries_order); "" when nothing failed (the icon is hidden then)."""
    return "\n".join(
        f"{titles.get(wid) or f'Workshop item {wid}'}: {d.failed[wid]}" for wid in _js_entries_order(d.failed)
    )


def failure_summary(d: DownloadState) -> str:
    """The warning icon's aria-label: "N download(s) failed"."""
    n = len(d.failed)
    return f"{n} download{'' if n == 1 else 's'} failed"


# ---- Thunderstore managers (0.6.25): one row per job, ids = full_names ----
def seed_packages(ids) -> DownloadState:
    """A download job starts: the mods it is known to fetch (the pre-pass's
    "plan" adds the rest up front; anything it missed still joins on its
    "start" - apply_package_event)."""
    return DownloadState(wids=_uniq(ids), active=1)


def apply_package_event(d: DownloadState | None, ev: dict | None) -> DownloadState | None:
    """bepinex_load_orders.package_progress's events: "checking" (the
    pre-pass started, 0.6.34) sets `checking` - the bar reads "Checking
    required mods..." - until its "plan" or the first "start" clears it;
    "plan" (plan_downloads' pre-pass) adds every mod it names to the total; "start" adds the mod to
    the total (if new) and makes it the current one; "item-done" is
    apply_download_event's (done, failed / un-failed on a later success),
    except the finished mod stays `cur` so the label doesn't flicker to
    "Downloading..." between two mods (percent_of ignores a done `cur`)."""
    if d is None or not ev:
        return d
    if ev.get("type") == "checking":
        return replace(d, checking=True)
    if ev.get("type") == "plan":  # the pre-pass (0.6.26): the job's whole list, before the first download
        return replace(d, wids=_uniq(d.wids, tuple(ev.get("ids") or ())), checking=False)
    if ev.get("type") == "start":
        return replace(d, wids=_uniq(d.wids, (ev["id"],)), cur=Current(ev["id"], 0.0, None), checking=False)
    after = apply_download_event(d, ev)
    return after if after is d else replace(after, cur=d.cur)


def package_label(d: DownloadState, titles: dict[str, str]) -> str:
    """"Downloading: <mod name>" (the current / last mod's title, else its
    id), or "Downloading..." before the first one starts; "Checking required
    mods..." while the pre-pass works out the total (0.6.34)."""
    if d.checking:
        return "Checking required mods..."
    if d.cur is None:
        return "Downloading..."
    return f"Downloading: {titles.get(d.cur.id) or d.cur.id}"
