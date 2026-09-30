def main() -> None:
    # Imports are deferred so that importing the volt_py package (or a
    # stdlib-only submodule such as volt_py.sort) does not require PySide6.
    import sys

    from pathlib import Path

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
    # Electron main.js's will-quit: stop any Steam helper process still
    # running (steam_client.stop_all: asks each to shut down and closes its
    # pipe, which ends it on its own; not waited on, so quitting never stalls).
    app.aboutToQuit.connect(lambda: steam_client.stop_all(wait=False))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
