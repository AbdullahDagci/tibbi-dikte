"""Dinleme göstergesi: ekranın altında, odak ÇALMAYAN yarı saydam kapsül.

Sol: ses seviyesine göre atan mikrofon küresi ve dalga halkaları. Sağ: bu dikte oturumunda yazılan metin
(beyaz) + o an söylenmekte olan, henüz kesinleşmemiş kısım (gri).
Pencere asla etkinleşmez ve fare olaylarını geçirir; yazılan uygulamadaki imleç yerinde kalır.
"""
from __future__ import annotations

import html
import math
import sys
import time

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QLabel, QWidget

ACCENT = {"listening": QColor("#FF5A5F"), "finishing": QColor("#F5A524"), "done": QColor("#22C55E"),
          "loading": QColor("#8B95A7"), "error": QColor("#F97316")}
CAPTION = {"listening": "DİNLİYOR", "finishing": "SON KELİMELER YAZILIYOR", "done": "YAZILDI",
           "loading": "MODEL YÜKLENİYOR", "error": "HATA"}

W, H, MARGIN, ORB = 600, 96, 18, 64
MAX_CHARS = 105  # ~2 satır


def _no_activate(widget: QWidget) -> None:
    """Windows: WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT — tıklansa bile odak almaz."""
    if sys.platform != "win32":
        return
    import ctypes
    hwnd = int(widget.winId())
    GWL_EXSTYLE = -20
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= 0x08000000 | 0x00000080 | 0x00000020 | 0x00080000  # NOACTIVATE, TOOLWINDOW, TRANSPARENT, LAYERED
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


