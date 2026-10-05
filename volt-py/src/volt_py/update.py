"""Self-update logic (no UI): check GitHub for a newer release, download and
verify its zip, unpack it, and hand the file copy to a generated .bat that
runs after VOLT quits (a running VOLT.exe - and its --steam-worker child, the
same exe - can't be overwritten on Windows).

Flow, driven by the UI (dispatch 2): fetch_latest() -> is_newer() ->
can_self_update() -> download() -> stage() -> write_apply_script() ->
launch_apply() -> the caller quits the app AT ONCE. Next start:
cleanup_leftovers() clears <base>/update/ and reports a failed copy.

User data lives inside the install folder (<base>/games, <base>/cache); the
.bat copies with robocopy /E (never /MIR, never /PURGE), so nothing in the
install folder is ever deleted, and the release zip carries no games/ or
cache/ anyway. Stdlib + volt_py.net only (no PySide6), so
tools/checks/volt_py_update.py runs it in the sandbox.

Testing override: VOLT_UPDATE_API_URL (read once, at import) replaces the
GitHub API URL - any URL urllib opens, file:///... included - so a local
JSON file can fake a newer release. Logged whenever it's in effect.
"""

import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import types
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version as _dist_version
from pathlib import Path

from volt_py import app_root, fsutil, net
from volt_py.applog import log

REPO = "Vokaerian/V.O.L.T"
DEFAULT_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
API_URL = os.environ.get("VOLT_UPDATE_API_URL") or DEFAULT_API_URL
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
ASSET_PATTERN = "VOLT-v*-win64.zip"  # tools/release.py's zip name
# Also a trust-boundary check: the name becomes a file name under update/.
_SAFE_ASSET = re.compile(r"VOLT-v[0-9A-Za-z.\-]+-win64\.zip")
_DIGEST = re.compile(r"sha256:([0-9a-fA-F]{64})")
TIMEOUT_S = 10
_CHUNK = 256 * 1024

UPDATE_DIR = "update"  # <base>/update/: download, staged/, apply.bat, apply.log
STAGED_DIR = "staged"
STATE_FILE = "update.json"  # <base>/update.json
APPLY_BAT = "apply.bat"
APPLY_LOG = "apply.log"
APPLY_LOG_PREV = "apply.log.prev"  # apply.log once cleanup_leftovers has read it
EXE_NAME = "VOLT.exe"
ZIP_ROOT = "VOLT"  # the zip's one top-level folder since 0.6.29 (tools/release.py)
# In <base>, never touched by an update (robocopy /XD; also never in the zip).
KEEP_DIRS = ("games", "cache", UPDATE_DIR)
FAILED_MARK = "RESULT: FAILED"
OK_MARK = "RESULT: OK"
# apply.log markers (0.6.44): VOLT writes TARGET_MARK before it launches the
# script, the script writes STARTED_MARK first and DONE_MARK right before it
# restarts VOLT. A log missing one of them was cut short (antivirus, say).
TARGET_MARK = "TARGET VERSION:"
STARTED_MARK = "VOLT update started"
DONE_MARK = "FINISHED"
WAIT_SECONDS = 60

DEFAULT_STATE = {"check_on_startup": True, "skipped_tag": None, "last_check": None}

# Seams for tools/checks/volt_py_update.py (like steam_cmd.env).
env = types.SimpleNamespace(platform=sys.platform, is_packaged=app_root.is_packaged, popen=subprocess.Popen)

class UpdateError(Exception):
    """A plain-words message for the update dialog."""


class UpdateCheckError(UpdateError):
    """The check itself failed (network, GitHub, bad JSON). The manual check
    shows it; the startup check swallows it."""


@dataclass
class Release:
    tag: str
    version: tuple
    notes: str
    asset_name: str | None = None
    asset_url: str | None = None
    asset_size: int | None = None
    sha256: str | None = None  # lowercase hex
    url: str | None = None  # the release's GitHub page (html_url; https://github.com/ only), None when absent


# ---- versions ----
def parse_version(tag) -> tuple | None:
    """'v0.6.10' / '0.6.10' -> (0, 6, 10); anything else -> None."""
    if not isinstance(tag, str):
        return None
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", tag.strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def is_newer(latest, current) -> bool:
    """latest > current; each a tag/version string or a parsed tuple. False
    when either doesn't parse."""
    a = parse_version(latest) if isinstance(latest, str) else latest
    b = parse_version(current) if isinstance(current, str) else current
    return bool(a and b) and a > b


