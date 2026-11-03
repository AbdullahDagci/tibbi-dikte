"""Giriş noktası: python -m app.main"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from .paths import user_dir


def setup_logging() -> None:
    h = RotatingFileHandler(user_dir() / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h])


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Tıbbi Dikte")
    app.setQuitOnLastWindowClosed(False)
    from . import theme
    theme.apply(app)

    lock = QLockFile(str(user_dir() / "app.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "Tıbbi Dikte", "Uygulama zaten çalışıyor (sistem tepsisine bakın).")
        return 0

    from .tray import TrayApp
    tray = TrayApp(app)
    tray.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
