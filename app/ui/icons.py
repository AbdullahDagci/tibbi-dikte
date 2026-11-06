"""Tabler Icons (MIT): app/icons altındaki SVG'ler istenen renkte çizilir ve önbelleğe alınır."""
from __future__ import annotations

import logging
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..paths import resource_dir

log = logging.getLogger(__name__)
_SIZES = (16, 18, 20, 24, 32, 48, 64, 128)
_LOGO_BACKGROUND = b"#1B6FD8"  # logo.svg içindeki zemin rengi


def _render(svg: bytes, size: int) -> QPixmap:
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg)).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


@lru_cache(maxsize=256)
def icon(name: str, color: str) -> QIcon:
    """Adı verilen ikon; dosya yoksa boş ikon döner ve uygulama çalışmaya devam eder."""
    path = resource_dir() / "icons" / f"{name}.svg"
    try:
        svg = path.read_bytes().replace(b"currentColor", color.encode("ascii"))
    except OSError:
        log.warning("İkon bulunamadı: %s", path)
        return QIcon()
    return _from_svg(svg)


def _from_svg(svg: bytes) -> QIcon:
    result = QIcon()
    for size in _SIZES:
        result.addPixmap(_render(svg, size))
    return result


@lru_cache(maxsize=16)
def logo_icon(background: str) -> QIcon:
    """Logonun verilen zemin rengindeki hâli: tepsi simgesi dikte durumunu bu renkle gösterir."""
    path = resource_dir() / "icons" / "logo.svg"
    try:
        svg = path.read_bytes().replace(_LOGO_BACKGROUND, background.encode("ascii"))
    except OSError:
        log.warning("Logo bulunamadı: %s", path)
        return QIcon()
    return _from_svg(svg)


def pixmap(name: str, color: str, size: int = 18) -> QPixmap:
    return icon(name, color).pixmap(size, size)
