"""One VOLT per base folder (0.6.46): a second VOLT.exe started against the
same <base> (app_root.resolve_base_root - so dev, packaged and VOLT_APP_ROOT
folders stay independent) shows one message and exits, before it opens the
log, so the running VOLT's volt.log and crash log are never rotated away.

The lock is Qt's QLockFile at <base>/volt.lock (passed in as lock_file_cls,
so tools/checks/volt_py_single_instance.py runs this without PySide6). Held
until the app's event loop ends (volt_py.main unlocks it, which deletes the
file). A lock left by a crashed or killed VOLT is recovered by QLockFile
itself: the pid it names is no longer running (or is now another program),
so tryLock removes it. Time-based staleness is off (setStaleLockTime(0)):
Qt's default 30 s would let a second VOLT take over from one running longer.
Bring forward (0.6.46, user-greenlit custom work): the running VOLT also
listens on a QLocalServer named per base folder (server_name). A refused VOLT
connects, sends RAISE_MSG and waits for ACK_MSG: then the first window has
come forward and the second just exits (no box). No answer (an older VOLT
without the server, a hung one): the "already running" box instead. Anything
but RAISE_MSG is ignored and the connection closed; no other commands exist.
QtNetwork's classes are passed in (server_cls / socket_cls), so this file
stays importable without PySide6."""

import hashlib
import os
import sys
from pathlib import Path

LOCK_NAME = "volt.lock"
EXIT_ALREADY_RUNNING = 2
TITLE = "VOLT is already running"
WHAT = "VOLT is already open."
MEANS = "Only one VOLT can run from the same folder at a time, so this second one closes."
RAISE_MSG = b"raise\n"
ACK_MSG = b"ok\n"
MAX_MSG = 64  # read at most this much from a connection
WAIT_MS = 1500


TRYIT = ("Look for VOLT's window on the taskbar (it may be behind other windows or on another screen). "
         "If you just closed VOLT, wait a few seconds and start it again.")


def acquire(base, lock_file_cls):
    """(lock, refused). refused: another VOLT holds <base>/volt.lock. lock is
    None and refused False when the lock couldn't be taken for another reason
    (a read-only folder): VOLT runs anyway, unguarded. Never raises."""
    try:
        Path(base).mkdir(parents=True, exist_ok=True)
        lock = lock_file_cls(str(Path(base) / LOCK_NAME))
        lock.setStaleLockTime(0)
        if lock.tryLock(0):
            return lock, False
        return None, lock.error() == lock_file_cls.LockError.LockFailedError
    except Exception:
        return None, False


def server_name(base) -> str:
    """The local-server name for this base folder: a hash of its normalised
    path (case-folded on Windows), so dev / packaged / VOLT_APP_ROOT folders
    each get their own and no path characters reach the pipe name."""
    key = os.path.normcase(os.path.abspath(str(base)))
    return "VOLT-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def wants_raise(data: bytes) -> bool:
    return data[:MAX_MSG].strip() == RAISE_MSG.strip()


def listen(server_cls, name: str, on_raise):
    """The running VOLT: serve `name` (a stale one from a crash removed
    first). A connection that sends RAISE_MSG gets on_raise() then ACK_MSG;
    anything else is ignored. Every connection is closed after its first
    read. Returns the server (keep it, close() it before the lock is
    released) or None when it can't listen (VOLT runs on, nothing raised)."""
    try:
        server_cls.removeServer(name)
        server = server_cls()
        if not server.listen(name):
            return None
    except Exception:
        return None

    def take(sock):
        try:
            if wants_raise(bytes(sock.read(MAX_MSG).data())):
                on_raise()
                sock.write(ACK_MSG)
            sock.disconnectFromServer()  # graceful: the ack is written first
        except Exception:
            pass  # a client gone mid-read: nothing to do

    def on_new():
        while server.hasPendingConnections():
            sock = server.nextPendingConnection()
            sock.disconnected.connect(sock.deleteLater)
            sock.readyRead.connect(lambda s=sock: take(s))

    server.newConnection.connect(on_new)
    return server


def notify_first(socket_cls, name: str, wait_ms: int = WAIT_MS) -> bool:
    """The refused VOLT: ask the running one to bring its window forward.
    True only when it answered ACK_MSG. Never raises."""
    allow_foreground()
    try:
        sock = socket_cls()
        sock.connectToServer(name)
        if not sock.waitForConnected(wait_ms):
            return False
        if sock.write(RAISE_MSG) != len(RAISE_MSG):
            return False
        sock.waitForBytesWritten(wait_ms)
        ok = sock.waitForReadyRead(wait_ms) and bytes(sock.readAll().data()).strip() == ACK_MSG.strip()
        sock.abort()
        return bool(ok)
    except Exception:
        return False


def allow_foreground() -> None:
    """Windows only lets the foreground process hand the foreground on: this
    VOLT was just started by the user, so it may - ASFW_ANY lets the running
    VOLT's activateWindow() actually come to the front instead of only
    flashing its taskbar button."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except (AttributeError, OSError):
        pass
