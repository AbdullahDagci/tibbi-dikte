"""Arayüz temel bileşenleri: ikonlar, düğme türleri, göstergeler."""
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import theme  # noqa: E402
from app.ui import widgets  # noqa: E402
from app.ui.icons import icon  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ICON_USE = re.compile(r"""(?:\bicon\(|\bicon=|\bicon_button\(|\bpixmap\()\s*"([a-z0-9-]+)\"""")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_icon_is_painted_in_the_requested_color(qapp):
    image = icon("search", "#D92D52").pixmap(24, 24).toImage()
    colors = {QColor(image.pixel(x, y)).name() for x in range(24) for y in range(24)
              if QColor(image.pixelColor(x, y)).alpha() == 255}
    assert "#d92d52" in colors


def test_missing_icon_does_not_crash_the_app(qapp):
    assert icon("yok-boyle-ikon", "#000000").isNull()


def test_every_icon_named_in_the_source_exists():
    used = set()
    for path in (ROOT / "app").rglob("*.py"):
        used |= set(ICON_USE.findall(path.read_text(encoding="utf-8")))
    assert used, "kaynakta ikon kullanımı bulunamadı"
    missing = [name for name in used if not (ROOT / "app" / "icons" / f"{name}.svg").is_file()]
    assert not missing


@pytest.mark.parametrize("variant", ["primary", "success", "danger", "light", "info"])
def test_button_variant_has_its_own_style_rule(qapp, variant):
    assert f'QPushButton[variant="{variant}"]' in theme.QSS
    assert widgets.button("Kaydet", icon="device-floppy", variant=variant).property("variant") == variant


def test_changing_variant_keeps_text_and_updates_property(qapp):
    b = widgets.button("Başlat", icon="player-record", variant="primary")
    widgets.set_variant(b, "danger", icon="player-stop")
    assert b.property("variant") == "danger" and b.text() == "Başlat" and not b.icon().isNull()


def test_stat_tile_shows_value_sub_and_color(qapp):
    tile = widgets.StatTile("Kelime doğruluğu", icon="chart-bar")
    assert tile.value.text() == "—"
    tile.set("%98,1", "ham model: %91,2", theme.GOOD)
    assert tile.value.text() == "%98,1" and tile.sub.text() == "ham model: %91,2"
    assert theme.GOOD in tile.value.styleSheet()


@pytest.mark.parametrize("kind", ["success", "warning", "danger", "info", "muted"])
def test_badge_kind_has_its_own_style_rule(qapp, kind):
    assert f'QLabel[badge="{kind}"]' in theme.QSS
    badge = widgets.Badge("Hazır", kind)
    assert badge.text() == "Hazır" and badge.property("badge") == kind


def test_switch_toggles_when_clicked_anywhere_on_it(qapp):
    s = widgets.Switch()
    s.resize(s.sizeHint())
    assert s.sizeHint().width() > s.sizeHint().height()
    QTest.mouseClick(s, Qt.LeftButton, pos=QPoint(s.width() - 4, s.height() // 2))
    assert s.isChecked()
    QTest.mouseClick(s, Qt.LeftButton, pos=QPoint(4, s.height() // 2))
    assert not s.isChecked()


def test_card_holds_content_and_title(qapp):
    from PySide6.QtWidgets import QLabel
    card = widgets.Card("Model ve ses", icon="cpu")
    card.body.addWidget(QLabel("içerik"))
    assert card.objectName() == "card"
    assert any(label.text() == "Model ve ses" for label in card.findChildren(QLabel))
    assert any(label.text() == "içerik" for label in card.findChildren(QLabel))


def test_info_tip_keeps_explanation_in_tooltip(qapp):
    tip = widgets.InfoTip("Uzun açıklama burada durur.")
    assert tip.toolTip() == "Uzun açıklama burada durur." and tip.text() == ""


def test_collapsible_hides_and_shows_its_body(qapp):
    from PySide6.QtWidgets import QLabel
    box = widgets.Collapsible("Dene", icon="wand", expanded=False)
    box.body.addWidget(QLabel("x"))
    box.show()
    assert not box.content.isVisible()
    box.toggle_button.click()
    assert box.content.isVisible()
    box.hide()
    box.deleteLater()
