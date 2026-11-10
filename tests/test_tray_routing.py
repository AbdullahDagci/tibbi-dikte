"""Tepsi uygulaması ile ana pencere arasındaki bağlantı: dikte çıktısının yönü, lisans kilidi, durum ve kapanış."""
import os
import subprocess
import sys
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import config as cfgmod, tray as traymod  # noqa: E402
from app.typer import type_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tray(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(traymod, "USER_LEXICON", tmp_path / "t.txt")
    monkeypatch.setattr(traymod, "USER_CORRECTIONS", tmp_path / "d.tsv")
    monkeypatch.setattr(traymod, "ensure_user_files", lambda: None)
    app = traymod.TrayApp(qapp)
    app.licensed = True
    yield app
    if app.main is not None and app.main.lexicon_page is not None:
        app.main.lexicon_page.editor.mark_clean()
    app.quit()
    app.dispose()


def test_output_goes_to_cursor_while_window_was_never_opened(tray):
    tray._route_output()
    assert tray.dictation.typer is type_text


def test_output_goes_to_editor_when_dictate_page_is_active(tray, monkeypatch):
    tray.open_page("dictate")
    monkeypatch.setattr(tray.main, "isActiveWindow", lambda: True)
    tray._route_output()
    assert tray.dictation.typer == tray.main.dictate_page.sink.type
    assert tray.dictation.on_scores == tray.main.dictate_page.sink.show_scores


def test_output_goes_to_cursor_when_other_page_is_open(tray, monkeypatch):
    tray.open_page("lexicon")
    monkeypatch.setattr(tray.main, "isActiveWindow", lambda: True)
    tray._route_output()
    assert tray.dictation.typer is type_text and tray.dictation.on_scores is None


def test_tray_menu_opens_requested_pages(tray):
    labels = [a.text() for a in tray._actions]
    assert labels == ["Dikteyi başlat", "Uygulamayı aç", "Sözlük", "Test ve doğruluk", "Ayarlar", "Çıkış"]  # Veri toplama gizli
    next(a for a in tray._actions if a.text() == "Sözlük").trigger()
    assert tray.main.current_page_name() == "lexicon" and tray.main.isVisible()


def test_unlicensed_toggle_opens_license_page(tray):
    tray.licensed = False
    tray._toggle()
    assert tray.main.current_page_name() == "license"


def test_state_change_reaches_window(tray):
    tray.open_page("dictate")
    tray._on_state("listening")
    assert tray.main.state_badge.text() == "Dinliyor"
    assert tray.main.dictate_page.btn.text() == "Dikteyi durdur"


def test_settings_change_updates_hotkey_label(tray):
    tray.open_page("dictate")
    tray.cfg.hotkey = "<ctrl>+<shift>+d"
    tray._on_settings_changed(False)
    assert "D" in tray.main.dictate_page.status.text() and "Shift" in tray.main.dictate_page.status.text()


def test_quit_hides_window_and_dispose_removes_it(tray):
    tray.open_page("dictate")
    win = tray.main
    tray.quit()
    assert tray.main is win and not win.isVisible()      # açık iletişim kutusu varken silinmez
    tray.dispose()
    assert tray.main is None


def test_cancelled_quit_keeps_app_running(tray, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.user_dict import Entry
    quits = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Cancel))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(tray.app, "quit", lambda: quits.append(True))
    tray.open_page("lexicon")
    tray.main.lexicon_page.editor.add_entry(Entry("BT", ["bete"]))
    tray.main.lexicon_page.editor.add_entry(Entry("MR", ["bete"]))     # çakışma: yazılamadı
    tray.quit()
    assert not quits and tray.main.isVisible()


def _spy_reload(tray, monkeypatch):
    done, full = threading.Event(), []
    monkeypatch.setattr(tray.dictation, "reload_dictionary", done.set)
    monkeypatch.setattr(tray, "_load_async", lambda: full.append(True))
    return done, full


def test_dictionary_change_refreshes_without_reloading_model(tray, monkeypatch):
    done, full = _spy_reload(tray, monkeypatch)
    monkeypatch.setattr(tray.dictation, "needs_engine_reload_for_dictionary", lambda: False)
    tray._dictionary_changed()
    assert done.wait(5) and full == []


def test_dictionary_change_does_not_stop_running_dictation(tray, monkeypatch):
    done, full = _spy_reload(tray, monkeypatch)
    monkeypatch.setattr(tray.dictation, "needs_engine_reload_for_dictionary", lambda: False)
    tray.dictation._active.set()
    tray._dictionary_changed()
    tray.dictation._active.clear()
    assert done.wait(5) and full == []
    assert not getattr(tray, "_reload_pending", False)


def test_hotword_model_waits_for_dictation_to_finish(tray, monkeypatch):
    done, full = _spy_reload(tray, monkeypatch)
    monkeypatch.setattr(tray.dictation, "needs_engine_reload_for_dictionary", lambda: True)
    tray.dictation._active.set()
    tray._dictionary_changed()
    tray.dictation._active.clear()
    assert tray._reload_pending and full == []
    tray._reload_pending = False


