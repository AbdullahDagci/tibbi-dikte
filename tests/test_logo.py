"""Uygulama logosu: pencere, tepsi durumları ve Windows simgesi."""
import os
import re
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import theme  # noqa: E402
from app.tray import STATE_STYLE, make_icon  # noqa: E402
from app.ui.icons import icon, logo_icon  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from make_logo import ico_bytes  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _colors(q_icon, size=64):
    image = q_icon.pixmap(size, size).toImage()
    return {QColor(image.pixel(x, y)).name() for x in range(image.width()) for y in range(image.height())
            if image.pixelColor(x, y).alpha() == 255}


def test_logo_is_white_stethoscope_on_blue(qapp):
    colors = _colors(icon("logo", theme.PRIMARY))
    assert {theme.PRIMARY.lower(), "#ffffff"} <= colors


def test_logo_uses_the_same_stethoscope_drawing_as_the_app(qapp):
    icons = ROOT / "app" / "icons"
    drawing = re.findall(r'<path d="([^"]+)"', (icons / "stethoscope.svg").read_text(encoding="utf-8"))
    logo = (icons / "logo.svg").read_text(encoding="utf-8")
    assert drawing and all(d in logo for d in drawing)


@pytest.mark.parametrize("state", list(STATE_STYLE))
def test_tray_icon_shows_logo_in_state_color(qapp, state):
    color = STATE_STYLE[state][0]
    colors = _colors(make_icon(color))
    assert color.lower() in colors and "#ffffff" in colors


def test_ready_tray_icon_matches_application_logo(qapp):
    assert STATE_STYLE["idle"][0] == theme.PRIMARY
    assert _colors(make_icon(STATE_STYLE["idle"][0])) == _colors(icon("logo", theme.PRIMARY))


def test_tray_states_can_be_told_apart(qapp):
    assert _colors(logo_icon(theme.DANGER)) != _colors(logo_icon(theme.PRIMARY))


def _ico_sizes(data):
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1)
    sizes = []
    for i in range(count):
        width, height, _, _, _, _, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        assert width == height
        assert data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n" and offset + length <= len(data)
        sizes.append(width or 256)
    return sizes


def test_windows_icon_file_contains_all_sizes():
    data = (ROOT / "app" / "icons" / "logo.ico").read_bytes()
    assert _ico_sizes(data) == [16, 24, 32, 48, 64, 128, 256]


def test_icon_builder_writes_requested_sizes(qapp):
    svg = (ROOT / "app" / "icons" / "logo.svg").read_bytes()
    assert _ico_sizes(ico_bytes(svg, (16, 256))) == [16, 256]


def test_packaging_uses_the_logo():
    assert 'icon="app/icons/logo.ico"' in (ROOT / "TibbiDikte.spec").read_text(encoding="utf-8")
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert r"SetupIconFile=..\app\icons\logo.ico" in iss and "UninstallDisplayIcon=" in iss


def test_installer_refreshes_windows_icon_cache():
    """Eski sürümün simgesi Windows önbelleğinde kalmasın: güncellemeden sonra masaüstü ve görev çubuğu yenilensin."""
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert "ChangesAssociations=yes" in iss
    run = iss[iss.index("[Run]"):]
    refresh = next(line for line in run.splitlines() if "ie4uinit.exe" in line)
    assert '"-show"' in refresh and "runhidden" in refresh and "runasoriginaluser" in refresh
    assert "skipifdoesntexist" in refresh
