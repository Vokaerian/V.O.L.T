"""Export diagnostics (0.6.50; the Troubleshoot window's "Export
diagnostics..." button, Thunderstore games): ONE .zip with what a helper needs
to see what happened to a profile - never uploaded, the user picks who gets it.

Layout = the real app layout relative to <base> (app_root.resolve_base_root):
  logs/volt.log, logs/volt.log.prev, logs/apply.log(.prev)
  games/<game>/settings.json
  games/<game>/load-orders/<profile>/loadorder.json, doorstop_config.ini, .doorstop_version
  games/<game>/load-orders/<profile>/volt-runs/<id>.json + <id>.log.gz   the RUNS_KEPT newest runs
  games/<game>/load-orders/<profile>/BepInEx/LogOutput.log, BepInEx/config/** (every file),
      BepInEx/LogOutput.sqlite(-shm, -wal) when they exist (AsyncLoggers writes them)
  diagnostics.txt (zip root): versions, game, profile, OS, mod counts, the redaction note,
      every file included and every file skipped (unreadable / locked) with the reason.
Only the open profile; never plugins/, core/, patchers/, monomod/, cache/, a DLL /
EXE, the game folder or its loader files (only what's listed above is collected, and
a .dll / .exe under config/ is skipped and listed).

Redaction (user decision 2026-10-08): the Windows account name (account_names: the
home folder's last part and USERNAME) becomes "***" in every text file - the
"C:\\Users\\<name>" / "/Users/<name>" / "/home/<name>" path part always, the bare
name (case-insensitive, whole word) when it has 3+ characters; a .log.gz is
decompressed, redacted and compressed again. Files that aren't UTF-8 text (the
SQLite database and its -shm / -wal, any binary config) get a SAME-LENGTH byte mask
instead (each byte of the name -> "*", so the database stays valid), stated in
diagnostics.txt. Originals are never modified: everything is redacted while it is
written into the zip. Nothing else is removed - mod configs and logs can hold other
names or paths, and the save dialog's intro says so.

Pure Python, no Qt (tools/checks/volt_py_diagnostics.py)."""

import gzip
import os
import platform
import re
import sys
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

from . import bepinex_runs as runs
from .applog import LOG_DIR, log

NOTE_NAME = "diagnostics.txt"
RUNS_KEPT = 5
MASK = "***"
LOG_FILES = ("volt.log", "volt.log.prev", "apply.log", "apply.log.prev")
PROFILE_FILES = ("loadorder.json", "doorstop_config.ini", ".doorstop_version")
SQLITE_FILES = ("LogOutput.sqlite", "LogOutput.sqlite-shm", "LogOutput.sqlite-wal")
PROGRAM_SUFFIXES = (".dll", ".exe")
BARE_MIN = 3  # a shorter account name is masked only inside a user-folder path (else "a" / "al" would hit every word)


def file_name(game_slug: str, profile_slug: str, when: datetime) -> str:
    """The save dialog's default name."""
    return f"volt-diagnostics-{game_slug}-{profile_slug}-{when:%Y%m%d-%H%M%S}.zip"


def account_names(home=None, env=None) -> list[str]:
    """The account name(s) to mask: the home folder's own name and USERNAME
    (each once, case-insensitively; empty ones dropped)."""
    env = os.environ if env is None else env
    out: list[str] = []
    for name in (Path(home if home is not None else os.path.expanduser("~")).name, env.get("USERNAME") or env.get("USER")):
        if name and name.casefold() not in (n.casefold() for n in out):
            out.append(name)
    return out


def _regexes(names: list[str], binary: bool) -> list[re.Pattern]:
    """Per name: the user-folder path form (group 1 = the folder prefix kept,
    group 2 = the name) and, for a 3+ character name, the bare whole word."""
    out = []
    for name in names:
        n = re.escape(name.encode("utf-8") if binary else name)
        if binary:
            out.append(re.compile(rb"(?i)([\\/]+(?:Users|home)[\\/]+)(" + n + rb")(?![A-Za-z0-9_.-])"))
            if len(name) >= BARE_MIN:
                out.append(re.compile(rb"(?i)()(?<![A-Za-z0-9_])(" + n + rb")(?![A-Za-z0-9_])"))
        else:
            out.append(re.compile(r"(?i)([\\/]+(?:Users|home)[\\/]+)(" + n + r")(?![A-Za-z0-9_.-])"))
            if len(name) >= BARE_MIN:
                out.append(re.compile(r"(?i)()(?<![A-Za-z0-9_])(" + n + r")(?![A-Za-z0-9_])"))
    return out


def redact_text(text: str, names: list[str]) -> str:
    """`text` with every account-name occurrence (module docstring) -> MASK."""
    for rx in _regexes(names, binary=False):
        text = rx.sub(lambda m: m.group(1) + MASK, text)
    return text


def mask_bytes(data: bytes, names: list[str]) -> bytes:
    """`data` with the same occurrences (UTF-8) overwritten by "*", byte for
    byte: the length and every other byte unchanged (a database stays valid)."""
    for rx in _regexes(names, binary=True):
        data = rx.sub(lambda m: m.group(1) + b"*" * len(m.group(2)), data)
    return data


