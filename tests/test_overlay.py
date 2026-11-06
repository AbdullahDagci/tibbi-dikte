"""Dinleme göstergesinin ekrandaki konumu."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.overlay import ListeningOverlay  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_overlay_sits_in_bottom_right_corner_inside_the_screen(qapp):
    overlay = ListeningOverlay()
    overlay._place()
    screen = QGuiApplication.primaryScreen().availableGeometry()
    frame = overlay.geometry()
    assert screen.contains(frame), (screen, frame)
    assert screen.right() - frame.right() <= 24
    assert screen.bottom() - frame.bottom() <= 24
    overlay.deleteLater()
