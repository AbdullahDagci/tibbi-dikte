"""Sistem tepsisi uygulaması: durum ikonu, menü, kısayol ve dikte denetleyicisini bağlar."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .config import Config
from .collect import CollectWindow
from .dictation import Dictation
from .hotkey import GlobalHotkey, pynput_to_qt
from .licensing import license as lic
from .dictation import BUILTIN_LEXICON, RADIOLOGY_LEXICON, USER_CORRECTIONS, USER_LEXICON
from .editor import EditorPage
from .overlay import ListeningOverlay
from .ptt import PushToTalk
from .settings_window import TAB_LICENSE, SettingsWindow
from .testbench import TestWindow
from .typer import backspace, type_text

log = logging.getLogger(__name__)

STATE_STYLE = {
    "idle": ("#2f6fed", "Hazır"),
    "listening": ("#d92d20", "Dinliyor…"),
    "loading": ("#98a2b3", "Model yükleniyor…"),
    "error": ("#f79009", "Hata — ayrıntı için günlük dosyasına bakın"),
    "unlicensed": ("#667085", "Lisans gerekli"),
}


def make_icon(color: str) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 60, 60)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", 30, QFont.Bold)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "D")
    p.end()
    return QIcon(pm)


class _Bridge(QObject):
    """Arka plan iş parçacıklarından UI iş parçacığına güvenli geçiş."""
    state = Signal(str)
    toggle = Signal()
    level = Signal(float)
    ptt_start = Signal()
    ptt_stop = Signal()
    partial = Signal(str)
    text = Signal(str)


class TrayApp:
    def __init__(self, app: QApplication):
        self.app = app
        self.cfg = Config.load()
        self.bridge = _Bridge()
        self.bridge.state.connect(self._on_state)
        self.bridge.toggle.connect(self._toggle)
        self.icons = {k: make_icon(c) for k, (c, _) in STATE_STYLE.items()}
        self.licensed = False

        self.dictation = Dictation(self.cfg, on_state=self.bridge.state.emit, on_text=self.bridge.text.emit,
                                   on_level=self.bridge.level.emit, on_partial=self.bridge.partial.emit)
        self.overlay = ListeningOverlay(pynput_to_qt(self.cfg.hotkey))
        self.bridge.level.connect(self.overlay.set_level)
        self.bridge.partial.connect(self.overlay.set_partial)
        self.bridge.text.connect(self.overlay.add_text)
        self._test: TestWindow | None = None
        self.hotkey = GlobalHotkey(self.cfg.hotkey, self.bridge.toggle.emit)
        self.ptt = PushToTalk(self.cfg.ptt_key, self.bridge.ptt_start.emit, self.bridge.ptt_stop.emit)
        self.bridge.ptt_start.connect(self._ptt_start)
        self.bridge.ptt_stop.connect(self._ptt_stop)

        self.tray = QSystemTrayIcon(self.icons["loading"])
        menu = QMenu()
        self.act_toggle = QAction("Dikteyi başlat")
        self.act_toggle.triggered.connect(self._toggle)
        act_settings = QAction("Ayarlar…")
        act_settings.triggered.connect(lambda: self.settings().show_tab(0))
        act_test = QAction("Test ve doğruluk…")
        act_test.triggered.connect(self.show_test)
        act_collect = QAction("Veri toplama…")
        act_collect.triggered.connect(self.show_collect)
        act_quit = QAction("Çıkış")
        act_quit.triggered.connect(self.quit)
        for a in (self.act_toggle, act_test, act_collect, act_settings):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._actions = (self.act_toggle, act_test, act_collect, act_settings, act_quit)
        self._collect: CollectWindow | None = None
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_click)
        self.tray.show()
        self._settings: SettingsWindow | None = None

    # ------------------------------------------------ yaşam döngüsü
    def start(self) -> None:
        self._check_license()
        self.hotkey.start()
        self.ptt.start()

    def _check_license(self) -> None:
        info = lic.current()
        self.licensed = info.valid
        self.license_info = info
        if info.valid and info.demo:
            self.tray.showMessage("Tıbbi Dikte — deneme sürümü", info.message,
                                  QSystemTrayIcon.Warning if (info.days_left or 0) <= 3 else QSystemTrayIcon.Information)
        if not info.valid:
            self._on_state("unlicensed")
            self.tray.showMessage("Tıbbi Dikte", f"{info.message} Lütfen ürün anahtarınızı girin.",
                                  QSystemTrayIcon.Warning)
            self.settings().show_tab(TAB_LICENSE)
            return
        self._load_async()

    def _load_async(self) -> None:
        def run():
            try:
                self.dictation.load()
            except Exception:
                pass  # durum "error" olarak bildirildi
        threading.Thread(target=run, name="model-load", daemon=True).start()

    def quit(self) -> None:
        self.hotkey.stop()
        self.ptt.stop()
        self.dictation.stop_listening()
        self.tray.hide()
        self.app.quit()

    # ------------------------------------------------ olaylar
    def settings(self) -> SettingsWindow:
        if self._settings is None:
            self._settings = SettingsWindow(self.cfg)
            self._settings.settings_changed.connect(self._on_settings_changed)
            self._settings.license_changed.connect(self._check_license)
            self._settings.finished.connect(lambda _: setattr(self, "_settings", None))
            self._settings.setAttribute(Qt.WA_DeleteOnClose)
        return self._settings

    def show_test(self) -> None:
        if not self.licensed:
            self.settings().show_tab(TAB_LICENSE)
            return
        if self._test is None:
            d = self.dictation
            page = EditorPage(USER_LEXICON, USER_CORRECTIONS, pynput_to_qt(self.cfg.hotkey),
                              on_toggle=self._toggle, on_dictionary_changed=self._dictionary_changed)
            self._test = TestWindow(lambda: (d.engine, d.post, d.listening),
                                    [BUILTIN_LEXICON, RADIOLOGY_LEXICON, USER_LEXICON], editor_page=page)
            page.set_listening(d.listening)
            self._test.finished.connect(lambda _: setattr(self, "_test", None))
            self._test.setAttribute(Qt.WA_DeleteOnClose)
        self._test.show()
        self._test.raise_()
        self._test.activateWindow()

    def show_collect(self) -> None:
        if not self.licensed:
            self.settings().show_tab(TAB_LICENSE)
            return
        if self._collect is None:
            d = self.dictation
            self._collect = CollectWindow(lambda: (d.engine, d.post, d.listening))
            self._collect.finished.connect(lambda _: setattr(self, "_collect", None))
            self._collect.setAttribute(Qt.WA_DeleteOnClose)
        self._collect.show()
        self._collect.raise_()
        self._collect.activateWindow()

    def _on_settings_changed(self, reload_model: bool) -> None:
        self.hotkey.rebind(self.cfg.hotkey)
        self.ptt.rebind(self.cfg.ptt_key)
        self.overlay.hotkey_label = pynput_to_qt(self.cfg.hotkey)
        if reload_model and self.licensed:
            self._load_async()
        self._update_tooltip()

    def _on_tray_click(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._toggle()

    def _route_output(self) -> None:
        """Dikte başlarken: Test › Canlı dikte editörü etkinse metin doğrudan editöre, değilse imlece (SendInput)."""
        if self._test is not None and self._test.wants_dictation():
            sink = self._test.editor_page.sink
            self.dictation.typer, self.dictation.eraser = sink.type, sink.erase
            self.dictation.on_segment = sink.show_annotated
            self.dictation.on_scores = sink.show_scores
        else:
            self.dictation.typer, self.dictation.eraser = type_text, backspace
            self.dictation.on_segment = None
            self.dictation.on_scores = None

    def _dictionary_changed(self) -> None:
        """Editörden sözlüğe varyant eklendi: sözlük + hotword'ler yeniden yüklenir (dikte sürüyorsa bitince)."""
        if self.dictation.listening:
            self._reload_pending = True
        else:
            self._load_async()

    def _toggle(self) -> None:
        if not self.licensed:
            self.settings().show_tab(TAB_LICENSE)
            return
        if self.dictation.engine is None:
            return
        if not self.dictation.listening:
            self._route_output()
        self.overlay.ptt_mode = False
        if self.dictation.listening and self.cfg.show_overlay:
            self.overlay.finishing()  # son ses çözülüp yazılıyor
        self._beep(self.dictation.listening)
        # durdurma, son sesi çözüp yazdığı için UI'yı bloklamasın
        threading.Thread(target=self.dictation.toggle, daemon=True).start()

    def _ptt_start(self) -> None:
        if not self.licensed or self.dictation.engine is None or self.dictation.listening:
            return
        self._ptt_on = True
        self._route_output()
        self.overlay.ptt_mode = True
        self._beep(False)
        threading.Thread(target=self.dictation.start_listening, daemon=True).start()

    def _ptt_stop(self) -> None:
        if not getattr(self, "_ptt_on", False):
            return
        self._ptt_on = False
        if self.dictation.listening and self.cfg.show_overlay:
            self.overlay.finishing()
        self._beep(True)
        threading.Thread(target=self.dictation.stop_listening, daemon=True).start()

    @staticmethod
    def _beep(stopping: bool) -> None:
        try:
            import winsound
            threading.Thread(target=winsound.Beep, args=(660 if stopping else 990, 70), daemon=True).start()
        except Exception:
            pass

    def _on_state(self, state: str) -> None:
        prev = getattr(self, "state", None)
        if self.cfg.show_overlay:
            if state == "listening":
                self.overlay.start()
            elif state == "idle" and prev == "listening":
                self.overlay.done()
            elif state == "error" and prev == "listening":
                self.overlay.error("Dikte sırasında hata oluştu (günlük dosyasına bakın).")
        self.state = state
        if self._test is not None and self._test.editor_page is not None:
            self._test.editor_page.set_listening(state == "listening")
        if state == "idle" and getattr(self, "_reload_pending", False):
            self._reload_pending = False
            self._load_async()
        self.tray.setIcon(self.icons.get(state, self.icons["idle"]))
        self.act_toggle.setText("Dikteyi durdur" if state == "listening" else "Dikteyi başlat")
        self.act_toggle.setEnabled(state in ("idle", "listening"))
        self._update_tooltip()
        if state == "error":
            self.tray.showMessage("Tıbbi Dikte", STATE_STYLE["error"][1], QSystemTrayIcon.Critical)

    def _update_tooltip(self) -> None:
        label = STATE_STYLE.get(getattr(self, "state", "idle"), STATE_STYLE["idle"])[1]
        model = self.dictation.model.name if self.dictation.model else "-"
        li = getattr(self, "license_info", None)
        demo = f"\nDeneme: {li.days_left} gün kaldı" if li is not None and li.valid and li.demo else ""
        self.tray.setToolTip(f"Tıbbi Dikte — {label}\nKısayol: {pynput_to_qt(self.cfg.hotkey)}\nModel: {model}{demo}")
