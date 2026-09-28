def main() -> None:
    # Imports are deferred so that importing the volt_py package (or a
    # stdlib-only submodule such as volt_py.sort) does not require PySide6.
    import sys

    from PySide6.QtWidgets import QApplication

    from volt_py import steam_client
    from volt_py.main_window import MainWindow
    from volt_py.theme import apply_theme

    app = QApplication(sys.argv)
    apply_theme(app)
    # Electron main.js's will-quit: stop any Steam helper process still
    # running (steam_client.stop_all: asks each to shut down and closes its
    # pipe, which ends it on its own; not waited on, so quitting never stalls).
    app.aboutToQuit.connect(lambda: steam_client.stop_all(wait=False))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