class ListeningOverlay(QWidget):
    def __init__(self, hotkey_label: str = "Ctrl+Alt+Space"):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.resize(W + 2 * MARGIN, H + 2 * MARGIN)
        self.hotkey_label = hotkey_label
        self.ptt_mode = False
        self.state = "listening"
        self.level = 0.0          # yumuşatılmış seviye
        self._target = 0.0        # son ölçülen seviye
        self.committed = ""
        self.partial = ""
        self._t0 = time.monotonic()

        self.caption = QLabel(self)
        self.caption.setGeometry(MARGIN + ORB + 44, MARGIN + 12, W - ORB - 64, 18)
        self.text = QLabel(self)
        self.text.setGeometry(MARGIN + ORB + 44, MARGIN + 32, W - ORB - 64, H - 40)
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        self.text.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.text.setFont(QFont("Segoe UI", 11))
        self.caption.setFont(QFont("Segoe UI Semibold", 8))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(16)
        self._hide_timer = QTimer(self, singleShot=True)
        self._hide_timer.timeout.connect(self._fade_out)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(260)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._after_fade)
        self._render_text()

    # ------------------------------------------------ dış arayüz
    def start(self) -> None:
        self.committed, self.partial = "", ""
        self._set_state("listening")
        self._place()
        self._hide_timer.stop()
        self._fade.stop()
        self.setWindowOpacity(0.0)
        self.show()
        _no_activate(self)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start()

    def finishing(self) -> None:
        if self.isVisible():
            self._set_state("finishing")

    def done(self) -> None:
        if not self.isVisible():
            return
        self.partial = ""
        self._set_state("done" if self.committed else "listening")
        self._render_text()
        self._hide_timer.start(1400 if self.committed else 300)

    def error(self, msg: str) -> None:
        self.committed, self.partial = msg, ""
        self._set_state("error")
        self._place()
        self.show()
        _no_activate(self)
        self.setWindowOpacity(1.0)
        self._timer.start()
        self._hide_timer.start(3500)

    def set_level(self, v: float) -> None:
        self._target = max(0.0, min(1.0, v))

    def set_partial(self, text: str) -> None:
        self.partial = text
        self._render_text()

    def add_text(self, text: str) -> None:
        self.committed = (self.committed + " " + text.strip()).strip()
        self.partial = ""
        self._render_text()

    # ------------------------------------------------ iç
    def _set_state(self, s: str) -> None:
        self.state = s
        c = ACCENT[s]
        hint = (f"  ·  {self.hotkey_label} ile durdur" if not self.ptt_mode else "  ·  bırakınca durur")             if s == "listening" else ""
        self.caption.setText(f"<span style='color:{c.name()}; letter-spacing:1.5px'>{CAPTION[s]}</span>"
                             f"<span style='color:#7C8698'>{html.escape(hint)}</span>")
        self.update()

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.move(g.center().x() - self.width() // 2, g.bottom() - self.height() - 36)

    def _render_text(self) -> None:
        committed, partial = self.committed, self.partial
        full = (committed + (" " if committed and partial else "") + partial)
        if len(full) > MAX_CHARS:  # sondan göster
            cut = len(full) - MAX_CHARS
            if cut < len(committed):
                committed = "…" + committed[cut:]
            else:
                partial, committed = "…" + partial[cut - len(committed):], ""
        if not committed and not partial:
            body = "<span style='color:#6B7486'>Konuşmaya başlayın…</span>"
        else:
            body = (f"<span style='color:#F4F6FA'>{html.escape(committed)}</span>"
                    + (" " if committed and partial else "")
                    + f"<span style='color:#8D97A8'>{html.escape(partial)}</span>")
        self.text.setText(body)

    def _tick(self) -> None:
        # hızlı yükselme, yavaş sönme
        k = 0.45 if self._target > self.level else 0.08
        self.level += (self._target - self.level) * k
        self._target *= 0.92
        self.update()

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _after_fade(self) -> None:
        if self.windowOpacity() <= 0.01:
            self.hide()
            self._timer.stop()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        body = QRectF(MARGIN, MARGIN, W, H)
        # yumuşak gölge
        for i in range(MARGIN, 0, -2):
            a = int(26 * (1 - i / MARGIN) ** 2)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(body.adjusted(-i, -i + 4, i, i + 4), 28 + i, 28 + i)
        # cam gövde
        path = QPainterPath()
        path.addRoundedRect(body, 28, 28)
        p.fillPath(path, QColor(16, 19, 27, 250))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawPath(path)

        accent = ACCENT[self.state]
        c = QPointF(MARGIN + 22 + ORB / 2, MARGIN + H / 2)
        t = time.monotonic() - self._t0
        lvl = self.level if self.state == "listening" else 0.15
        # dalga halkaları: seviye arttıkça daha geniş ve parlak
        if self.state in ("listening", "finishing"):
            p.save()
            p.setClipPath(path)  # halkalar kapsülün dışına taşmasın
            for i in range(3):
                phase = ((t * (0.9 + lvl * 1.6)) + i / 3) % 1.0
                r = ORB / 2 + 4 + phase * (10 + 22 * lvl)
                a = int((1 - phase) * (70 + 150 * lvl))
                col = QColor(accent)
                col.setAlpha(max(0, min(255, a)))
                p.setPen(QPen(col, 2.0))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, r, r)
            p.restore()
        # küre: parlak çekirdek, seviyeyle hafif büyür; dinlemiyorken yavaş nefes alır
        breathe = 0.04 * math.sin(t * 2.4) if self.state != "listening" else 0
        rad = ORB / 2 * (0.86 + 0.18 * lvl + breathe)
        g = QRadialGradient(c + QPointF(-rad * 0.3, -rad * 0.35), rad * 1.4)
        g.setColorAt(0.0, accent.lighter(150))
        g.setColorAt(0.55, accent)
        g.setColorAt(1.0, accent.darker(160))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, rad, rad)
        self._draw_glyph(p, c)

    def _draw_glyph(self, p: QPainter, c: QPointF) -> None:
        p.setPen(QPen(QColor("white"), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        if self.state == "done":
            path = QPainterPath(c + QPointF(-9, 1))
            path.lineTo(c + QPointF(-3, 7))
            path.lineTo(c + QPointF(10, -7))
            p.drawPath(path)
            return
        # mikrofon: kapsül + kavis + ayak
        p.setBrush(QColor("white"))
        p.drawRoundedRect(QRectF(c.x() - 5, c.y() - 13, 10, 17), 5, 5)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(c.x() - 10, c.y() - 9, 20, 18), 200 * 16, 140 * 16)
        p.drawLine(c + QPointF(0, 9), c + QPointF(0, 14))
        p.drawLine(c + QPointF(-5, 14), c + QPointF(5, 14))
