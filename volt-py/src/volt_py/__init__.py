import sys

from PySide6.QtWidgets import QApplication

from volt_py.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
