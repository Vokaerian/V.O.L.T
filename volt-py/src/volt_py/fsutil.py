"""Small filesystem helpers (subset of Electron's src/electron/lib/fsutil.js).

Plain synchronous pathlib/os - Node's async dance isn't needed in Python.
"""

import errno
import json
import os
from pathlib import Path
from typing import Any


def exists(p) -> bool:
    return bool(p) and os.path.exists(p)


def is_dir(p) -> bool:
    return bool(p) and os.path.isdir(p)


def read_text(p) -> str:
    # utf-8-sig strips a leading BOM, matching fsutil.js's stripBom.
    return Path(p).read_text(encoding="utf-8-sig")


def read_json(p) -> Any:
    return json.loads(read_text(p))


def write_text_atomic(file, text: str) -> None:
    """Atomic write: temp sibling + os.replace, so a crash mid-write never
    leaves a truncated file behind. Text is written as-is (utf-8, no newline
    translation), so CRLF/LF and a leading BOM survive untouched."""
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(f"{file.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, file)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json(file, obj) -> None:
    # JSON.stringify output is LF everywhere. default=str: Path values
    # (paths.py returns Path) are stored as plain strings.
    write_text_atomic(file, json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")


def find_child_ci(dir, name: str) -> Path | None:
    """Case-insensitive child lookup (exact match first); None if `dir` is
    unreadable or has no match."""
    try:
        entries = os.listdir(dir)
    except OSError:
        return None
    if name in entries:
        return Path(dir) / name
    lower = name.lower()
    hit = next((e for e in entries if e.lower() == lower), None)
    return Path(dir) / hit if hit else None


def _err_code(err: BaseException) -> str:
    """fsutil.js's `err.code || err.message`: the errno name (EACCES, EBUSY,
    ENOTEMPTY...) when there is one, else the message."""
    code = errno.errorcode.get(getattr(err, "errno", None) or 0)
    return code or str(err) or repr(err)


_is_junction = getattr(os.path, "isjunction", lambda p: False)  # 3.12+; a junction is a link, never walked


def is_link(p) -> bool:
    """A symlink or (Windows) junction: removed as a link, never walked into."""
    return os.path.islink(p) or _is_junction(p)


def rmtree_force(dir) -> None:
    """shutil.rmtree that also removes Windows read-only files (a Workshop
    mod's files can carry the attribute; a plain rmtree stops at the first
    one): one chmod-and-retry per refused entry. Raises like rmtree otherwise.
    rmtree itself never follows a symlink / junction inside the tree."""
    import shutil
    import stat
    import sys

    def retry(func, path, _exc) -> None:
        os.chmod(path, stat.S_IWRITE)
        func(path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(dir, onexc=retry)
    else:  # the device-shell harnesses run 3.10
        shutil.rmtree(dir, onerror=retry)


def remove_tree_best_effort(dir) -> dict:
    """Best-effort recursive delete (fsutil.js removeTreeBestEffort:
    Unsubscribe's Workshop-folder cleanup, a SteamCMD copy's removal):
    removes every file and folder it can and skips - never aborts on - one it
    can't (e.g. a file the running game holds open on Windows). A file whose
    unlink is refused (read-only) gets one chmod-and-retry. Links are removed,
    never followed (a symlink / junction to a folder is unlinked as a link:
    os.unlink, or os.rmdir where Windows insists on it - the target is left
    alone). Returns {"removed": files removed, "skipped": [{"path", "error"}]
    for what was left behind (a folder is only listed when its own removal
    failed for a reason other than still holding skipped files), "gone":
    whether `dir` no longer exists}. A missing `dir` is {0, [], True}."""
    removed = 0
    skipped: list[dict] = []

    def skip(p, err) -> None:
        skipped.append({"path": str(p), "error": _err_code(err)})

    def unlink(p, dir_link: bool) -> None:
        try:
            os.unlink(p)
        except IsADirectoryError:  # a link to a folder, on a platform that won't unlink() it
            os.rmdir(p)
        except PermissionError:
            if dir_link:  # Windows: a directory symlink / junction is removed as a directory
                os.rmdir(p)
                return
            os.chmod(p, 0o666)
            os.unlink(p)

    def walk(d) -> None:
        nonlocal removed
        try:
            entries = list(os.scandir(d))
        except FileNotFoundError:
            return
        except OSError as err:
            skip(d, err)
            return
        for e in entries:
            if e.is_dir(follow_symlinks=False) and not _is_junction(e.path):
                walk(e.path)
                continue
            try:
                unlink(e.path, e.is_dir())  # is_dir() follows the link: a link to a folder
                removed += 1
            except FileNotFoundError:
                pass
            except OSError as err:
                skip(e.path, err)
        try:
            os.rmdir(d)
        except FileNotFoundError:
            pass
        except OSError as err:
            if err.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                skip(d, err)

    walk(str(dir))
    return {"removed": removed, "skipped": skipped, "gone": not exists(dir)}


def is_dds_only_leftover(dir, exclude_about_folder: bool = False) -> bool:
    """True if `dir` holds at least one file and every file (recursively) is a
    .dds texture - a texture-compression leftover, not a real mod.
    `exclude_about_folder` skips a top-level About folder. An unreadable folder,
    or any symlink (never followed, like the JS's lstat-based Dirent), counts
    as "not a leftover"."""
    files = 0

    def walk(d, top: bool) -> bool:
        nonlocal files
        try:
            entries = list(os.scandir(d))
        except OSError:
            return False
        for e in entries:
            if e.is_dir(follow_symlinks=False):
                if top and exclude_about_folder and e.name.lower() == "about":
                    continue
                if not walk(e.path, False):
                    return False
                continue
            if not e.is_file(follow_symlinks=False) or os.path.splitext(e.name)[1].lower() != ".dds":
                return False
            files += 1
        return True

    return walk(dir, True) and files > 0
