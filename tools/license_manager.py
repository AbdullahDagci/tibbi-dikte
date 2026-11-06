"""Lisans Yöneticisi: verilen anahtarlar, kalan günler, yenileme ve yeni anahtar üretimi.

Yalnızca geliştirici bilgisayarında çalışır (tools/private_key.pem gerekir), müşteri paketine girmez.
Çalıştırma: tools\\LisansYoneticisi.cmd
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QDate, QEvent, QSize, Qt  # noqa: E402
from PySide6.QtGui import QCursor, QGuiApplication, QIcon  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QDateEdit, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,  # noqa: E402
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QToolTip, QVBoxLayout,
                               QWidget)

from app import theme  # noqa: E402
from app.licensing.license import DEMO_MAX_DAYS  # noqa: E402
from app.medical.postprocess import tr_lower  # noqa: E402
from app.ui import widgets  # noqa: E402
from app.ui.data_table import Column, DataTable, RowAction  # noqa: E402
from app.ui.icons import pixmap as icon_pixmap  # noqa: E402
from tools import license_store as store  # noqa: E402

APP_TITLE = "Lisans Yöneticisi"
KIND_MACHINE, KIND_DEMO = "machine", "demo"
MACHINE_PLACEHOLDER = "ABCD-EFGH-IJKL-MNOP"
PERPETUAL_DURATION, CUSTOM_DURATION = "perpetual", "custom"
_ONE_YEAR = 365
_DURATIONS = ((14, "14 gün"), (30, "30 gün"), (90, "90 gün"), (_ONE_YEAR, "1 yıl"))
_DEMO_DURATIONS = ((14, "14 gün"), (30, "30 gün"))
_STATUS_COLORS = {store.ACTIVE: theme.GOOD, store.EXPIRING: theme.WARNING_TEXT, store.EXPIRED: theme.BAD,
                  store.PERPETUAL: theme.PRIMARY, store.RENEWED: theme.MUTED}


def _date_text(day: dt.date | None) -> str:
    return "Süresiz" if day is None else f"{day:%d.%m.%Y}"


def _machine_text(record: store.LicenseRecord) -> str:
    return "Her bilgisayar" if record.is_demo else record.machine_code


def _days_text(row: store.LicenseRow) -> str:
    days = row.days_left
    if days is None:
        return "—"
    if days < 0:
        return f"{-days} gün önce doldu"
    return "Bugün bitiyor" if days == 0 else f"{days} gün"


def _days_sort_key(row: store.LicenseRow) -> tuple:
    return row.days_left is None, row.days_left or 0


def _search_text(row: store.LicenseRow) -> str:
    r = row.record
    return f"{r.customer} {_machine_text(r)} {row.status} {_date_text(r.issued)} {_date_text(r.expires)}"


def _customer(row: store.LicenseRow) -> str:
    return row.record.customer


def _machine(row: store.LicenseRow) -> str:
    return _machine_text(row.record)


def _issued(row: store.LicenseRow) -> str:
    return _date_text(row.record.issued)


def _issued_key(row: store.LicenseRow) -> dt.date:
    return row.record.issued


def _expires(row: store.LicenseRow) -> str:
    return _date_text(row.record.expires)


def _expires_key(row: store.LicenseRow) -> dt.date:
    return row.record.expires or dt.date.max


def _status(row: store.LicenseRow) -> str:
    return row.status


def _status_color(row: store.LicenseRow) -> str:
    return _STATUS_COLORS[row.status]


def _renewals(row: store.LicenseRow) -> str:
    return f"{row.renewals} kez" if row.renewals else "—"


def _renewals_key(row: store.LicenseRow) -> int:
    return row.renewals


def _qdate(day: dt.date) -> QDate:
    return QDate(day.year, day.month, day.day)


class LicenseDialog(QDialog):
    """Yeni anahtar ya da yenileme. Anahtar yalnızca düğmeyle üretilir: her anahtar kalıcı olarak kayda geçer."""

    def __init__(self, private_key: Path, log: Path, today: dt.date, renewing: store.LicenseRecord | None = None,
                 parent=None):
        super().__init__(parent)
        self._private_key, self._log, self._today = private_key, log, today
        self._renewing = renewing
        self._setting_date = False
        self.record: store.LicenseRecord | None = None
        self.setWindowTitle("Lisansı yenile" if renewing else "Yeni lisans")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(480)

        self.customer = QLineEdit()
        self.customer.setPlaceholderText("örn. X Hastanesi (deneme)")
        self.kind = QComboBox()
        self.kind.addItem("Bir bilgisayara bağlı", KIND_MACHINE)
        self.kind.addItem("Her bilgisayarda (yalnız kendi sunumlarınız)", KIND_DEMO)
        self.machine = QLineEdit()
        self.machine.setToolTip("Müşterinin uygulamadaki Lisans sayfasında yazan makine kodu")
        self.duration = QComboBox()
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("dd.MM.yyyy")
        self.end_date.setMinimumDate(_qdate(today + dt.timedelta(days=1)))
        self.demo_warning = QLabel("Bu anahtar her bilgisayarda çalışır ve iptal edilemez; yalnızca kendi sunumlarınız içindir. "
                                   "Müşteri için \"Yeni lisans\" ile bilgisayara bağlı anahtar üretin.")
        self.demo_warning.setStyleSheet(f"color:{theme.WARNING_TEXT}")
        self.demo_warning.setWordWrap(True)
        self.demo_warning.hide()

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.addRow("Müşteri", self.customer)
        form.addRow("Tür", self.kind)
        form.addRow("Makine kodu", self.machine)
        form.addRow("Süre", self.duration)
        form.addRow("Bitiş tarihi", self.end_date)

        self.btn_cancel = widgets.button("Vazgeç", "x", "light")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_issue = widgets.button("Anahtar üret", "key", "success")
        self.btn_issue.clicked.connect(self._issue)
        for btn in (self.btn_cancel, self.btn_issue):
            btn.setAutoDefault(False)
            btn.setDefault(False)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_issue)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        if renewing is not None:
            note = QLabel(f"Mevcut bitiş: {_date_text(renewing.expires)}. Yeni süre {_date_text(self._start())} tarihinden başlar.")
            note.setObjectName("muted")
            note.setWordWrap(True)
            root.addWidget(note)
        root.addLayout(form)
        root.addWidget(self.demo_warning)
        root.addLayout(buttons)

        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.duration.currentIndexChanged.connect(self._duration_changed)
        self.end_date.dateChanged.connect(self._date_edited)
        if renewing is not None:
            self.customer.setText(renewing.customer)
            self.customer.setReadOnly(True)
            self.kind.setEnabled(False)
            if renewing.is_demo:
                self.kind.setCurrentIndex(self.kind.findData(KIND_DEMO))
            else:
                self.machine.setText(renewing.machine_code)
                self.machine.setReadOnly(True)
        self._kind_changed()

    def _is_demo(self) -> bool:
        return self.kind.currentData() == KIND_DEMO

    def _start(self) -> dt.date:
        if self._renewing is None or self._renewing.is_demo:
            return self._today
        return store.renewal_start(self._renewing, self._today)

    def _kind_changed(self) -> None:
        demo = self._is_demo()
        self.machine.setEnabled(not demo)
        self.machine.setPlaceholderText("" if demo else MACHINE_PLACEHOLDER)
        self.demo_warning.setVisible(demo)
        limit = self._today + dt.timedelta(days=DEMO_MAX_DAYS) if demo else dt.date(2099, 12, 31)
        self.end_date.setMaximumDate(_qdate(limit))
        self.duration.blockSignals(True)
        self.duration.clear()
        for days, label in _DEMO_DURATIONS if demo else _DURATIONS:
            self.duration.addItem(label, days)
        if not demo:
            self.duration.addItem("Süresiz", PERPETUAL_DURATION)
        self.duration.addItem("Özel tarih", CUSTOM_DURATION)
        default = _ONE_YEAR if self._renewing is not None and not demo else 14
        self.duration.setCurrentIndex(self.duration.findData(default))
        self.duration.blockSignals(False)
        self._duration_changed()

    def _duration_changed(self) -> None:
        choice = self.duration.currentData()
        self.end_date.setEnabled(choice != PERPETUAL_DURATION)
        if isinstance(choice, int):
            self._setting_date = True
            start = _qdate(self._start())
            self.end_date.setDate(start.addYears(1) if choice == _ONE_YEAR else start.addDays(choice))
            self._setting_date = False

    def _date_edited(self) -> None:
        if not self._setting_date:
            self.duration.blockSignals(True)
            self.duration.setCurrentIndex(self.duration.findData(CUSTOM_DURATION))
            self.duration.blockSignals(False)

    def _issue(self) -> None:
        expires = None if self.duration.currentData() == PERPETUAL_DURATION else self.end_date.date().toPython()
        try:
            self.record = store.issue(self.customer.text(), self.machine.text(), self._is_demo(), expires,
                                      private_key=self._private_key, log=self._log, today=self._today)
        except store.LicenseError as e:
            QMessageBox.warning(self, "Lisans", str(e))
            return
        self.accept()


class KeyDialog(QDialog):
    """Üretilen anahtarı gösterir; müşteriye göndermek için kopyalanır."""

    def __init__(self, record: store.LicenseRecord, parent=None):
        super().__init__(parent)
        self._key = record.key
        self.setWindowTitle("Ürün anahtarı")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(520)
        where = "her bilgisayarda" if record.is_demo else f"{record.machine_code} kodlu bilgisayarda"
        info = QLabel(f"{record.customer} · bitiş: {_date_text(record.expires)}\nBu anahtar {where} çalışır.")
        info.setWordWrap(True)
        self.key_text = QPlainTextEdit(record.key)
        self.key_text.setReadOnly(True)
        self.key_text.setFixedHeight(92)
        self.btn_copy = widgets.button("Anahtarı kopyala", "copy", "primary")
        self.btn_copy.clicked.connect(self._copy)
        close = widgets.button("Kapat", "x", "light")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(close)
        buttons.addWidget(self.btn_copy)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        root.addWidget(info)
        root.addWidget(self.key_text)
        root.addLayout(buttons)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._key)
        self.btn_copy.setText("Kopyalandı")


class LicenseManagerWindow(QMainWindow):
    def __init__(self, private_key: Path = store.PRIVATE_KEY, log: Path = store.ISSUED_KEYS,
                 today: Callable[[], dt.date] = dt.date.today, parent=None):
        super().__init__(parent)
        self._private_key, self._log, self._today = private_key, log, today
        self._records: list[store.LicenseRecord] = []
        self._error = ""
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(theme.app_icon())
        self.setMinimumSize(960, 620)
        self.resize(1180, 760)

        title = QLabel("Lisanslar")
        title.setObjectName("pageTitle")
        self.date_label = QLabel()
        self.date_label.setObjectName("muted")
        self.key_badge = widgets.Badge()
        topbar = QFrame()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(22, 12, 22, 12)
        top.setSpacing(12)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.date_label)
        top.addWidget(self.key_badge)

        self.tile_active = widgets.StatTile("Geçerli lisans", "circle-check")
        self.tile_expiring = widgets.StatTile(f"{store.EXPIRING_DAYS} gün içinde bitecek", "alert-triangle")
        self.tile_expired = widgets.StatTile("Süresi dolan", "lock")
        self.tile_total = widgets.StatTile("Üretilen anahtar", "key")
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        for tile in (self.tile_active, self.tile_expiring, self.tile_expired, self.tile_total):
            tiles.addWidget(tile, 1)

        columns = [Column("Müşteri", _customer, stretch=True, bold=True), Column("Makine kodu", _machine),
                   Column("Veriliş", _issued, sort_key=_issued_key), Column("Bitiş", _expires, sort_key=_expires_key),
                   Column("Kalan süre", _days_text, sort_key=_days_sort_key), Column("Durum", _status, color=_status_color),
                   Column("Yenileme", _renewals, sort_key=_renewals_key)]
        actions = [RowAction("copy", "Anahtarı kopyala", self.copy_key), RowAction("refresh", "Lisansı yenile", self.renew)]
        self.table = DataTable(columns, _search_text, normalize=tr_lower, actions=actions,
                               search_placeholder="Müşteri, makine kodu, durum ara…", empty_text="Henüz lisans yok")
        self.show_history = widgets.Switch()
        self.show_history.toggled.connect(self._history_toggled)
        self.table.add_action(widgets.switch_row("Eski anahtarlar", self.show_history,
                                                 "Yenilenen lisansların önceki anahtarlarını da listeler."))
        self.btn_new = widgets.button("Yeni lisans", "plus", "primary")
        self.btn_new.clicked.connect(self.new_license)
        self.table.add_action(self.btn_new)
        card = widgets.Card()
        card.body.addWidget(self.table, 1)

        page = QWidget()
        page.setObjectName("page")
        pv = QVBoxLayout(page)
        pv.setContentsMargins(22, 18, 22, 18)
        pv.setSpacing(12)
        pv.addLayout(tiles)
        pv.addWidget(card, 1)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(topbar)
        cv.addWidget(page, 1)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())
        h.addWidget(content, 1)
        self.setCentralWidget(root)
        self.reload()

    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        v = QVBoxLayout(side)
        v.setContentsMargins(14, 16, 14, 14)
        v.setSpacing(4)
        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setPixmap(icon_pixmap("stethoscope", "#FFFFFF", 26))
        brand = QLabel("Tıbbi Dikte")
        brand.setObjectName("brand")
        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 0, 12)
        head.setSpacing(10)
        head.addWidget(logo)
        head.addWidget(brand)
        head.addStretch()
        v.addLayout(head)
        caption = QLabel("YÖNETİM")
        caption.setObjectName("navGroup")
        caption.setContentsMargins(10, 12, 0, 4)
        v.addWidget(caption)
        nav = QPushButton("Lisanslar")
        nav.setProperty("nav", True)
        nav.setCheckable(True)
        nav.setChecked(True)
        nav.setEnabled(True)
        icon = QIcon()
        icon.addPixmap(icon_pixmap("license", "#FFFFFF", 18), QIcon.Normal, QIcon.On)
        nav.setIcon(icon)
        nav.setIconSize(QSize(18, 18))
        nav.clicked.connect(self._keep_nav_checked)
        v.addWidget(nav)
        v.addStretch()
        note = QLabel(APP_TITLE)
        note.setObjectName("sidebarNote")
        note.setContentsMargins(10, 0, 0, 0)
        v.addWidget(note)
        return side

    def _keep_nav_checked(self) -> None:
        self.sender().setChecked(True)  # tek sayfa var: menü öğesi seçili kalır

    # ------------------------------------------------------------ veri
    def reload(self) -> None:
        error = ""
        try:
            self._records = store.load_records(self._log)
        except store.LicenseError as e:
            self._records, error = [], str(e)
        today = self._today()
        rows = store.build_rows(self._records, today)
        self.table.set_rows(rows if self.show_history.isChecked() else store.current_rows(rows), keep_page=True)
        s = store.summarize(rows)
        self.tile_active.set(str(s.active))
        self.tile_expiring.set(str(s.expiring), color=theme.WARNING_TEXT if s.expiring else None)
        self.tile_expired.set(str(s.expired), color=theme.BAD if s.expired else None)
        self.tile_total.set(str(s.total_keys), "yenilemeler dahil")
        self.date_label.setText(f"{today:%d.%m.%Y}")
        ready = store.has_private_key(self._private_key)
        self.key_badge.set_state("Özel anahtar hazır" if ready else "Özel anahtar yok", "success" if ready else "danger")
        self.btn_new.setEnabled(ready and not error)
        if error != self._error:  # uyarı kapanınca pencere yeniden etkinleşir: aynı hata tekrar tekrar gösterilmesin
            self._error = error
            if error:
                QMessageBox.warning(self, APP_TITLE, error)

    def _history_toggled(self, _checked: bool) -> None:
        self.reload()

    def changeEvent(self, event) -> None:
        """Pencereye dönünce liste ve kalan günler güncellenir (ör. komut satırından anahtar üretildiyse)."""
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.reload()

    # ------------------------------------------------------------ işlemler
    def copy_key(self, row: store.LicenseRow) -> None:
        QGuiApplication.clipboard().setText(row.record.key)
        QToolTip.showText(QCursor.pos(), "Anahtar kopyalandı")

    def new_license(self) -> None:
        self._run_dialog(LicenseDialog(private_key=self._private_key, log=self._log, today=self._today(), parent=self))

    def renew(self, row: store.LicenseRow) -> None:
        if not store.has_private_key(self._private_key):
            QMessageBox.warning(self, APP_TITLE, f"Özel anahtar bulunamadı: {self._private_key}")
            return
        latest = store.latest_of(self._records, row.record)
        self._run_dialog(LicenseDialog(private_key=self._private_key, log=self._log, today=self._today(), renewing=latest,
                                       parent=self))

    def _run_dialog(self, dialog) -> None:
        issued = dialog.exec() == QDialog.Accepted
        record = dialog.record if issued else None
        dialog.deleteLater()
        if record is None:
            return
        self.reload()
        shown = KeyDialog(record, parent=self)
        shown.exec()
        shown.deleteLater()


def main() -> int:
    if sys.platform == "win32":
        import ctypes
        # Görev çubuğunda Python değil, uygulamanın kendi simgesi görünsün
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TibbiDikte.LisansYoneticisi")
    app = QApplication(sys.argv)
    theme.apply(app)
    window = LicenseManagerWindow()
    window.show()
    code = app.exec()
    window.deleteLater()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