def _redacted(path: Path, data: bytes, names: list[str]) -> tuple[bytes, str]:
    """(the bytes to store, how): text redacted / a .gz re-packed / a same-length mask."""
    if path.name.endswith(".gz"):
        inner, how = _redacted(path.with_name(path.name[:-3]), gzip.decompress(data), names)
        return gzip.compress(inner), how
    if path.name in SQLITE_FILES:
        return mask_bytes(data, names), "masked"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return mask_bytes(data, names), "masked"
    return redact_text(text, names).encode("utf-8"), "text"


def collect(base, app_root, tree) -> list[Path]:
    """Every file that goes in (module docstring), in zip order; what doesn't exist is left out."""
    base, app_root, tree = Path(base), Path(app_root), Path(tree)
    files = [base / LOG_DIR / n for n in LOG_FILES] + [app_root / "settings.json"] + [tree / n for n in PROFILE_FILES]
    try:
        ids = sorted((p.name[:-5] for p in runs.runs_dir(tree).glob("*.json") if p.name != runs.PENDING), reverse=True)
    except OSError:
        ids = []
    for rid in ids[:RUNS_KEPT]:
        files += [runs.runs_dir(tree) / f"{rid}.json", runs.runs_dir(tree) / f"{rid}.log.gz"]
    bep = tree / "BepInEx"
    files.append(bep / "LogOutput.log")
    files += sorted((p for p in (bep / "config").rglob("*") if p.is_file()), key=lambda p: p.as_posix().casefold())
    files += [bep / n for n in SQLITE_FILES]
    return [p for p in files if p.is_file()]


def _arcname(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:  # a profile outside <base> (never, today): keep the layout's tail
        return "outside-base/" + path.name


def _counts(manifest: dict | None) -> str:
    m = manifest or {}
    active, inactive, fw = m.get("active") or [], m.get("inactive") or [], m.get("framework") or {}
    off = sum(1 for e in active if e.get("enabled") is False)
    return (f"{len(active)} active ({off} switched off), {len(inactive)} inactive; framework "
            f"{fw.get('full_name', '-')} {fw.get('version', '')}".rstrip())


def write(dest, *, base, app_root, tree, game_name: str, game_slug: str, profile_name: str, profile_slug: str,
          manifest: dict | None, game_dir, app_version: str, qt_version: str, names: list[str] | None = None) -> dict:
    """Writes the zip at `dest` (a temp sibling first, then os.replace: no
    half-written file). Returns {"files": [arcnames], "skipped": [(arcname,
    reason)], "masked": [arcnames byte-masked]}. OSError when `dest` can't be
    written; a single unreadable source file is skipped and listed, never raised."""
    dest, base = Path(dest), Path(base)
    names = account_names() if names is None else names
    done, skipped, masked = [], [], []
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for path in collect(base, app_root, tree):
                arc = _arcname(path, base)
                if path.suffix.casefold() in PROGRAM_SUFFIXES:
                    skipped.append((arc, "a program file, never included"))
                    continue
                try:
                    data, how = _redacted(path, path.read_bytes(), names)
                except (OSError, EOFError, zlib.error) as err:  # locked / unreadable / a broken .gz
                    skipped.append((arc, f"couldn't be read: {err}"))
                    continue
                z.writestr(arc, data)
                done.append(arc)
                if how == "masked":
                    masked.append(arc)
            z.writestr(NOTE_NAME, redact_text(_note(game_name, game_slug, profile_name, profile_slug, manifest, game_dir,
                                                    app_version, qt_version, done, skipped, masked), names))
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    log(f"[diagnostics] {dest}: {len(done)} files ({len(masked)} byte-masked), {len(skipped)} skipped {skipped}")
    return {"files": done, "skipped": skipped, "masked": masked}


def _note(game_name, game_slug, profile_name, profile_slug, manifest, game_dir, app_version, qt_version,
          done, skipped, masked) -> str:
    lines = [
        "VOLT diagnostics", "",
        f"VOLT version: {app_version}",
        f"Game: {game_name} ({game_slug})",
        f"Profile: {profile_name} ({profile_slug})",
        f"Operating system: {platform.platform()}",
        f"Python: {sys.version.split()[0]}",
        f"Qt: {qt_version}",
        f"Game folder: {game_dir or '(not set)'}",
        f"Mods: {_counts(manifest)}",
        f"Saved: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        f"Privacy: the Windows user name is replaced with {MASK} in every text file (logs, settings, configs). "
        "LogOutput.sqlite and its -shm / -wal files" + (" (and the other files marked [masked] below)" if any(
            not a.endswith(SQLITE_FILES) for a in masked) else "") + " are not rewritten: the user name is masked "
        "byte for byte (each letter replaced with *, the file otherwise unchanged) so the database stays readable. "
        "Nothing else is removed: mod configs and logs can still hold other names or folder paths.",
        "",
        f"Files ({len(done)}):",
        *(f"  {a}{'  [masked]' if a in masked else ''}" for a in done),
        "",
        f"Skipped ({len(skipped)}):" if skipped else "Skipped: none",
        *(f"  {a}: {why}" for a, why in skipped),
    ]
    return "\n".join(lines) + "\n"
