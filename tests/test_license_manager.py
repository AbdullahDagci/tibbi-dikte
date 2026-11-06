"""Lisans Yöneticisi ekranı: liste, kalan gün, yeni anahtar, yenileme ve kopyalama."""
import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from PySide6.QtCore import QCoreApplication, QDate, QEvent  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton  # noqa: E402

from app import theme  # noqa: E402
from app.licensing import license as lic  # noqa: E402
from app.ui.data_table import Column, DataTable  # noqa: E402
from tools import license_manager as manager  # noqa: E402
from tools import license_store as store  # noqa: E402

PRIV = Ed25519PrivateKey.generate()
PUB = PRIV.public_key()
TODAY = dt.date(2026, 11, 7)
MACHINE = bytes(range(10))
CODE = lic._group(lic.base64.b32encode(MACHINE).decode().rstrip("="))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def paths(tmp_path):
    private = tmp_path / "private.pem"
    private.write_bytes(PRIV.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return private, tmp_path / "issued.csv"


@pytest.fixture
def warnings(monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    return shown


def dispose(widget):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def window(qapp, paths):
    made = []

    def make():
        win = manager.LicenseManagerWindow(private_key=paths[0], log=paths[1], today=lambda: TODAY)
        made.append(win)
        return win
    yield make
    for win in made:
        dispose(win)


def add(paths, customer, expires, code=CODE, today=TODAY):
    return store.issue(customer=customer, machine_code=code, expires=expires, today=today, private_key=paths[0], log=paths[1])


def other_code(byte):
    return lic._group(lic.base64.b32encode(bytes([byte]) * 10).decode().rstrip("="))


def cells(win, row=0):
    t = win.table.table
    return [t.item(row, c).text() for c in range(t.columnCount() - 1)]


def dialog(paths, **kw):
    return manager.LicenseDialog(private_key=paths[0], log=paths[1], today=TODAY, **kw)


# ------------------------------------------------------------ liste
def test_empty_list_opens_without_a_key_file(window):
    win = window()
    assert win.table.filtered_rows() == [] and win.btn_new.isEnabled()
    assert win.windowTitle() == "Lisans Yöneticisi"
    assert win.tile_active.value.text() == "0"


def test_table_shows_customer_dates_days_left_and_status(window, paths):
    add(paths, "X Hastanesi", dt.date(2026, 11, 21))
    win = window()
    assert cells(win) == ["X Hastanesi", CODE, "07.11.2026", "21.11.2026", "14 gün", store.EXPIRING, "—"]


@pytest.mark.parametrize("expires,text", [(dt.date(2026, 11, 7), "Bugün bitiyor"), (None, "—")])
def test_days_left_text_for_special_cases(window, paths, expires, text):
    add(paths, "X", expires, today=dt.date(2026, 11, 1))
    assert cells(window())[4] == text


def test_expired_row_says_how_long_ago(window, paths):
    add(paths, "X", dt.date(2026, 11, 4), today=dt.date(2026, 11, 1))
    row = cells(window())
    assert row[4] == "3 gün önce doldu" and row[5] == store.EXPIRED


def test_demo_row_says_it_works_everywhere(window, paths):
    store.issue(customer="Sunum", machine_code=None, demo=True, expires=dt.date(2026, 11, 21), today=TODAY,
                private_key=paths[0], log=paths[1])
    assert cells(window())[1] == "Her bilgisayar"


def test_status_has_color(window, paths):
    add(paths, "X", dt.date(2026, 11, 21))
    win = window()
    assert win.table.table.item(0, 5).foreground().color() == QColor(theme.WARNING_TEXT)


def test_summary_tiles(window, paths):
    add(paths, "A", dt.date(2027, 6, 1), other_code(1))
    add(paths, "B", dt.date(2026, 11, 20), other_code(2))
    add(paths, "C", dt.date(2026, 11, 2), other_code(3), today=dt.date(2026, 11, 1))
    win = window()
    assert (win.tile_active.value.text(), win.tile_expiring.value.text(), win.tile_expired.value.text()) == ("2", "1", "1")


def test_search_finds_customer_and_status(window, paths):
    add(paths, "İzmir Kliniği", dt.date(2027, 6, 1), other_code(1))
    add(paths, "Ankara", dt.date(2026, 11, 20), other_code(2))
    win = window()
    win.table.search.setText("izmir")
    assert [r.record.customer for r in win.table.filtered_rows()] == ["İzmir Kliniği"]
    win.table.search.setText(store.EXPIRING.lower())
    assert [r.record.customer for r in win.table.filtered_rows()] == ["Ankara"]


def test_days_left_column_sorts_by_number_not_text(window, paths):
    add(paths, "A", dt.date(2026, 11, 16), other_code(1))   # 9 gün
    add(paths, "B", dt.date(2026, 12, 7), other_code(2))    # 30 gün
    add(paths, "C", dt.date(2026, 11, 8), other_code(3))    # 1 gün
    win = window()
    win.table._header_clicked(4)
    assert [r.record.customer for r in win.table.filtered_rows()] == ["C", "A", "B"]


def test_key_never_appears_in_the_table(window, paths):
    rec = add(paths, "X", dt.date(2026, 11, 21))
    assert rec.key not in cells(window())


def test_copy_action_puts_key_on_clipboard(window, paths):
    rec = add(paths, "X", dt.date(2026, 11, 21))
    win = window()
    win.copy_key(win.table.visible_rows()[0])
    assert QGuiApplication.clipboard().text() == rec.key


def test_list_is_reloaded_when_window_gets_focus_again(window, paths, monkeypatch):
    win = window()
    add(paths, "Komut satırından", dt.date(2026, 11, 21))
    monkeypatch.setattr(win, "isActiveWindow", lambda: True)
    win.changeEvent(QEvent(QEvent.ActivationChange))
    assert win.table.filtered_rows()[0].record.customer == "Komut satırından"


def test_broken_file_shows_message_and_blocks_new_keys(window, paths, warnings):
    paths[1].write_text("customer_id;customer\n1;X\n", encoding="utf-8")
    win = window()
    assert warnings and "okunamadı" in warnings[0]
    assert not win.btn_new.isEnabled()
    win.reload()
    assert len(warnings) == 1  # aynı hata her pencere etkinleşmesinde yeniden gösterilmez


# ------------------------------------------------------------ özel anahtar
def test_missing_private_key_blocks_issuing_but_list_still_works(window, paths, warnings):
    add(paths, "X", dt.date(2026, 11, 21))
    paths[0].unlink()
    win = window()
    assert not win.btn_new.isEnabled() and win.key_badge.text() == "Özel anahtar yok"
    assert len(win.table.filtered_rows()) == 1
    win.renew(win.table.visible_rows()[0])
    assert warnings and "Özel anahtar" in warnings[0]


def test_private_key_badge_when_ready(window):
    assert window().key_badge.text() == "Özel anahtar hazır"


# ------------------------------------------------------------ yeni lisans penceresi
def test_new_license_issues_machine_bound_key(qapp, paths):
    d = dialog(paths)
    d.customer.setText("Y Kliniği")
    d.machine.setText(CODE)
    d.duration.setCurrentIndex(d.duration.findData(14))
    d.btn_issue.click()
    assert d.result() == QDialog.Accepted
    assert d.record.customer == "Y Kliniği" and d.record.expires == dt.date(2026, 11, 21)
    assert lic.verify(d.record.key, public_key=PUB, machine=MACHINE, today=TODAY, check_clock=False).valid
    dispose(d)


def test_invalid_input_keeps_dialog_open_and_logs_nothing(qapp, paths, warnings):
    d = dialog(paths)
    d.customer.setText("Y")
    d.machine.setText("hatalı")
    d.btn_issue.click()
    assert d.record is None and warnings
    assert not paths[1].exists()
    dispose(d)


def test_enter_key_does_not_issue_a_key_by_accident(qapp, paths):
    d = dialog(paths)
    assert not d.btn_issue.isDefault() and not d.btn_issue.autoDefault()
    dispose(d)


def test_choosing_duration_updates_date(qapp, paths):
    d = dialog(paths)
    d.duration.setCurrentIndex(d.duration.findData(365))
    assert d.end_date.date() == QDate(2027, 11, 7)
    dispose(d)


def test_editing_date_switches_to_custom_duration(qapp, paths):
    d = dialog(paths)
    d.end_date.setDate(QDate(2026, 12, 25))
    assert d.duration.currentData() == manager.CUSTOM_DURATION
    d.customer.setText("Y")
    d.machine.setText(CODE)
    d.btn_issue.click()
    assert d.record.expires == dt.date(2026, 12, 25)
    dispose(d)


def test_perpetual_choice_disables_date(qapp, paths):
    d = dialog(paths)
    d.duration.setCurrentIndex(d.duration.findData(manager.PERPETUAL_DURATION))
    assert not d.end_date.isEnabled()
    d.customer.setText("Y")
    d.machine.setText(CODE)
    d.btn_issue.click()
    assert d.record.expires is None
    dispose(d)


def test_demo_type_hides_machine_code_and_perpetual(qapp, paths):
    d = dialog(paths)
    d.duration.setCurrentIndex(d.duration.findData(365))
    d.kind.setCurrentIndex(d.kind.findData(manager.KIND_DEMO))
    assert not d.machine.isEnabled() and d.demo_warning.isVisibleTo(d)
    assert d.duration.findData(manager.PERPETUAL_DURATION) == -1 and d.duration.findData(365) == -1
    assert d.end_date.date() <= QDate(2026, 12, 8)
    d.customer.setText("Sunum")
    d.btn_issue.click()
    assert d.record.is_demo
    dispose(d)


# ------------------------------------------------------------ yenileme
def test_renew_is_locked_to_customer_and_continues_from_current_expiry(qapp, paths):
    rec = add(paths, "X", dt.date(2026, 12, 1))
    d = dialog(paths, renewing=rec)
    assert d.customer.text() == "X" and d.customer.isReadOnly() and d.machine.isReadOnly()
    assert d.duration.currentData() == 365 and d.end_date.date() == QDate(2027, 12, 1)
    d.btn_issue.click()
    rows = {r.record.customer_id: r.status for r in store.build_rows(store.load_records(paths[1]), TODAY)}
    assert rows == {rec.customer_id: store.RENEWED, d.record.customer_id: store.ACTIVE}
    dispose(d)


def test_renewing_old_row_uses_latest_key(window, paths, monkeypatch):
    old = add(paths, "X", dt.date(2026, 11, 20))
    new = add(paths, "X", dt.date(2027, 1, 1))
    seen = []

    class FakeDialog:
        def __init__(self, **kw):
            seen.append(kw["renewing"])

        def exec(self):
            return QDialog.Rejected

        def deleteLater(self):
            pass

    monkeypatch.setattr(manager, "LicenseDialog", FakeDialog)
    win = window()
    win.show_history.setChecked(True)
    row = next(r for r in win.table.filtered_rows() if r.record.customer_id == old.customer_id)
    win.renew(row)
    assert seen == [new]


def test_after_issuing_key_is_shown_and_list_updated(window, paths, monkeypatch):
    shown = []
    rec = store.LicenseRecord(1, "Y", CODE, dt.date(2026, 11, 21), TODAY, "ANAHTAR")

    class FakeDialog:
        def __init__(self, **kw):
            self.record = rec

        def exec(self):
            store.issue(customer="Y", machine_code=CODE, expires=dt.date(2026, 11, 21), today=TODAY,
                        private_key=paths[0], log=paths[1])
            return QDialog.Accepted

        def deleteLater(self):
            pass

    monkeypatch.setattr(manager, "LicenseDialog", FakeDialog)
    monkeypatch.setattr(manager.KeyDialog, "exec", lambda self: shown.append(self.key_text.toPlainText()))
    win = window()
    win.new_license()
    assert shown == ["ANAHTAR"] and cells(win)[0] == "Y"


def test_key_dialog_copies_key(qapp):
    rec = store.LicenseRecord(1, "Y", CODE, dt.date(2026, 11, 21), TODAY, "ANAHTAR-KOD")
    d = manager.KeyDialog(rec)
    assert d.key_text.isReadOnly()
    d.btn_copy.click()
    assert QGuiApplication.clipboard().text() == "ANAHTAR-KOD"
    dispose(d)


# ------------------------------------------------------------ ortak tablo bileşeni
def test_data_table_column_can_color_text(qapp):
    table = DataTable([Column("Ad", str, color=lambda row: "#112233" if row == "kırmızı" else None)], str)
    table.set_rows(["kırmızı", "normal"])
    assert table.table.item(0, 0).foreground().color() == QColor("#112233")
    assert table.table.item(1, 0).foreground().color() != QColor("#112233")
    dispose(table)


def _pixels_near(image, color, tolerance=40):
    target = QColor(color)
    found = 0
    for x in range(0, image.width(), 1):
        for y in range(0, image.height(), 1):
            c = image.pixelColor(x, y)
            if (abs(c.red() - target.red()) + abs(c.green() - target.green()) + abs(c.blue() - target.blue())) < tolerance:
                found += 1
    return found


def test_status_color_is_really_painted_with_app_theme(window, paths):
    """Tema, satır yazı rengini ezmemeli: durum yalnız nesnede değil ekranda da renkli görünmeli."""
    add(paths, "X", dt.date(2026, 11, 8), other_code(1), today=dt.date(2026, 11, 1))
    add(paths, "Y", dt.date(2026, 11, 2), other_code(2), today=dt.date(2026, 11, 1))
    app = QApplication.instance()
    previous = app.styleSheet()
    app.setStyleSheet(theme.QSS)
    try:
        win = window()
        win.resize(2800, 900)  # test ortamının yazı tipi geniş: tüm sütunlar görünsün
        win.show()
        QCoreApplication.processEvents()
        image = win.table.table.viewport().grab().toImage()
        assert _pixels_near(image, theme.WARNING_TEXT) > 0 and _pixels_near(image, theme.BAD) > 0
    finally:
        app.setStyleSheet(previous)


def test_one_year_means_same_date_next_year_even_in_leap_year(qapp, paths):
    d = manager.LicenseDialog(private_key=paths[0], log=paths[1], today=dt.date(2027, 11, 11))
    d.duration.setCurrentIndex(d.duration.findData(365))
    assert d.end_date.date() == QDate(2028, 11, 11)
    dispose(d)


def test_demo_warning_tells_what_to_do_for_a_customer(qapp, paths):
    d = dialog(paths)
    d.kind.setCurrentIndex(d.kind.findData(manager.KIND_DEMO))
    assert "Yeni lisans" in d.demo_warning.text() and "bilgisayara bağlı" in d.demo_warning.text()
    assert d.machine.placeholderText() == ""  # kapalı alanda örnek kod, girilmiş kod gibi görünmesin
    d.kind.setCurrentIndex(d.kind.findData(manager.KIND_MACHINE))
    assert d.machine.placeholderText() == manager.MACHINE_PLACEHOLDER
    dispose(d)


# ------------------------------------------------------------ yenileme tek satırda görünür
def test_renewed_license_stays_a_single_row_with_latest_dates(window, paths):
    add(paths, "X", dt.date(2026, 11, 20))
    newest = add(paths, "X", dt.date(2027, 11, 20))
    win = window()
    rows = win.table.filtered_rows()
    assert [r.record for r in rows] == [newest]
    assert cells(win)[3] == "20.11.2027" and cells(win)[6] == "1 kez"
    assert win.tile_total.value.text() == "2" and win.tile_active.value.text() == "1"


def test_history_switch_shows_old_keys(window, paths):
    add(paths, "X", dt.date(2026, 11, 20))
    add(paths, "X", dt.date(2027, 11, 20))
    win = window()
    win.show_history.setChecked(True)
    assert [r.status for r in win.table.filtered_rows()] == [store.ACTIVE, store.RENEWED]
    win.show_history.setChecked(False)
    assert len(win.table.filtered_rows()) == 1


def test_two_machines_of_same_customer_stay_separate_rows(window, paths):
    add(paths, "X", dt.date(2026, 11, 20), other_code(1))
    add(paths, "X", dt.date(2026, 11, 20), other_code(2))
    assert len(window().table.filtered_rows()) == 2


# ------------------------------------------------------------ listeden kaldırma
def test_row_has_a_remove_action(window, paths):
    add(paths, "X", dt.date(2026, 11, 21))
    win = window()
    t = win.table.table
    assert len(t.cellWidget(0, t.columnCount() - 1).findChildren(QPushButton)) == 3


def test_removing_a_license_removes_all_its_keys_after_confirmation(window, paths, monkeypatch):
    add(paths, "X", dt.date(2026, 11, 20))
    add(paths, "X", dt.date(2027, 11, 20))
    add(paths, "Y", dt.date(2027, 11, 20), other_code(2))
    win = window()
    monkeypatch.setattr(win, "_confirm_remove", lambda text: True)
    row = next(r for r in win.table.filtered_rows() if r.record.customer == "X")
    win.remove_license(row)
    assert [r.record.customer for r in win.table.filtered_rows()] == ["Y"]
    assert [r.customer for r in store.load_records(paths[1])] == ["Y"]


def test_cancelling_keeps_the_license(window, paths, monkeypatch):
    add(paths, "X", dt.date(2026, 11, 21))
    win = window()
    monkeypatch.setattr(win, "_confirm_remove", lambda text: False)
    win.remove_license(win.table.visible_rows()[0])
    assert len(win.table.filtered_rows()) == 1 and len(store.load_records(paths[1])) == 1


def test_removing_old_key_from_history_keeps_the_license(window, paths, monkeypatch):
    old = add(paths, "X", dt.date(2026, 11, 20))
    add(paths, "X", dt.date(2027, 11, 20))
    win = window()
    win.show_history.setChecked(True)
    monkeypatch.setattr(win, "_confirm_remove", lambda text: True)
    win.remove_license(next(r for r in win.table.filtered_rows() if r.record.customer_id == old.customer_id))
    rows = win.table.filtered_rows()
    assert len(rows) == 1 and rows[0].status == store.ACTIVE and rows[0].renewals == 0


def _remove_text(win, row):
    captured = []
    win._confirm_remove = lambda text: captured.append(text) or False
    win.remove_license(row)
    return captured[0]


def test_warning_says_key_keeps_working_until_expiry(window, paths):
    add(paths, "X Hastanesi", dt.date(2026, 11, 21))
    win = window()
    text = _remove_text(win, win.table.visible_rows()[0])
    assert "X Hastanesi" in text and "iptal olmaz" in text and "21.11.2026" in text


def test_warning_for_perpetual_key(window, paths):
    add(paths, "X", None)
    win = window()
    text = _remove_text(win, win.table.visible_rows()[0])
    assert "iptal olmaz" in text and "süresiz" in text


def test_no_warning_when_key_has_already_expired(window, paths):
    add(paths, "X", dt.date(2026, 11, 2), today=dt.date(2026, 11, 1))
    win = window()
    assert "iptal olmaz" not in _remove_text(win, win.table.visible_rows()[0])


def test_message_counts_older_keys(window, paths):
    add(paths, "X", dt.date(2026, 11, 20))
    add(paths, "X", dt.date(2026, 12, 20))
    add(paths, "X", dt.date(2027, 11, 20))
    win = window()
    assert "2 eski anahtar" in _remove_text(win, win.table.visible_rows()[0])


def test_cancel_is_the_default_choice(window, monkeypatch):
    seen = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.append(self.defaultButton().text()))
    assert window()._confirm_remove("emin misiniz") is False
    assert seen == ["Vazgeç"]


# ------------------------------------------------------------ pencereye dönünce tablo gereksiz yere kurulmaz
def _action_cell(win):
    t = win.table.table
    return t.cellWidget(0, t.columnCount() - 1)


def test_reload_does_not_rebuild_buttons_when_nothing_changed(window, paths):
    """Fare altındaki düğme silinip yeniden yaratılırsa ipucu ve üzerine gelme durumu yanıp söner."""
    add(paths, "X", dt.date(2026, 11, 21))
    win = window()
    cell = _action_cell(win)
    win.reload()
    assert _action_cell(win) is cell


def test_reload_rebuilds_when_file_changed(window, paths):
    add(paths, "X", dt.date(2026, 11, 21))
    win = window()
    add(paths, "Y", dt.date(2026, 11, 22), other_code(2))
    win.reload()
    assert len(win.table.filtered_rows()) == 2


def test_reload_updates_when_day_changes(window, paths):
    add(paths, "X", dt.date(2026, 11, 21))
    days = [TODAY]
    win = manager.LicenseManagerWindow(private_key=paths[0], log=paths[1], today=lambda: days[0])
    assert cells(win)[4] == "14 gün"
    days[0] = TODAY + dt.timedelta(days=1)
    win.reload()
    assert cells(win)[4] == "13 gün" and win.date_label.text() == "08.11.2026"
    dispose(win)


def test_activation_does_not_reload_while_a_dialog_is_open(window, paths, monkeypatch):
    win = window()
    calls = []
    monkeypatch.setattr(win, "isActiveWindow", lambda: True)
    monkeypatch.setattr(win, "reload", lambda: calls.append(True))
    monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: win))
    win.changeEvent(QEvent(QEvent.ActivationChange))
    assert calls == []
    monkeypatch.setattr(QApplication, "activeModalWidget", staticmethod(lambda: None))
    win.changeEvent(QEvent(QEvent.ActivationChange))
    assert calls == [True]
