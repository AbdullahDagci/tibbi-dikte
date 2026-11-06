"""Ana pencere: sol menü, sayfa geçişi, büyütme, lisans kilidi, dikte yönlendirme ve sayfa yaşam döngüsü."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QShortcut  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox  # noqa: E402

from app import config as cfgmod, user_dict  # noqa: E402
from app.collect import CollectPage  # noqa: E402
from app.config import Config  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from app.settings_window import AboutPage, LicensePage, SettingsPage  # noqa: E402
from app.testbench import TestPage  # noqa: E402
from app.user_dict import Entry  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _dispose(widget):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class FakeStream:
    def __init__(self):
        self.stopped = self.closed = False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def private_data_dirs(tmp_path, monkeypatch):
    # Testler kullanıcının gerçek ayar ve veri toplama dosyalarına dokunmasın
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr("app.collect.OUT_ROOT", tmp_path / "veri_toplama")


@pytest.fixture
def make_window(qapp, tmp_path, monkeypatch):
    lex, corr = tmp_path / "t.txt", tmp_path / "d.tsv"
    user_dict.save([Entry("BT", ["bete"])], lex, corr)
    made = []

    def make(cfg=None, licensed=True, **kw):
        win = MainWindow(cfg or Config(), get_pipeline=lambda: (None, None, False), term_files=[lex],
                         lexicon_path=lex, corrections_path=corr, hotkey_label="Ctrl+Alt+Space", **kw)
        win.set_licensed(licensed)
        made.append(win)
        return win
    yield make
    for win in made:
        _dispose(win)


# ------------------------------------------------------------ pencere
def test_window_can_be_maximized_and_resized(make_window):
    win = make_window()
    assert win.windowFlags() & Qt.WindowMaximizeButtonHint
    assert win.minimumWidth() < 1100 and win.maximumWidth() > 4000
    win.resize(1600, 950)
    win.show()
    assert win.width() == 1600 and win.height() == 950


def test_size_is_saved_on_close_and_given_back_on_next_opening(make_window, monkeypatch):
    # Geri yüklemeyi ekrana sığdıran Qt'dir; sahte ekran küçük olduğu için aktarılan veri denetlenir
    cfg = Config()
    first = make_window(cfg)
    first.resize(1333, 777)
    first.show()
    expected = bytes(first.saveGeometry())
    first.close()
    assert Config.load().extra.get("window_geometry") == cfg.extra["window_geometry"]
    restored = []
    monkeypatch.setattr(MainWindow, "restoreGeometry", lambda self, data: restored.append(bytes(data)) or True)
    make_window(cfg)
    assert restored == [expected]


def test_broken_saved_size_is_ignored(make_window):
    cfg = Config()
    cfg.extra["window_geometry"] = "bu-geçerli-değil"
    assert make_window(cfg).width() >= 960


# ------------------------------------------------------------ gezinme
@pytest.mark.parametrize("name,title", [
    ("dictate", "Dikte"), ("test", "Test ve doğruluk"), ("collect", "Veri toplama"), ("lexicon", "Sözlük"),
    ("settings", "Ayarlar"), ("license", "Lisans"), ("about", "Hakkında"),
])
def test_menu_click_opens_page_and_updates_title(make_window, name, title):
    win = make_window()
    win.nav_buttons[name].click()
    assert win.current_page_name() == name
    assert win.title_label.text() == title
    assert win.nav_buttons[name].isChecked()
    assert sum(b.isChecked() for b in win.nav_buttons.values()) == 1
    assert not win.nav_buttons[name].icon().isNull()


def test_pages_are_created_once_and_keep_their_state(make_window):
    win = make_window()
    win.show_page("dictate")
    win.dictate_page.editor.setPlainText("rapor taslağı")
    win.show_page("lexicon")
    win.show_page("dictate")
    assert win.dictate_page.editor.toPlainText() == "rapor taslağı"


def test_unknown_page_goes_to_dictate(make_window):
    win = make_window()
    win.show_page("olmayan")
    assert win.current_page_name() == "dictate"


# ------------------------------------------------------------ lisans
def test_without_license_only_license_and_about_are_open(make_window):
    win = make_window(licensed=False)
    locked = [n for n, b in win.nav_buttons.items() if not b.isEnabled()]
    assert sorted(locked) == ["collect", "dictate", "lexicon", "settings", "test"]
    win.show_page("test")
    assert win.current_page_name() == "license"
    win.show_page("about")
    assert win.current_page_name() == "about"


def test_license_activation_unlocks_menu(make_window):
    win = make_window(licensed=False)
    win.set_licensed(True)
    assert all(b.isEnabled() for b in win.nav_buttons.values())
    win.show_page("test")
    assert win.current_page_name() == "test"


# ------------------------------------------------------------ dikte yönlendirme
def test_dictation_goes_to_editor_only_when_window_active_on_dictate_page(make_window, monkeypatch):
    win = make_window()
    monkeypatch.setattr(win, "isActiveWindow", lambda: True)
    assert not win.wants_dictation()            # pencere görünmüyor
    win.show()
    win.show_page("lexicon")
    assert not win.wants_dictation()            # başka sayfa açık
    win.show_page("dictate")
    assert win.wants_dictation()
    monkeypatch.setattr(win, "isActiveWindow", lambda: False)
    assert not win.wants_dictation()            # başka uygulama önde: metin imlece gider


def test_state_updates_badge_and_editor_button(make_window):
    win = make_window()
    win.show_page("dictate")
    win.set_state("listening")
    assert win.state_badge.text() == "Dinliyor" and win.state_badge.property("badge") == "danger"
    assert win.dictate_page.btn.property("variant") == "danger"
    win.set_state("idle")
    assert win.state_badge.text() == "Hazır" and win.state_badge.property("badge") == "success"
    assert win.dictate_page.btn.property("variant") == "primary"


def test_state_set_before_page_exists_is_applied_when_it_opens(make_window):
    win = make_window()
    win.set_state("listening")
    win.show_page("dictate")
    assert win.dictate_page.btn.property("variant") == "danger"


def test_hotkey_label_reaches_editor(make_window):
    win = make_window()
    win.show_page("dictate")
    win.set_hotkey_label("Ctrl+Shift+D")
    assert "Ctrl+Shift+D" in win.dictate_page.status.text()


# ------------------------------------------------------------ sinyaller
def test_dictionary_change_requests_only_dictionary_reload(make_window):
    dictionary, settings = [], []
    win = make_window(on_dictionary_changed=lambda: dictionary.append(True), on_settings_changed=settings.append)
    win.show_page("lexicon")
    win.lexicon_page.editor.add_entry(Entry("MR", ["em ar"]))
    assert dictionary == [True]
    assert settings == []     # modeli baştan yüklemez, dikteyi kesmez


def test_dictionary_change_from_editor_refreshes_table_and_notifies(make_window):
    fired = []
    win = make_window(on_dictionary_changed=lambda: fired.append(True))
    win.show_page("lexicon")
    user_dict.add_variant(win.lexicon_page.lexicon_path, win.lexicon_page.corrections_path, "pete", "BT")
    win.dictionary_changed()
    assert fired == [True]
    assert win.lexicon_page.editor.entries() == [Entry("BT", ["bete", "pete"])]


def test_settings_save_notifies_and_about_follows(make_window):
    fired = []
    win = make_window(on_settings_changed=fired.append)
    win.show_page("settings")
    win.settings_page.threads.setValue(win.settings_page.threads.value() % 8 + 1)
    assert win.settings_page.save() is True
    assert fired == [True]
    win.settings_page.cb_space.toggle()
    win.settings_page.save()
    assert fired == [True, False]            # model/sözlüğü etkilemeyen ayar yeniden yükleme istemez


# ------------------------------------------------------------ sayfalar
def test_settings_page_writes_config(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", tmp_path / "config.json")
    cfg = Config()
    page = SettingsPage(cfg)
    page.cb_live.setChecked(not cfg.live_typing)
    expected = page.cb_live.isChecked()
    page.btn_save.click()
    assert Config.load().live_typing == expected
    _dispose(page)


def test_invalid_hotkey_is_rejected(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QKeySequence
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", tmp_path / "config.json")
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    monkeypatch.setattr("app.settings_window.is_valid", lambda hk: False)
    cfg = Config()
    page = SettingsPage(cfg)
    page.hotkey_edit.setKeySequence(QKeySequence("Ctrl+K"))
    assert page.save() is False and warned
    assert not (tmp_path / "config.json").exists()
    _dispose(page)


def test_long_model_names_do_not_widen_settings_page(qapp):
    page = SettingsPage(Config())
    page.model_box.addItem("Çok uzun bir model adı " * 12, "x")
    page.mic_box.addItem("Çok uzun bir mikrofon adı " * 12, 99)
    assert page.minimumSizeHint().width() < 900
    _dispose(page)


def test_license_page_shows_state_and_rejects_bad_key(qapp, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    page = LicensePage()
    assert page.status_badge.text() in ("Etkin", "Etkin değil")
    assert page.mcode.text()
    page.key_edit.setPlainText("YANLIS-ANAHTAR")
    monkeypatch.setattr("app.settings_window.lic.activate", lambda key: type(
        "I", (), {"valid": False, "message": "Geçersiz anahtar"})())
    page.btn_activate.click()
    assert warned == ["Geçersiz anahtar"]
    _dispose(page)


def test_about_page_shows_only_developers_and_rights(qapp):
    from PySide6.QtWidgets import QLabel, QPushButton
    page = AboutPage()
    texts = [label.text() for label in page.findChildren(QLabel) if label.text()]
    assert texts == ["Tıbbi Dikte", "Abdullah ve İbrahim Dağcı tarafından geliştirilmiştir.", "Tüm hakları saklıdır."]
    assert page.findChildren(QPushButton) == []
    _dispose(page)


def test_about_page_shows_logo(qapp):
    from PySide6.QtWidgets import QLabel
    page = AboutPage()
    assert any(not label.pixmap().isNull() for label in page.findChildren(QLabel))
    _dispose(page)


def test_window_uses_application_logo(make_window):
    from PySide6.QtWidgets import QLabel
    win = make_window()
    assert not win.windowIcon().isNull()
    brand = win.findChild(QLabel, "brandLogo")
    assert brand is not None and not brand.pixmap().isNull()


# ------------------------------------------------------------ kayıtlar sayfadan çıkınca durur
def test_test_page_stops_recording_when_left(make_window, monkeypatch):
    win = make_window()
    win.show()
    win.show_page("test")
    page = win.test_page
    stream = FakeStream()
    page._rec_stream = stream
    page._rec_chunks = []
    from PySide6.QtCore import QTimer
    page._rec_timer = QTimer(page, interval=100)
    win.show_page("lexicon")
    assert page._rec_stream is None and stream.stopped and stream.closed


def test_collect_page_stops_recording_when_window_closes(make_window):
    win = make_window()
    win.show()
    win.show_page("collect")
    page = win.collect_page
    stream = FakeStream()
    page._stream = stream
    win.close()
    assert page._stream is None and stream.stopped and stream.closed


def test_minimizing_does_not_stop_recording(make_window):
    from PySide6.QtGui import QHideEvent
    win = make_window()
    win.show()
    win.show_page("collect")
    page = win.collect_page
    stream = FakeStream()
    page._stream = stream
    event = QHideEvent()
    event.spontaneous = lambda: True
    page.hideEvent(event)
    assert page._stream is stream
    page._stream = None


def test_collect_shortcuts_only_work_inside_their_page(qapp):
    page = CollectPage(lambda: (None, None, False))
    shortcuts = page.findChildren(QShortcut)
    assert len(shortcuts) >= 3
    assert all(s.context() == Qt.WidgetWithChildrenShortcut for s in shortcuts)
    _dispose(page)


def test_test_page_error_is_shown_without_model(qapp, monkeypatch):
    import numpy as np
    page = TestPage(lambda: (None, None, False), [])
    page.audio, page.sr = np.zeros(1600, np.float32), 16000
    page._run()
    assert "Model henüz yüklenmedi" in page.diff.toPlainText()
    _dispose(page)


def _recording_collect_page(win):
    from app import theme
    from app.ui import widgets
    win.show()
    win.show_page("collect")
    page = win.collect_page
    page.speaker.setText("dr01")
    page.consent.setChecked(True)
    stream = FakeStream()
    page._stream = stream
    page._timer.start()
    page.btn_rec.setText("Durdur")
    widgets.set_variant(page.btn_rec, "danger", icon="player-stop")
    page._set_status("Kaydediliyor…", theme.BAD)
    return page, stream


def test_leaving_collect_mid_recording_leaves_a_ready_button(make_window):
    win = make_window()
    page, stream = _recording_collect_page(win)
    win.show_page("lexicon")
    win.show_page("collect")
    assert stream.stopped and page._stream is None and not page._timer.isActive()
    assert page.btn_rec.text() == "Kaydı başlat" and page.btn_rec.property("variant") == "primary"
    assert "Kaydediliyor" not in page.status.text() and page.level.value() == 0


def test_leaving_collect_requires_consent_again_and_drops_unsaved_take(make_window):
    import numpy as np
    win = make_window()
    win.show()
    win.show_page("collect")
    page = win.collect_page
    page.consent.setChecked(True)
    page.pcm = np.zeros(16000, np.float32)
    win.show_page("lexicon")
    assert not page.consent.isChecked()
    assert page.pcm is None and not page.btn_save.isEnabled()  # rızasız kayıt "evet" diye yazılamasın


def test_unsaved_settings_are_discarded_when_page_is_left(make_window):
    cfg = Config()
    win = make_window(cfg)
    win.show()
    win.show_page("settings")
    page = win.settings_page
    page.cb_live.setChecked(not cfg.live_typing)
    page.threads.setValue(cfg.num_threads % 8 + 1)
    win.show_page("about")
    win.show_page("settings")
    assert page.cb_live.isChecked() == cfg.live_typing and page.threads.value() == cfg.num_threads


def test_saved_settings_stay_when_page_is_reopened(make_window):
    cfg = Config()
    win = make_window(cfg)
    win.show()
    win.show_page("settings")
    page = win.settings_page
    wanted = not cfg.live_typing
    page.cb_live.setChecked(wanted)
    page.save()
    win.show_page("about")
    win.show_page("settings")
    assert page.cb_live.isChecked() is wanted


def test_restoring_from_minimize_keeps_unsaved_settings(make_window):
    from PySide6.QtGui import QShowEvent
    cfg = Config()
    win = make_window(cfg)
    win.show()
    win.show_page("settings")
    page = win.settings_page
    wanted = not cfg.live_typing
    page.cb_live.setChecked(wanted)
    event = QShowEvent()
    event.spontaneous = lambda: True
    page.showEvent(event)
    assert page.cb_live.isChecked() is wanted


def _conflicting_dictionary(win, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    win.show_page("lexicon")
    win.lexicon_page.editor.add_entry(Entry("MR", ["bete"]))     # "bete" zaten BT'ye bağlı: yazılamadı


@pytest.mark.parametrize("answer,expected", [(QMessageBox.Discard, True), (QMessageBox.Cancel, False)])
def test_quit_asks_when_dictionary_could_not_be_written(make_window, monkeypatch, answer, expected):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a[2]) or answer))
    win = make_window()
    _conflicting_dictionary(win, monkeypatch)
    assert win.confirm_quit() is expected
    assert asked
    win.lexicon_page.editor.mark_clean()


def test_quit_does_not_ask_when_dictionary_is_saved(make_window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: pytest.fail("sormamalıydı")))
    win = make_window()
    assert win.confirm_quit() is True
    win.show_page("lexicon")
    win.lexicon_page.editor.add_entry(Entry("MR", ["em ar"]))
    assert win.confirm_quit() is True


# ------------------------------------------------------------ odak ve güncel veri
def test_returning_to_collect_keeps_focus_in_text_box(make_window):
    from PySide6.QtGui import QShowEvent
    win = make_window()
    win.show()
    win.show_page("collect")
    page = win.collect_page
    page.mode.setCurrentIndex(1)
    page.free_text.setFocus()
    event = QShowEvent()
    event.spontaneous = lambda: True
    page.showEvent(event)
    assert win.focusWidget() is page.free_text
    page.showEvent(QShowEvent())
    assert win.focusWidget() is page.free_text


def test_clicking_current_menu_item_returns_focus_to_page(make_window):
    win = make_window()
    win.show()
    win.show_page("collect")
    button = win.nav_buttons["collect"]
    button.setFocus()
    button.click()
    assert win.focusWidget() is win.collect_page


def test_dictate_page_focus_goes_to_editor(make_window):
    win = make_window()
    win.show()
    win.nav_buttons["lexicon"].click()
    win.nav_buttons["dictate"].click()
    assert win.focusWidget() is win.dictate_page.editor


def test_new_terms_count_for_term_score_without_restart(qapp, tmp_path):
    import numpy as np
    terms = tmp_path / "terimler.txt"
    terms.write_text("protrüzyon\n", encoding="utf-8")
    page = TestPage(lambda: (None, None, False), [terms])
    assert "doppler" not in page.terms
    terms.write_text("protrüzyon\ndoppler\n", encoding="utf-8")
    page.audio, page.sr = np.zeros(1600, np.float32), 16000
    page._run()
    assert "doppler" in page.terms
    _dispose(page)


def test_settings_page_lists_models_added_after_first_open(make_window, tmp_path, monkeypatch):
    from app.engines.base import ModelInfo
    from app.settings_window import discover_models
    win = make_window()
    win.show()
    win.show_page("settings")
    page = win.settings_page
    extra = ModelInfo(dir=tmp_path / "yeni-model", spec={"name": "Yeni Model"})
    monkeypatch.setattr("app.settings_window.discover_models", lambda: [*discover_models(), extra])
    win.show_page("about")
    win.show_page("settings")
    assert page.model_box.findData(str(extra.dir)) >= 0


# ------------------------------------------------------------ bip sesi
def test_beep_settings_are_saved(make_window):
    cfg = Config()
    win = make_window(cfg)
    win.show()
    win.show_page("settings")
    page = win.settings_page
    page.beep_on.setChecked(False)
    page.beep_start_hz.setValue(1200)
    page.beep_stop_hz.setValue(500)
    page.beep_ms.setValue(150)
    assert page.save() is True
    saved = Config.load()
    assert (saved.beep_enabled, saved.beep_start_hz, saved.beep_stop_hz, saved.beep_ms) == (False, 1200, 500, 150)


def test_beep_controls_follow_switch(qapp):
    page = SettingsPage(Config())
    page.beep_on.setChecked(True)
    assert page.beep_start_hz.isEnabled() and page.beep_ms.isEnabled()
    page.beep_on.setChecked(False)
    assert not page.beep_start_hz.isEnabled() and not page.beep_stop_hz.isEnabled() and not page.beep_ms.isEnabled()
    _dispose(page)


def test_beep_change_does_not_request_model_reload(make_window):
    fired = []
    win = make_window(on_settings_changed=fired.append)
    win.show()
    win.show_page("settings")
    win.settings_page.beep_start_hz.setValue(1500)
    win.settings_page.save()
    assert fired == [False]


def test_listen_buttons_play_current_unsaved_values(qapp, monkeypatch):
    played = []
    monkeypatch.setattr("app.settings_window.play_tone", lambda hz, ms: played.append((hz, ms)))
    page = SettingsPage(Config())
    page.beep_start_hz.setValue(1234)
    page.beep_stop_hz.setValue(432)
    page.beep_ms.setValue(90)
    page.btn_beep_start.click()
    page.btn_beep_stop.click()
    assert played == [(1234, 90), (432, 90)]
    _dispose(page)


def test_settings_has_no_hotword_switch(qapp):
    page = SettingsPage(Config())
    assert "Terimleri modele öncelikli tanıt" not in [label.text() for label in page.findChildren(QLabel)]
    assert not hasattr(page, "cb_hot")
    _dispose(page)


def test_saving_settings_keeps_stored_hotword_value(qapp):
    cfg = Config(use_hotwords=False)
    page = SettingsPage(cfg)
    page.show()
    assert page.save()
    assert cfg.use_hotwords is False
    _dispose(page)