def test_saving_dictionary_in_page_reaches_dictation(tray, monkeypatch):
    from app.user_dict import Entry
    done, full = _spy_reload(tray, monkeypatch)
    monkeypatch.setattr(tray.dictation, "needs_engine_reload_for_dictionary", lambda: False)
    tray.open_page("lexicon")
    tray.main.lexicon_page.editor.add_entry(Entry("ahmet", ["ömer"]))
    assert done.wait(5)


def test_maximized_window_stays_maximized_when_reopened_from_tray(tray):
    tray.open_page("dictate")
    tray.main.showMaximized()
    tray.main.showMinimized()
    tray.open_page("lexicon")
    assert tray.main.isMaximized() and not tray.main.isMinimized()


def test_quit_with_message_box_open_exits_cleanly(tmp_path):
    # Yığında oluşturulan QMessageBox'ın üst penceresi altından silinirse süreç çöküyordu (0xC0000374)
    script = tmp_path / "scenario.py"
    script.write_text('''
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
from app import tray as traymod
t = traymod.TrayApp(app)
t.licensed = True
t.open_page("settings")
QTimer.singleShot(0, lambda: QMessageBox.information(t.main, "Kontrol", "Açık uyarı"))
QTimer.singleShot(250, t.quit)
code = app.exec()
getattr(t, "dispose", lambda: None)()
sys.exit(code)
''', encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", APPDATA=str(tmp_path), PYTHONPATH=str(ROOT))
    done = subprocess.run([sys.executable, "-B", str(script)], env=env, cwd=str(tmp_path), timeout=60,
                          capture_output=True)
    assert done.returncode == 0, done.stderr[-400:]


# ------------------------------------------------------------ bip sesi
def test_beep_uses_configured_tones(tray, monkeypatch):
    played = []
    monkeypatch.setattr(traymod, "play_tone", lambda hz, ms: played.append((hz, ms)))
    tray.cfg.beep_enabled, tray.cfg.beep_start_hz, tray.cfg.beep_stop_hz, tray.cfg.beep_ms = True, 1100, 400, 120
    tray._beep(False)
    tray._beep(True)
    assert played == [(1100, 120), (400, 120)]


def test_beep_can_be_turned_off(tray, monkeypatch):
    played = []
    monkeypatch.setattr(traymod, "play_tone", lambda hz, ms: played.append((hz, ms)))
    tray.cfg.beep_enabled = False
    tray._beep(False)
    tray._beep(True)
    assert played == []


@pytest.mark.parametrize("hz,ms,expected", [
    (1000, 70, (1000, 70)),
    (5, 70, (37, 70)),            # Windows'un kabul ettiği aralığa çekilir: elle bozulan ayar çökme yapmaz
    (99999, 70, (32767, 70)),
    (1000, 0, (1000, 1)),
])
def test_beep_tone_stays_in_valid_range(hz, ms, expected):
    from app.audio import beep_tone
    from app.config import Config
    cfg = Config(beep_start_hz=hz, beep_ms=ms)
    assert beep_tone(cfg, stopping=False) == expected


def test_default_beep_keeps_previous_sound():
    from app.audio import beep_tone
    from app.config import Config
    assert beep_tone(Config(), stopping=False) == (990, 70)
    assert beep_tone(Config(), stopping=True) == (660, 70)


# ------------------------------------------------------------ uygulama açıkken lisans süresi
def test_license_is_rechecked_while_app_runs(tray):
    assert tray._license_timer.isActive() and tray._license_timer.interval() == 3_600_000


def test_expiry_while_running_locks_dictation_and_opens_license_page(tray, monkeypatch):
    stopped = []
    monkeypatch.setattr(tray.dictation, "stop_listening", lambda: stopped.append(True))
    monkeypatch.setattr(traymod.lic, "current", lambda: traymod.lic.LicenseInfo(False, "Lisans süresi doldu."))
    tray._recheck_license()
    assert tray.licensed is False and stopped == [True]
    assert tray.main.current_page_name() == "license"


def test_valid_license_recheck_keeps_working_and_updates_days_left(tray, monkeypatch):
    monkeypatch.setattr(traymod.lic, "current",
                        lambda: traymod.lic.LicenseInfo(True, "Lisans geçerli", days_left=5))
    tray._recheck_license()
    assert tray.licensed is True and "5 gün" in tray.tray.toolTip()


def test_customer_trial_key_shows_days_left_notice(tray, monkeypatch):
    shown = []
    monkeypatch.setattr(tray.tray, "showMessage", lambda *a: shown.append(a))
    monkeypatch.setattr(traymod.lic, "current",
                        lambda: traymod.lic.LicenseInfo(True, "Lisans geçerli (10 gün kaldı)", days_left=10))
    monkeypatch.setattr(tray, "_load_async", lambda: None)
    tray._check_license()
    assert shown and "10 gün" in shown[0][1]


def test_long_license_does_not_nag_on_every_start(tray, monkeypatch):
    shown = []
    monkeypatch.setattr(tray.tray, "showMessage", lambda *a: shown.append(a))
    monkeypatch.setattr(traymod.lic, "current",
                        lambda: traymod.lic.LicenseInfo(True, "Lisans geçerli", days_left=200))
    monkeypatch.setattr(tray, "_load_async", lambda: None)
    tray._check_license()
    assert shown == []
