"""Sistem tepsisi uygulaması: durum ikonu, menü, kısayol ve dikte denetleyicisini bağlar."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import theme
from .audio import MIC_WARNINGS, beep_tone, play_tone
from .config import Config
from .dictation import (BUILTIN_LEXICON, DICTATION_ERROR, RADIOLOGY_LEXICON, USER_CORRECTIONS, USER_LEXICON, Dictation,
                        ensure_user_files)
from .hotkey import GlobalHotkey, pynput_to_qt
from .licensing import license as lic
from .main_window import HIDDEN_PAGES, MainWindow
from .overlay import ListeningOverlay
from .ptt import PushToTalk
from .typer import backspace, type_text
from .ui.icons import icon as make_menu_icon
from .ui.icons import logo_icon

log = logging.getLogger(__name__)

STATE_STYLE = {
    "idle": (theme.PRIMARY, "Hazır"),
    "listening": (theme.DANGER, "Dinliyor…"),
    "loading": (theme.MUTED, "Model yükleniyor…"),
    "error": (theme.WARNING, "Hata — ayrıntı için günlük dosyasına bakın"),
    "unlicensed": (theme.MUTED, "Lisans gerekli"),
}


def make_icon(color: str) -> QIcon:
    """Tepsi simgesi: logonun zemini dikte durumunun rengini alır."""
    return logo_icon(color)


class _Bridge(QObject):
    """Arka plan iş parçacıklarından UI iş parçacığına güvenli geçiş."""
    state = Signal(str)
    toggle = Signal()
    level = Signal(float)
    ptt_start = Signal()
    ptt_stop = Signal()
    partial = Signal(str)
    text = Signal(str)
    mic_warning = Signal(str)


LICENSE_CHECK_MS = 3_600_000  # uygulama günlerce açık kalabilir: lisans saatte bir yeniden denetlenir
LICENSE_NOTICE_DAYS = 30      # süresi bundan azsa açılışta kalan gün bildirilir


class TrayApp:
    def __init__(self, app: QApplication):
        self.app = app
        self.cfg = Config.load()
        self.bridge = _Bridge()
        self.bridge.state.connect(self._on_state)
        self.bridge.toggle.connect(self._toggle)
        self.icons = {k: make_icon(c) for k, (c, _) in STATE_STYLE.items()}
        self.licensed = False
        self._license_timer = QTimer()
        self._license_timer.setInterval(LICENSE_CHECK_MS)
        self._license_timer.timeout.connect(self._recheck_license)
        self._license_timer.start()

        self.dictation = Dictation(self.cfg, on_state=self.bridge.state.emit, on_text=self.bridge.text.emit,
                                   on_level=self.bridge.level.emit, on_partial=self.bridge.partial.emit,
                                   on_warning=self.bridge.mic_warning.emit)
        self.overlay = ListeningOverlay(pynput_to_qt(self.cfg.hotkey))
        self.bridge.level.connect(self.overlay.set_level)
        self.bridge.mic_warning.connect(self._on_mic_warning)
        self.bridge.partial.connect(self.overlay.set_partial)
        self.bridge.text.connect(self.overlay.add_text)
        self.main: MainWindow | None = None
        self.hotkey = GlobalHotkey(self.cfg.hotkey, self.bridge.toggle.emit)
        self.ptt = PushToTalk(self.cfg.ptt_key, self.bridge.ptt_start.emit, self.bridge.ptt_stop.emit)
        self.bridge.ptt_start.connect(self._ptt_start)
        self.bridge.ptt_stop.connect(self._ptt_stop)

        self.tray = QSystemTrayIcon(self.icons["loading"])
        menu = QMenu()
        self.act_toggle = QAction("Dikteyi başlat")
        self.act_toggle.triggered.connect(self._toggle)
        self.act_toggle.setIcon(make_menu_icon("microphone", theme.TEXT))
        pages = (("dictate", "Uygulamayı aç", "logo"), ("lexicon", "Sözlük", "book-2"),
                 ("test", "Test ve doğruluk", "flask"), ("collect", "Veri toplama", "database"),
                 ("settings", "Ayarlar", "settings"))
        page_actions = []
        for name, title, icon_name in pages:
            if name in HIDDEN_PAGES:
                continue
            action = QAction(make_menu_icon(icon_name, theme.TEXT), title)
            action.triggered.connect(lambda _checked=False, page=name: self.open_page(page))
            page_actions.append(action)
        act_quit = QAction(make_menu_icon("x", theme.DANGER), "Çıkış")
        act_quit.triggered.connect(self.quit)
        menu.addAction(self.act_toggle)
        menu.addSeparator()
        for action in page_actions:
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._actions = (self.act_toggle, *page_actions, act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_click)
        self.tray.show()

    # ------------------------------------------------ yaşam döngüsü
    def start(self) -> None:
        self._check_license()
        self.hotkey.start()
        self.ptt.start()

    def _check_license(self) -> None:
        info = lic.current()
        self.licensed = info.valid
        self.license_info = info
        if info.valid and info.days_left is not None and (info.demo or info.days_left <= LICENSE_NOTICE_DAYS):
            self.tray.showMessage("Tıbbi Dikte — deneme sürümü" if info.demo else "Tıbbi Dikte — lisans süresi", info.message,
                                  QSystemTrayIcon.Warning if info.days_left <= 3 else QSystemTrayIcon.Information)
        if not info.valid:
            self._require_license(info)
            return
        self._sync_license()
        self._load_async()

    def _load_async(self) -> None:
        def run():
            try:
                self.dictation.load()
            except Exception:
                pass  # durum "error" olarak bildirildi
        threading.Thread(target=run, name="model-load", daemon=True).start()

    def quit(self) -> None:
        if self.main is not None and not self.main.confirm_quit():
            return
        self.hotkey.stop()
        self.ptt.stop()
        self.dictation.stop_listening()
        self.tray.hide()
        if self.main is not None:
            self.main.close()
        self.app.quit()

    def _require_license(self, info) -> None:
        self._on_state("unlicensed")
        self.tray.showMessage("Tıbbi Dikte", f"{info.message} Lütfen ürün anahtarınızı girin.", QSystemTrayIcon.Warning)
        self._sync_license()
        self.open_page("license")

    def _recheck_license(self) -> None:
        """Süre uygulama açıkken dolarsa dikte durur ve lisans sayfası açılır."""
        info = lic.current()
        self.license_info = info
        if info.valid or not self.licensed:
            self._update_tooltip()
            return
        self.dictation.stop_listening()
        self.licensed = False
        self._require_license(info)

    def dispose(self) -> None:
        """Olay döngüsü bittikten sonra çağrılır: açık iletişim kutusunun penceresi altından silinmez."""
        self._license_timer.stop()
        if self.main is not None:
            self.main.deleteLater()
            self.main = None
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    # ------------------------------------------------ olaylar
    def main_window(self) -> MainWindow:
        if self.main is None:
            ensure_user_files()
            d = self.dictation
            self.main = MainWindow(self.cfg, lambda: (d.engine, d.post, d.listening),
                                   [BUILTIN_LEXICON, RADIOLOGY_LEXICON, USER_LEXICON], USER_LEXICON, USER_CORRECTIONS,
                                   pynput_to_qt(self.cfg.hotkey), on_toggle=self._toggle,
                                   on_dictionary_changed=self._dictionary_changed,
                                   on_settings_changed=self._on_settings_changed,
                                   on_license_changed=self._check_license)
            self.main.set_licensed(self.licensed)
            self.main.set_state(getattr(self, "state", "idle"))
            self._update_tooltip()
        return self.main

    def open_page(self, name: str) -> None:
        win = self.main_window()
        win.show_page(name)
        if win.isMinimized():  # büyütülmüş pencere büyütülmüş olarak geri gelir
            win.setWindowState(win.windowState() & ~Qt.WindowMinimized)
        win.show()
        win.raise_()
        win.activateWindow()

    def _sync_license(self) -> None:
        if self.main is not None:
            self.main.set_licensed(self.licensed)

    def _on_settings_changed(self, reload_model: bool) -> None:
        self.hotkey.rebind(self.cfg.hotkey)
        self.ptt.rebind(self.cfg.ptt_key)
        self.overlay.hotkey_label = pynput_to_qt(self.cfg.hotkey)
        if self.main is not None:
            self.main.set_hotkey_label(pynput_to_qt(self.cfg.hotkey))
        if reload_model and self.licensed:
            self._load_async()
        self._update_tooltip()

    def _on_tray_click(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._toggle()

    def _route_output(self) -> None:
        """Dikte başlarken: Dikte sayfası etkinse metin doğrudan editöre, değilse imlece (SendInput)."""
        if self.main is not None and self.main.wants_dictation():
            sink = self.main.dictate_page.sink
            self.dictation.typer, self.dictation.eraser = sink.type, sink.erase
            self.dictation.on_segment = sink.show_annotated
            self.dictation.on_scores = sink.show_scores
        else:
            self.dictation.typer, self.dictation.eraser = type_text, backspace
            self.dictation.on_segment = None
            self.dictation.on_scores = None

    def _dictionary_changed(self) -> None:
        """Sözlük değişti: anında geçerli olur, dikte sürüyorsa kesilmez. Terimler modele hotword olarak veriliyorsa
        motor da yeniden kurulmalıdır; bu dikteyi durduracağı için dikte bitince yapılır."""
        if not self.dictation.needs_engine_reload_for_dictionary():
            threading.Thread(target=self.dictation.reload_dictionary, name="dictionary-reload", daemon=True).start()
        elif self.dictation.listening:
            self._reload_pending = True
        else:
            self._load_async()

    def _toggle(self) -> None:
        if not self.licensed:
            self.open_page("license")
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

    def _beep(self, stopping: bool) -> None:
        tone = beep_tone(self.cfg, stopping)
        if tone is not None:
            play_tone(*tone)

    def _on_state(self, state: str) -> None:
        prev = getattr(self, "state", None)
        if self.cfg.show_overlay:
            if state == "listening":
                self.overlay.start()
            elif state == "idle" and prev == "listening":
                self.overlay.done()
            elif state == "error" and prev == "listening":
                self.overlay.error(self.dictation.last_error or DICTATION_ERROR)
        self.state = state
        if self.main is not None:
            self.main.set_state(state)
        if state == "idle" and getattr(self, "_reload_pending", False):
            self._reload_pending = False
            self._load_async()
        self.tray.setIcon(self.icons.get(state, self.icons["idle"]))
        self.act_toggle.setText("Dikteyi durdur" if state == "listening" else "Dikteyi başlat")
        self.act_toggle.setEnabled(state in ("idle", "listening"))
        self._update_tooltip()
        if state == "error":
            self.tray.showMessage("Tıbbi Dikte", self.dictation.last_error or STATE_STYLE["error"][1],
                                  QSystemTrayIcon.Critical)

    def _on_mic_warning(self, key: str) -> None:
        """Dikte sırasında mikrofon sorunu: göstergede; gösterge kapalıysa tepsi bildirimi."""
        if self.cfg.show_overlay:
            self.overlay.set_warning(key)
        elif key in MIC_WARNINGS:
            title, detail = MIC_WARNINGS[key]
            self.tray.showMessage(f"Tıbbi Dikte — {title}", detail, QSystemTrayIcon.Warning)

    def _update_tooltip(self) -> None:
        label = STATE_STYLE.get(getattr(self, "state", "idle"), STATE_STYLE["idle"])[1]
        model = self.dictation.model.name if self.dictation.model else "-"
        if self.main is not None:
            self.main.set_model_name("" if model == "-" else model)
        li = getattr(self, "license_info", None)
        demo = ""
        if li is not None and li.valid and li.days_left is not None:
            demo = f"\n{'Deneme' if li.demo else 'Lisans'}: {li.days_left} gün kaldı"
        self.tray.setToolTip(f"Tıbbi Dikte — {label}\nKısayol: {pynput_to_qt(self.cfg.hotkey)}\nModel: {model}{demo}")
