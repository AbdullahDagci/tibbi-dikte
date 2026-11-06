"""app/icons/logo.svg dosyasından Windows simgesini (logo.ico) üretir: exe, kurulum ve kısayollar bunu kullanır.

Kullanım: python tools/make_logo.py   (logo değişince bir kez çalıştırılır, çıktı depoya girer)
"""
from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "app" / "icons" / "logo.svg"
ICO = ROOT / "app" / "icons" / "logo.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _png(svg: bytes, size: int) -> bytes:
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg)).render(painter, QRectF(0, 0, size, size))
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def ico_bytes(svg: bytes, sizes: tuple[int, ...] = SIZES) -> bytes:
    """Her boyutu PNG olarak içeren .ico dosyası (Windows Vista ve sonrası destekler)."""
    images = [_png(svg, size) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for size, data in zip(sizes, images):
        side = 0 if size >= 256 else size  # ICO biçiminde 256, 0 olarak yazılır
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return header + entries + b"".join(images)


def main() -> None:
    ICO.write_bytes(ico_bytes(SVG.read_bytes()))
    print(ICO, ICO.stat().st_size, "bayt")


if __name__ == "__main__":
    main()