def current_version() -> str:
    try:
        return _dist_version("volt-py")
    except Exception:  # PackageNotFoundError: no installed metadata
        return "?"


# ---- check ----
def _request(url: str, accept: str):
    return urllib.request.Request(url, headers={"User-Agent": f"VOLT/{current_version()} updater", "Accept": accept})


def _status_ok(res) -> int:
    status = getattr(res, "status", None) or 200  # None for file:// (the test override)
    if not 200 <= status < 300:
        raise OSError(f"HTTP {status}")
    return status


def fetch_latest(urlopen=net.urlopen) -> Release | None:
    """The latest published release (GitHub's /releases/latest skips drafts
    and pre-releases), or None when there is none / its tag isn't a version.
    A release without a matching zip comes back with asset fields None (the
    UI then offers the Releases page). Raises UpdateCheckError."""
    override = " (VOLT_UPDATE_API_URL override)" if API_URL != DEFAULT_API_URL else ""
    log(f"[update] checking {API_URL}{override} (running {current_version()})")
    try:
        with urlopen(_request(API_URL, "application/vnd.github+json"), timeout=TIMEOUT_S) as res:
            _status_ok(res)
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        if err.code == 404:
            log("[update] check: HTTP 404 - no published release yet")
            return None
        log(f"[update] check failed: HTTP {err.code} {err.reason}")
        if err.code in (403, 429):
            raise UpdateCheckError("GitHub is limiting how often VOLT can check for updates. Try again in an hour.") from err
        raise UpdateCheckError(f"GitHub answered with an error (HTTP {err.code}). Try again later.") from err
    except (OSError, ValueError) as err:  # URLError, timeouts, bad JSON/UTF-8
        log(f"[update] check failed: {err!r}")
        raise UpdateCheckError(f"VOLT couldn't reach GitHub to check for updates ({_reason(err)}). "
                               "Check your internet connection and try again.") from err
    if not isinstance(data, dict):
        log(f"[update] check failed: reply is {type(data).__name__}, not an object")
        raise UpdateCheckError("GitHub sent an answer VOLT couldn't read. Try again later.")
    try:
        save_state({"last_check": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    except OSError as err:
        log(f"[update] couldn't record last_check: {err!r}")

    tag = str(data.get("tag_name") or "")
    ver = parse_version(tag)
    if ver is None:
        log(f"[update] check: latest release tag {tag!r} isn't a version, ignoring it")
        return None
    page = data.get("html_url")
    rel = Release(tag=tag, version=ver, notes=str(data.get("body") or ""),
                  url=page if isinstance(page, str) and page.startswith("https://github.com/") else None)
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    for a in assets:
        name = a.get("name") if isinstance(a, dict) else None
        if isinstance(name, str) and fnmatch.fnmatchcase(name, ASSET_PATTERN) and _SAFE_ASSET.fullmatch(name):
            m = _DIGEST.fullmatch(str(a.get("digest") or ""))
            size = a.get("size")
            rel.asset_name, rel.asset_url = name, a.get("browser_download_url") or None
            rel.asset_size = size if isinstance(size, int) and size > 0 else None
            rel.sha256 = m.group(1).lower() if m else None
            break
    log(f"[update] latest release {tag} ({len(assets)} asset(s)); page {rel.url or 'none (html_url missing)'}; zip: "
        + (f"{rel.asset_name}, {rel.asset_size} bytes, sha256 {rel.sha256 or 'MISSING'}, {rel.asset_url}"
           if rel.asset_name else "none matching " + ASSET_PATTERN))
    return rel


def _reason(err) -> str:
    return str(getattr(err, "reason", None) or err) or type(err).__name__


# ---- state file ----
def _state_path() -> Path:
    return app_root.resolve_base_root() / STATE_FILE


def load_state() -> dict:
    """update.json merged over the defaults; missing or corrupt -> defaults."""
    state = dict(DEFAULT_STATE)
    path = _state_path()
    try:
        data = fsutil.read_json(path)
    except FileNotFoundError:
        return state
    except (OSError, ValueError) as err:
        log(f"[update] {path} unreadable, using defaults: {err!r}")
        return state
    if isinstance(data, dict):
        state.update({k: data[k] for k in DEFAULT_STATE if k in data})
    else:
        log(f"[update] {path} isn't a JSON object, using defaults")
    return state


def save_state(patch: dict) -> dict:
    """Merges patch into the state file (atomic write); returns the new state."""
    state = {**load_state(), **patch}
    fsutil.write_json(_state_path(), state)
    log(f"[update] state saved: {patch}")
    return state


def should_check_on_startup() -> bool:
    return bool(load_state()["check_on_startup"])


def is_skipped(tag) -> bool:
    return bool(tag) and load_state()["skipped_tag"] == tag


# ---- can we do it here? ----
def can_self_update(release: Release) -> tuple[bool, str]:
    """(True, "") or (False, why in plain words)."""
    base = app_root.resolve_base_root()
    if env.platform != "win32":
        why = "Updating from inside VOLT only works on Windows."
    elif not env.is_packaged():
        why = "This is a development copy of VOLT (not a release build), so it can't update itself."
    elif not release.asset_url:
        why = "This release has no Windows download attached."
    elif not release.sha256:
        why = "GitHub didn't give a checksum for this download, so VOLT can't check it isn't damaged."
    elif not _writable(base):
        why = (f"VOLT can't write to its own folder ({base}). Move VOLT to a folder you own "
               "(not Program Files), or download the update yourself.")
    else:
        log(f"[update] can self-update {release.tag} into {base}")
        return True, ""
    log(f"[update] can't self-update {release.tag}: {why}")
    return False, why


def _writable(folder: Path) -> bool:
    probe = folder / f".volt-write-test-{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError as err:
        log(f"[update] {folder} isn't writable: {err!r}")
        return False


def update_dir() -> Path:
    return app_root.resolve_base_root() / UPDATE_DIR


# ---- download ----
def download(release: Release, progress_cb=None, cancel_event=None, urlopen=net.urlopen) -> Path | None:
    """Streams the release zip to <base>/update/<asset>.part, checks size and
    sha256, renames it to <base>/update/<asset>. progress_cb(done, total)
    after every chunk (total None when unknown). Returns the zip path, or
    None when cancel_event was set (the .part is deleted). Raises UpdateError."""
    if not (release.asset_url and release.asset_name and release.sha256):
        raise UpdateError("This release has no download VOLT can check.")
    folder = update_dir()
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / f"{release.asset_name}.part"
    final = folder / release.asset_name
    log(f"[update] downloading {release.asset_url} -> {part} (expect {release.asset_size} bytes, sha256 {release.sha256})")
    digest = hashlib.sha256()
    done = 0
    try:
        with urlopen(_request(release.asset_url, "application/octet-stream"), timeout=TIMEOUT_S) as res, open(part, "wb") as f:
            _status_ok(res)
            length = res.headers.get("Content-Length") if getattr(res, "headers", None) else None
            total = release.asset_size or (int(length) if length and length.isdigit() else None)
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    break
                chunk = res.read(_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    except urllib.error.HTTPError as err:
        part.unlink(missing_ok=True)
        log(f"[update] download failed: HTTP {err.code} after {done} bytes")
        raise UpdateError(f"The download failed (GitHub answered HTTP {err.code}). Try again later.") from err
    except (OSError, ValueError) as err:
        part.unlink(missing_ok=True)
        log(f"[update] download failed after {done} bytes: {err!r}")
        raise UpdateError(f"The download stopped ({_reason(err)}). Check your internet connection and try again.") from err
    if cancel_event is not None and cancel_event.is_set():
        part.unlink(missing_ok=True)
        log(f"[update] download cancelled by the user after {done} bytes; {part} deleted")
        return None
    got = digest.hexdigest()
    if (release.asset_size and done != release.asset_size) or got != release.sha256:
        part.unlink(missing_ok=True)
        log(f"[update] download DAMAGED, deleted: {done} bytes (expected {release.asset_size}), "
            f"sha256 {got} (expected {release.sha256})")
        raise UpdateError("The download is damaged (it doesn't match what GitHub says it should be). "
                          "Nothing was changed. Try again.")
    os.replace(part, final)
    log(f"[update] downloaded and verified {done} bytes, sha256 {got} -> {final}")
    return final


# ---- stage ----
def stage(zip_path) -> Path:
    """Unpacks the zip into <base>/update/staged/ (a stale one wiped first)
    and returns the folder holding VOLT.exe: staged/VOLT/ (zips since 0.6.29)
    or staged/ itself (older flat zips). Refuses a zip with any entry that
    would land outside staged/. Raises UpdateError."""
    staged = update_dir() / STAGED_DIR
    log(f"[update] staging {zip_path} -> {staged}")
    try:
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(parents=True)
        root = staged.resolve()
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                target = (root / name).resolve()
                if target != root and root not in target.parents:
                    log(f"[update] staging refused: unsafe path in zip: {name!r}")
                    raise UpdateError("The download contains a file that would land outside VOLT's folder, "
                                      "so VOLT won't use it.")
            zf.extractall(root)
            count = len(zf.namelist())
    except (OSError, zipfile.BadZipFile) as err:
        log(f"[update] staging failed: {err!r}")
        raise UpdateError(f"VOLT couldn't unpack the update ({_reason(err)}).") from err
    for app in (staged / ZIP_ROOT, staged):
        if (app / EXE_NAME).is_file():
            log(f"[update] staged {count} zip entries; app root {app}")
            return app
    log(f"[update] staging failed: no {EXE_NAME} at {staged / ZIP_ROOT} or {staged}")
    raise UpdateError(f"The download doesn't contain {EXE_NAME}, so it can't be installed.")


# ---- apply ----
def _bat_path(p) -> str:
    """A path as a quoted .bat argument: '%' doubled (the one character a
    .bat expands inside quotes, with delayed expansion off); a trailing
    backslash (a drive root) gets '.' so it can't escape robocopy's closing
    quote. & ^ ( ) and spaces are literal inside the quotes."""
    s = str(p)
    if s.endswith("\\"):
        s += "."
    return '"' + s.replace("%", "%%") + '"'


def write_apply_script(staged, install_dir, target=None) -> Path:
    """Writes <base>/update/apply.bat: wait (up to WAIT_SECONDS) until VOLT.exe
    can be opened for writing (every VOLT process has exited), robocopy the
    staged app root over install_dir, log to apply.log, then ALWAYS start
    VOLT.exe again (the old build if the copy failed; apply.log says so).
    Also starts apply.log with TARGET_MARK target (the release tag), which the
    script appends to and cleanup_leftovers checks on the next start."""
    staged, install = Path(staged), Path(install_dir)
    folder = update_dir()
    bat, logf = folder / APPLY_BAT, folder / APPLY_LOG
    exe = install / EXE_NAME
    S, D, E, L = _bat_path(staged), _bat_path(install), _bat_path(exe), _bat_path(logf)
    xd = " ".join(_bat_path(staged / d) for d in KEEP_DIRS)
    # ponytail: robocopy /E only adds/overwrites, so files a newer build no
    # longer ships stay behind (harmless clutter). Upgrade path: ship a file
    # manifest in the zip and delete what the old manifest had and the new lacks.
    lines = [
        "@echo off",
        "setlocal DisableDelayedExpansion",
        "chcp 65001 >nul",
        f">>{L} echo {STARTED_MARK} %date% %time%",
        f">>{L} echo from {S}",
        f">>{L} echo to {D}",
        "set /a tries=0",
        ":wait",
        # Opens VOLT.exe for append and writes nothing ("(call )"); fails while
        # any VOLT process (the app or its --steam-worker) still runs it.
        f"2>nul (>>{E} (call )) && goto copy",
        "set /a tries+=1",
        f"if %tries% geq {WAIT_SECONDS} goto locked",
        # Not 'timeout /t 1': it exits at once when stdin isn't a console,
        # which it never is here (launch_apply), turning this into a spin.
        "ping -n 2 127.0.0.1 >nul",
        "goto wait",
        ":locked",
        f">>{L} echo {FAILED_MARK} - VOLT.exe was still in use after {WAIT_SECONDS} seconds; nothing was copied, starting the old version",
        "goto start",
        ":copy",
        f">>{L} echo VOLT.exe is free after %tries% second(s), copying",
        f"robocopy {S} {D} /E /XD {xd} /R:5 /W:2 /NFL /NDL /NJH /LOG+:{L}",
        "set rc=%errorlevel%",
        "if %rc% geq 8 goto failed",
        f">>{L} echo {OK_MARK} - robocopy exit code %rc%",
        "goto start",
        ":failed",
        f">>{L} echo {FAILED_MARK} - robocopy exit code %rc%; some files may not have been updated, starting VOLT anyway",
        ":start",
        f">>{L} echo {DONE_MARK} - starting {E}",
        f'start "" /D {D} {E}',
        "exit /b 0",
    ]
    folder.mkdir(parents=True, exist_ok=True)
    # CRLF: cmd's label/goto scanning misbehaves on LF-only batch files.
    with open(bat, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    # After the .bat: a failed write here leaves no apply.log, which the next
    # start reads as "never launched", not as an interrupted update.
    with open(logf, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(f"VOLT {current_version()} wrote apply.bat at {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %z}\n"
                f"{TARGET_MARK} {target or '?'}\n")
    log(f"[update] wrote {bat}: copy {staged} -> {install}, then start {exe}; target {target}; "
        f"apply.log {logf} started. Script:\n" + "\n".join(lines))
    return bat


def launch_apply(bat=None) -> None:
    """Starts apply.bat hidden and detached from VOLT. THE CALLER MUST QUIT
    THE APP IMMEDIATELY AFTER: the script waits (WAIT_SECONDS at most) for
    every VOLT process to exit before copying, then restarts VOLT.

    cmd.exe runs with its cwd set to the update folder and the script by bare
    name, so no path ever goes through cmd's /c quote-stripping rules."""
    bat = Path(bat) if bat else update_dir() / APPLY_BAT
    comspec = os.environ.get("ComSpec") or "cmd.exe"
    # CREATE_NO_WINDOW rather than DETACHED_PROCESS: a detached cmd has no
    # console, so every console child (ping, robocopy) would pop its own
    # window; this way they share one hidden console. Either way the script
    # outlives VOLT (Windows doesn't kill children with their parent).
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    argv = [comspec, "/d", "/c", bat.name]
    log(f"[update] launching {argv} (ComSpec {'from the environment' if os.environ.get('ComSpec') else 'unset, using cmd.exe'}) "
        f"in {bat.parent}, creationflags {flags:#x} (CREATE_NO_WINDOW|CREATE_NEW_PROCESS_GROUP), stdio DEVNULL")
    try:
        p = env.popen(argv, cwd=str(bat.parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)
    except OSError as err:
        log(f"[update] launching apply.bat FAILED: {err!r}")
        # Never launched: drop the TARGET_MARK header so the next start doesn't
        # report it as an interrupted update (the dialog shows this error now).
        (bat.parent / APPLY_LOG).unlink(missing_ok=True)
        raise
    log(f"[update] apply.bat launched: pid {getattr(p, 'pid', None)}; VOLT must now quit")


def _apply_problem(text: str) -> str | None:
    """What went wrong according to apply.log, in plain words, or None when
    the update finished. Logs written by 0.6.43 and older have no
    TARGET_MARK/DONE_MARK, so only the result line is checked for those."""
    if FAILED_MARK in text:
        return "apply.bat recorded a failed copy"
    m = re.search(re.escape(TARGET_MARK) + r"\s*(\S+)", text)
    target = m.group(1) if m else None
    if target and STARTED_MARK not in text:
        return "apply.bat never ran (it was stopped before its first line); nothing was copied"
    if OK_MARK not in text:
        return "apply.bat stopped before the copy finished (no result line)"
    if target and DONE_MARK not in text:
        return "apply.bat stopped after the copy, before it restarted VOLT"
    current = current_version()
    if target and parse_version(target) and parse_version(current) and parse_version(target) != parse_version(current):
        return f"VOLT is still version {current}, the update was to {target}"
    return None


def cleanup_leftovers() -> str | None:
    """Call once at startup. Empties <base>/update/ (download, staged/,
    apply.bat) and moves apply.log to apply.log.prev (kept for
    troubleshooting, so it's only reported once). Returns apply.log's text,
    led by a plain-words line, when the update failed or was cut short
    (_apply_problem), else None. Never raises."""
    exe = app_root.exe_path()
    try:
        st = exe.stat()
        about = f"{st.st_size} bytes, modified {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}"
    except OSError as err:
        about = f"stat failed: {err!r}"
    log(f"[update] running VOLT {current_version()} from {exe} ({about})")
    folder = update_dir()
    if not folder.is_dir():
        return None
    report = None
    logf = folder / APPLY_LOG
    try:
        if logf.is_file():
            text = logf.read_text(encoding="utf-8", errors="replace")
            problem = _apply_problem(text)
            log(f"[update] last update's apply.log: {'finished OK' if problem is None else 'DID NOT FINISH: ' + problem}"
                f"{'' if problem is None else ' (antivirus software may have stopped it)'}\n{text.strip()}")
            if problem:
                report = f"VOLT on the next start: {problem}.\n{text}"
            os.replace(logf, folder / APPLY_LOG_PREV)
        elif (folder / APPLY_BAT).exists():
            log(f"[update] {folder / APPLY_BAT} is there but {logf} isn't: the update was prepared but never "
                "launched (or apply.log was removed), so nothing was copied")
    except OSError as err:
        log(f"[update] couldn't read/move {logf}: {err!r}")
    for p in folder.iterdir():
        if p.name in (APPLY_LOG, APPLY_LOG_PREV):
            continue
        try:
            shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
            log(f"[update] cleanup: removed {p}")
        except OSError as err:
            log(f"[update] cleanup: couldn't remove {p}: {err!r}")
    return report
