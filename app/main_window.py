"""Ana pencere: sol menü, üst başlık çubuğu ve sayfalar. Sayfalar ilk açıldığında oluşturulur ve durumlarını korur."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import __version__, theme
from .collect import CollectPage
from .config import Config
from .editor import EditorPage
from .lexicon_editor import LexiconPage
from .settings_window import AboutPage, LicensePage, SettingsPage
from .testbench import TestPage
from .ui import widgets
from .ui.icons import pixmap as icon_pixmap

log = logging.getLogger(__name__)

NAV_GROUPS = (
    ("DİKTE", (("dictate", "Dikte", "microphone"), ("test", "Test ve doğruluk", "flask"),
               ("collect", "Veri toplama", "database"), ("lexicon", "Sözlük", "book-2"))),
    ("SİSTEM", (("settings", "Ayarlar", "settings"), ("license", "Lisans", "license"),
                ("about", "Hakkında", "info-circle"))),
)
TITLES = {name: title for _, items in NAV_GROUPS for name, title, _ in items}
OPEN_WITHOUT_LICENSE = {"license", "about"}
STATE_BADGE = {
    "idle": ("Hazır", "success"),
    "listening": ("Dinliyor", "danger"),
    "loading": ("Model yükleniyor", "info"),
    "error": ("Hata", "danger"),
    "unlicensed": ("Lisans gerekli", "warning"),
}


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config, get_pipeline: Callable[[], tuple], term_files: list[Path], lexicon_path: Path,
                 corrections_path: Path, hotkey_label: str, on_toggle: Callable[[], None] | None = None,
                 on_dictionary_changed: Callable[[], None] | None = None,
                 on_settings_changed: Callable[[bool], None] | None = None,
                 on_license_changed: Callable[[], None] | None = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._get_pipeline, self._term_files = get_pipeline, term_files
        self._lexicon_path, self._corrections_path = lexicon_path, corrections_path
        self._hotkey_label = hotkey_label
        self._on_toggle, self._on_dictionary_changed = on_toggle, on_dictionary_changed
        self._on_settings_changed, self._on_license_changed = on_settings_changed, on_license_changed
        self._pages: dict[str, QWidget] = {}
        self._licensed = True
        self._state = "idle"

        self.setWindowTitle("Tıbbi Dikte")
        self.setWindowIcon(theme.app_icon())
        self.setMinimumSize(960, 620)
        self.resize(1180, 760)
        self.nav_buttons: dict[str, QPushButton] = {}
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        self.stack = QStackedWidget()
        self.stack.setObjectName("pages")
        self.title_label = QLabel()
        self.title_label.setObjectName("pageTitle")
        self.model_label = QLabel()
        self.model_label.setObjectName("muted")
        self.state_badge = widgets.Badge("Hazır", "success")
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(22, 12, 22, 12)
        top.setSpacing(12)
        top.addWidget(self.title_label)
        top.addStretch()
        top.addWidget(self.model_label)
        top.addWidget(self.state_badge)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(topbar)
        cv.addWidget(self.stack, 1)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())
        h.addWidget(content, 1)
        self.setCentralWidget(root)
        self._restore_geometry()
        self.show_page("dictate")

    # ------------------------------------------------------------ sol menü
    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        v = QVBoxLayout(side)
        v.setContentsMargins(14, 16, 14, 14)
        v.setSpacing(4)
        brand_icon = QLabel()
        brand_icon.setObjectName("brandLogo")
        brand_icon.setPixmap(icon_pixmap("stethoscope", "#FFFFFF", 26))
        brand = QLabel("Tıbbi Dikte")
        brand.setObjectName("brand")
        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 0, 12)
        head.setSpacing(10)
        head.addWidget(brand_icon)
        head.addWidget(brand)
        head.addStretch()
        v.addLayout(head)
        for group, items in NAV_GROUPS:
            caption = QLabel(group)
            caption.setObjectName("navGroup")
            caption.setContentsMargins(10, 12, 0, 4)
            v.addWidget(caption)
            for name, title, icon in items:
                v.addWidget(self._nav_button(name, title, icon))
        v.addStretch()
        version = QLabel(f"Sürüm {__version__}")
        version.setObjectName("sidebarNote")
        version.setContentsMargins(10, 0, 0, 0)
        v.addWidget(version)
        return side

    def _nav_button(self, name: str, title: str, icon_name: str) -> QPushButton:
        btn = QPushButton(title)
        btn.setProperty("nav", True)
        btn.setProperty("page_name", name)
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        icon = QIcon()
        icon.addPixmap(icon_pixmap(icon_name, theme.SIDEBAR_TEXT, 18), QIcon.Normal, QIcon.Off)
        icon.addPixmap(icon_pixmap(icon_name, "#FFFFFF", 18), QIcon.Normal, QIcon.On)
        icon.addPixmap(icon_pixmap(icon_name, "#51657F", 18), QIcon.Disabled, QIcon.Off)
        btn.setIcon(icon)
        btn.setIconSize(QSize(18, 18))
        btn.clicked.connect(self._nav_clicked)
        self._nav_group.addButton(btn)
        self.nav_buttons[name] = btn
        return btn

    def _nav_clicked(self) -> None:
        self.show_page(self.sender().property("page_name"))
        self.stack.currentWidget().setFocus()  # odak menü düğmesinde kalmasın: sayfa kısayolları çalışsın

    # ------------------------------------------------------------ sayfalar
    def show_page(self, name: str) -> None:
        if name not in TITLES:
            name = "dictate"
        if not self._licensed and name not in OPEN_WITHOUT_LICENSE:
            name = "license"
        page = self._pages.get(name)
        if page is None:
            page = self._make_page(name)
            self._pages[name] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        self.title_label.setText(TITLES[name])
        self.nav_buttons[name].setChecked(True)

    def current_page_name(self) -> str:
        current = self.stack.currentWidget()
        return next((n for n, p in self._pages.items() if p is current), "")

    def _make_page(self, name: str) -> QWidget:
        if name == "dictate":
            page = EditorPage(self._lexicon_path, self._corrections_path, self._hotkey_label,
                              on_toggle=self._on_toggle, on_dictionary_changed=self.dictionary_changed)
            page.set_listening(self._state == "listening")
            return page
        if name == "test":
            return TestPage(self._get_pipeline, self._term_files)
        if name == "collect":
            return CollectPage(self._get_pipeline)
        if name == "lexicon":
            page = LexiconPage(self._lexicon_path, self._corrections_path)
            page.saved.connect(self._lexicon_saved)
            return page
        if name == "settings":
            page = SettingsPage(self.cfg)
            page.settings_changed.connect(self._settings_saved)
            return page
        if name == "license":
            page = LicensePage()
            page.license_changed.connect(self._license_activated)
            return page
        return AboutPage()

    @property
    def dictate_page(self) -> EditorPage | None:
        return self._pages.get("dictate")

    @property
    def test_page(self) -> TestPage | None:
        return self._pages.get("test")

    @property
    def collect_page(self) -> CollectPage | None:
        return self._pages.get("collect")

    @property
    def lexicon_page(self) -> LexiconPage | None:
        return self._pages.get("lexicon")

    @property
    def settings_page(self) -> SettingsPage | None:
        return self._pages.get("settings")

    # ------------------------------------------------------------ durum
    def set_licensed(self, licensed: bool) -> None:
        self._licensed = licensed
        for name, btn in self.nav_buttons.items():
            btn.setEnabled(licensed or name in OPEN_WITHOUT_LICENSE)
        if not licensed and self.current_page_name() not in OPEN_WITHOUT_LICENSE:
            self.show_page("license")
        page = self._pages.get("license")
        if page is not None:
            page.refresh()

    def set_state(self, state: str) -> None:
        self._state = state
        text, kind = STATE_BADGE.get(state, STATE_BADGE["idle"])
        self.state_badge.set_state(text, kind)
        if self.dictate_page is not None:
            self.dictate_page.set_listening(state == "listening")

    def set_model_name(self, name: str) -> None:
        self.model_label.setText(name)

    def set_hotkey_label(self, label: str) -> None:
        self._hotkey_label = label
        if self.dictate_page is not None:
            self.dictate_page.hotkey_label = label
            self.dictate_page.set_listening(self._state == "listening")

    def wants_dictation(self) -> bool:
        """Dikte çıktısı editöre mi gitmeli: pencere etkin ve Dikte sayfası açık; aksi hâlde metin imlece gider."""
        page = self.dictate_page
        return (page is not None and self.isVisible() and self.isActiveWindow()
                and self.stack.currentWidget() is page)

    # ------------------------------------------------------------ bildirimler
    def dictionary_changed(self) -> None:
        """Dikte ekranından sözlüğe söyleniş eklendi: açık tablo tazelenir, sözlük yeniden yüklenir."""
        if self.lexicon_page is not None:
            self.lexicon_page.reload_from_disk()
        if self._on_dictionary_changed:
            self._on_dictionary_changed()

    def _lexicon_saved(self) -> None:
        if self._on_dictionary_changed:
            self._on_dictionary_changed()

    def _settings_saved(self, reload_model: bool) -> None:
        if self._on_settings_changed:
            self._on_settings_changed(reload_model)

    def _license_activated(self) -> None:
        if self._on_license_changed:
            self._on_license_changed()

    def confirm_quit(self) -> bool:
        """Sözlük anında kaydedilir; yalnız çakışma yüzünden yazılamayan değişiklik varsa sorar."""
        page = self.lexicon_page
        if page is None or not page.editor.is_dirty():
            return True
        answer = QMessageBox.question(self, "Sözlük", "Aynı söyleniş birden çok terime bağlı olduğu için sözlükteki son "
                                      "değişiklikler kaydedilemedi. Bu değişiklikler atılsın mı?",
                                      QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        return answer == QMessageBox.Discard

    # ------------------------------------------------------------ pencere boyutu
    def _restore_geometry(self) -> None:
        raw = self.cfg.extra.get("window_geometry")
        if raw and not self.restoreGeometry(QByteArray.fromBase64(str(raw).encode("utf-8"))):
            log.info("Kayıtlı pencere boyutu okunamadı; varsayılan kullanılıyor")

    def save_window_state(self) -> None:
        self.cfg.extra["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.cfg.save()

    def closeEvent(self, event) -> None:
        """Kapatınca uygulama tepside çalışmaya devam eder."""
        self.save_window_state()
        super().closeEvent(event)
