"""Tüm ekranlarda ortak kullanılan bileşenler: düğme, kart, skor kutusu, rozet, anahtar, ipucu, daralan bölüm."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import theme
from .icons import icon as make_icon
from .icons import pixmap as make_pixmap

_ICON_COLOR = {"primary": "#FFFFFF", "success": "#FFFFFF", "danger": "#FFFFFF", "info": "#FFFFFF",
               "light": theme.PRIMARY, "ghost": theme.MUTED, "ghost-danger": theme.DANGER, "link": theme.TEXT}


def repolish(widget: QWidget) -> None:
    """Dinamik özellik değişince stil sayfasının yeniden uygulanması için."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_variant(btn: QPushButton, variant: str, icon: str | None = None) -> None:
    name = icon or btn.property("icon_name")
    btn.setProperty("variant", variant)
    if name:
        btn.setProperty("icon_name", name)
        btn.setIcon(make_icon(name, _ICON_COLOR[variant]))
    repolish(btn)


def button(text: str = "", icon: str | None = None, variant: str = "light", tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setIconSize(QSize(16, 16))
    if tooltip:
        btn.setToolTip(tooltip)
    set_variant(btn, variant, icon)
    return btn


def icon_button(icon: str, tooltip: str, variant: str = "ghost") -> QPushButton:
    return button("", icon, variant, tooltip)


class Card(QFrame):
    """Başlıklı beyaz kart. İçerik `body` yerleşimine eklenir, başlık sağına düğme `add_action` ile."""

    def __init__(self, title: str = "", icon: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._header = QHBoxLayout()
        self._header.setContentsMargins(18, 13, 18, 13)
        self._header.setSpacing(8)
        if title:
            if icon:
                glyph = QLabel()
                glyph.setPixmap(make_pixmap(icon, theme.PRIMARY, 18))
                self._header.addWidget(glyph)
            heading = QLabel(title)
            heading.setObjectName("cardHeading")
            self._header.addWidget(heading)
            self._header.addStretch()
            outer.addLayout(self._header)
            rule = QFrame()
            rule.setObjectName("cardRule")
            outer.addWidget(rule)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(18, 14, 18, 16)
        self.body.setSpacing(10)
        outer.addLayout(self.body, 1)

    def add_action(self, widget: QWidget) -> None:
        self._header.addWidget(widget)


class StatTile(QFrame):
    """Başlık + büyük değer + alt açıklama."""

    def __init__(self, title: str, icon: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("statTile")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(6)
        if icon:
            glyph = QLabel()
            glyph.setPixmap(make_pixmap(icon, theme.MUTED, 15))
            head.addWidget(glyph)
        label = QLabel(title)
        label.setObjectName("statTitle")
        label.setWordWrap(True)
        head.addWidget(label, 1)
        v.addLayout(head)
        self.value = QLabel("—")
        self.value.setObjectName("statValue")
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        self.sub.setWordWrap(True)
        v.addWidget(self.value)
        v.addWidget(self.sub)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color:{color}" if color else "")
        self.sub.setText(sub)


class Badge(QLabel):
    def __init__(self, text: str = "", kind: str = "muted", parent=None):
        super().__init__(text, parent)
        self.setProperty("badge", kind)
        self.setAlignment(Qt.AlignCenter)

    def set_state(self, text: str, kind: str) -> None:
        self.setText(text)
        self.setProperty("badge", kind)
        repolish(self)


class InfoTip(QLabel):
    """Ekranda metin yerine küçük bilgi simgesi; açıklama fare üzerine gelince görünür."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setPixmap(make_pixmap("info-circle", theme.MUTED, 16))
        self.setToolTip(text)
        self.setCursor(Qt.WhatsThisCursor)


class Switch(QCheckBox):
    """Aç/kapa anahtarı: QCheckBox ile aynı arayüz, yalnızca çizimi farklı."""

    _W, _H = 38, 20

    def sizeHint(self) -> QSize:
        return QSize(self._W, self._H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QColor(theme.PRIMARY if self.isChecked() else "#C5CDD9")
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self._W, self._H), self._H / 2, self._H / 2)
        p.setBrush(QColor("white"))
        x = self._W - self._H + 3 if self.isChecked() else 3
        p.drawEllipse(QRectF(x, 3, self._H - 6, self._H - 6))
        p.end()


def switch_row(text: str, switch: Switch, tip: str = "") -> QWidget:
    """Solda etiket (varsa bilgi simgesi), sağda anahtar."""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 3, 0, 3)
    h.setSpacing(6)
    h.addWidget(QLabel(text))
    if tip:
        h.addWidget(InfoTip(tip))
    h.addStretch()
    h.addWidget(switch)
    return row


class Collapsible(QWidget):
    """Başlığına tıklanınca açılıp kapanan bölüm; içerik `body` yerleşimine eklenir."""

    def __init__(self, title: str, icon: str | None = None, expanded: bool = False, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.toggle_button = button(title, icon, "link")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.toggled.connect(self._toggled)
        v.addWidget(self.toggle_button, alignment=Qt.AlignLeft)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.content, 1)
        self.content.setVisible(expanded)

    def _toggled(self, on: bool) -> None:
        self.content.setVisible(on)
