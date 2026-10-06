# Hidden command-line flag: run this process as the Steam Workshop helper
# (steam_worker.main) instead of opening the GUI. steam_client.py starts
# `VOLT.exe --steam-worker` in a packaged build, where sys.executable is
# VOLT.exe itself and `python -m volt_py.steam_worker` (the dev spawn) has
# no interpreter to run in. Never user-facing.
STEAM_WORKER_FLAG = "--steam-worker"


def main() -> None:
    # Imports are deferred so that importing the volt_py package (or a
    # stdlib-only submodule such as volt_py.sort) does not require PySide6.
    import sys

    # First thing, before any Qt import: the helper must start fast and
    # never show a window (steam_worker.py is stdlib + the binding only).
    if STEAM_WORKER_FLAG in sys.argv[1:]:
        from volt_py.steam_worker import main as steam_worker_main

        sys.exit(steam_worker_main())

    from pathlib import Path

    from PySide6.QtCore import QLockFile

    from volt_py import applog, single_instance
    from volt_py.app_root import resolve_base_root

    # One VOLT per base folder (single_instance.py), checked before the log
    # opens: a refused second VOLT never rotates the running one's logs.
    base = resolve_base_root()
    lock, refused = single_instance.acquire(base, QLockFile)
    if not refused:
        # The app-wide log (<base>/logs/, applog.py), first: everything from here
        # on - game select, the startup update check, a crash - is recorded. The
        # Steam helper above never opens it (its stderr is relayed into it).
        applog.init_log(base)
        if lock is None:
            applog.log(f"single-instance lock {base / single_instance.LOCK_NAME} couldn't be taken; running without it")

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from volt_py import steam_client
    from volt_py.main_window import MainWindow
    from volt_py.theme import apply_theme

    if sys.platform == "win32":
        # Own taskbar identity (not python.exe's), so the taskbar shows VOLT's
        # icon and groups its windows, in dev runs too. Must precede any window.
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Vokaerian.VOLT")
        except (AttributeError, OSError):
            pass

    app = QApplication(sys.argv)
    # Every window (main, Issues, dialogs) inherits it. volt_py/assets/ is
    # next to this file in dev and packaged builds alike (--include-data-dir).
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "assets" / "icon" / "volt.ico")))
    apply_theme(app)
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    server_name = single_instance.server_name(base)
    if refused:
        # The running VOLT brings its window forward and says so; only when it
        # can't be reached (an older or hung VOLT) does this one show the box.
        if not single_instance.notify_first(QLocalSocket, server_name):
            from volt_py.screens.error_box import show_error

            show_error(None, single_instance.TITLE, single_instance.WHAT,
                       means=single_instance.MEANS, tryit=single_instance.TRYIT)
        sys.exit(single_instance.EXIT_ALREADY_RUNNING)
    # Electron main.js's will-quit: stop any Steam helper process still
    # running (steam_client.stop_all: asks each to shut down and closes its
    # pipe, which ends it on its own; not waited on, so quitting never stalls).
    app.aboutToQuit.connect(lambda: steam_client.stop_all(wait=False))
    window = MainWindow()
    window.show()

    def bring_forward() -> None:
        from PySide6.QtCore import Qt

        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
        window.show()
        window.raise_()
        window.activateWindow()
        applog.log("another VOLT was started from this folder: brought this window forward instead")

    # Only the lock holder serves; an unguarded run (no lock) doesn't claim the name either.
    server = single_instance.listen(QLocalServer, server_name, bring_forward) if lock is not None else None
    if lock is not None and server is None:
        applog.log(f"single-instance: couldn't listen on {server_name}; a second VOLT will show its box instead")
    try:
        code = app.exec()
    finally:
        if server is not None:
            server.close()  # before the lock: no second VOLT is told "raised" by one that is leaving
        if lock is not None:
            lock.unlock()  # deletes volt.lock; the updater's apply.bat waits for this process to end anyway
    sys.exit(code)
