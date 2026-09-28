"""RimSort's Community Rules Database (port of Electron's
src/electron/lib/communityRules.js): crowd-sourced loadAfter/loadBefore rules
for mods that don't declare them (well) in their own About.xml.
https://github.com/RimSort/Community-Rules-Database

A LIVE RUNTIME LOOKUP, not bundled or redistributed with VOLT (the database
has no LICENSE): the app fetches the published file itself, once per process,
and keeps the last good copy at <app_root>/communityRules.json only as an
offline fallback. Fallback chain: live fetch -> cached file -> empty. Never
raises - a missing/unreachable source just drops out of Sort's merge
(sort.py), it never blocks or fails Sort.

Stdlib only (urllib + json + threading). Synchronous itself; callers pick
the thread. RimWorldMainScreen starts the lookup on a background thread when
it's built (Electron's fetch-at-launch), and the Sort button's click handler
also calls get_community_rules on the GUI thread: it returns the cached
result instantly once the background lookup has landed, else waits for it
(busy cursor meanwhile, up to TIMEOUT_S on a dead network). A lock makes sure
only one of them ever fetches.
"""

import json
import threading
from pathlib import Path

from . import net
from .applog import clip, log
from .fsutil import read_text, write_text_atomic

RULES_URL = "https://raw.githubusercontent.com/RimSort/Community-Rules-Database/main/communityRules.json"
# ponytail: urllib's timeout is per socket operation (connect, each read), not
# a total deadline like the JS's AbortSignal.timeout - a server trickling bytes
# could take longer. Fine for one ~1MB file from GitHub's CDN.
TIMEOUT_S = 10
CACHE_NAME = "communityRules.json"


def normalize_rules(data) -> dict[str, dict[str, list[str]]]:
    """The file's {"rules": {id: {"loadAfter": {id: ...}, "loadBefore": {id: ...}}}}
    as {lowercased id: {"load_after": [...], "load_before": [...]}}. Only the
    keys of loadAfter/loadBefore matter; name/comment and any other key
    (loadTop, loadBottom, incompatibleWith, ...) are ignored. Raises ValueError
    if there's no rules object."""
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, dict):
        raise ValueError('communityRules.json has no "rules" object')

    def keys(o) -> list[str]:
        return list(o) if isinstance(o, dict) else []

    out: dict[str, dict[str, list[str]]] = {}
    for raw_id, entry in rules.items():
        rid = str(raw_id).strip().lower()
        # JS: `!entry || typeof entry !== 'object'` - arrays count as objects
        # there (they just have no loadAfter/loadBefore), an empty {} is truthy.
        if not rid or not isinstance(entry, (dict, list)):
            continue
        cur = out.setdefault(rid, {"load_after": [], "load_before": []})
        if isinstance(entry, dict):
            cur["load_after"].extend(keys(entry.get("loadAfter")))
            cur["load_before"].extend(keys(entry.get("loadBefore")))
    return out


def _fetch_live(cache_file: Path, url: str) -> dict:
    log(f"community rules: fetching {url} (timeout {TIMEOUT_S}s)")
    with net.urlopen(url, timeout=TIMEOUT_S) as res:
        status = getattr(res, "status", None)  # None for a file:// URL (the check harness)
        if status is not None and not 200 <= status < 300:
            raise OSError(f"HTTP {status}")  # urlopen raises HTTPError for most; belt and braces
        raw = res.read()
    text = raw.decode("utf-8-sig")  # like res.text(): a leading BOM is dropped
    rules = normalize_rules(json.loads(text))  # validate before overwriting the cache
    log(f"community rules: live fetch OK, HTTP {status}, {len(raw)} bytes, {len(rules)} mods with rules")
    try:
        write_text_atomic(cache_file, text)
        log(f"community rules: cache written to {cache_file}")
    except OSError as err:
        log(f"community rules: could not write cache {cache_file}: {err!r}")
    return rules


def load(app_root, url: str = RULES_URL) -> dict:
    """{"rules": dict, "source": "live" | "cache" | "none"}. Never raises."""
    cache_file = Path(app_root) / CACHE_NAME
    try:
        return {"rules": _fetch_live(cache_file, url), "source": "live"}
    except Exception as err:  # network, HTTP, decode, JSON, shape - all fall back
        log(f"community rules: live fetch failed ({clip(repr(err), 500)}); trying cached copy {cache_file}")
    try:
        rules = normalize_rules(json.loads(read_text(cache_file)))
        log(f"community rules: using cached copy, {len(rules)} mods with rules")
        return {"rules": rules, "source": "cache"}
    except FileNotFoundError:
        log("community rules: no cached copy; sorting without community rules")
    except Exception as err:
        log(f"community rules: cached copy unusable ({clip(repr(err), 500)}); sorting without community rules")
    return {"rules": {}, "source": "none"}


_result: dict | None = None  # once per process, like the JS's `pending`
# Serializes get_community_rules: the startup background fetch and a Sort on
# the GUI thread can both call it, and only the first may run load(); the
# other waits here, then reuses its result (the JS gets this from sharing one
# promise).
_lock = threading.Lock()


def get_community_rules(app_root) -> dict:
    """Once per process: the first call does the lookup (load), every later
    call (e.g. each Sort) shares its result - a failed first lookup included,
    as in the JS. Thread-safe: a call made while another thread's lookup is
    in flight blocks until it finishes, then shares it. Never raises."""
    global _result
    with _lock:
        if _result is None:
            try:
                _result = load(app_root)
            except Exception as err:  # load() itself never raises; this is the JS's .catch
                log(f"community rules: lookup crashed ({err!r}); sorting without community rules")
                _result = {"rules": {}, "source": "none"}
        else:
            log(f"community rules: reusing this run's lookup (source={_result['source']}, {len(_result['rules'])} mods)")
        return _result


def loaded_rules() -> dict | None:
    """This run's community rules if get_community_rules has already looked
    them up, else None. Never fetches, never logs, never waits on the lock
    (reading the one reference is atomic; _result is only ever set to a
    finished dict): the live validation (RimWorldMainScreen._update_validation)
    reads it on every Active change. As in the Electron app, the rules are
    fetched in the background at startup (RimWorldMainScreen) and validation
    re-runs when they arrive; until then it runs without the community tier."""
    return None if _result is None else _result["rules"]
