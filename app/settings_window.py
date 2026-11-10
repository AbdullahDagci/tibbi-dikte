"""Ayarlar, Lisans ve Hakkında sayfaları."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from . import __version__, theme
from .audio import configured_device, list_input_devices, play_tone
from .config import Config
from .engines.registry import discover_models, resolve_model
from .hotkey import is_valid, pynput_to_qt, qt_to_pynput
from .licensing import license as lic
from .mic_test import MicTestPanel
from .ptt import PTT_KEYS
from .ui import widgets
from .ui.icons import pixmap as icon_pixmap


class SettingsPage(QWidget):
    settings_changed = Signal(bool)   # True = model/sözlük yeniden yüklenmeli

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.cfg = cfg

        left, right = QVBoxLayout(), QVBoxLayout()
        for column, cards in ((left, (self._model_card(), self._beep_card())),
                              (right, (self._hotkey_card(), self._typing_card(), self._correction_card()))):
            column.setSpacing(14)
            for card in cards:
                column.addWidget(card)
            column.addStretch()
        holder = QWidget()
        holder_lay = QHBoxLayout(holder)
        holder_lay.setContentsMargins(22, 18, 22, 12)
        holder_lay.setSpacing(14)
        holder_lay.addLayout(left, 1)
        holder_lay.addLayout(right, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(holder)

        self.saved_badge = widgets.Badge("Kaydedildi", "success")
        self.saved_badge.setVisible(False)
        self.btn_save = widgets.button("Kaydet", "device-floppy", "success")
        self.btn_save.clicked.connect(self._save_clicked)
        footer = QHBoxLayout()
        footer.setContentsMargins(22, 0, 22, 16)
        footer.addStretch()
        footer.addWidget(self.saved_badge)
        footer.addWidget(self.btn_save)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll, 1)
        lay.addLayout(footer)
        self._load_values()

    def _fill_lists(self) -> list:
        """Model ve mikrofon listelerini yeniden okur: sonradan eklenen model ya da takılan mikrofon görünür."""
        models = discover_models()
        self._default_model_dir = str(resolve_model(models, "").dir) if models else ""
        self.model_box.clear()
        for m in models:
            label = f"{m.name} (varsayılan)" if str(m.dir) == self._default_model_dir else m.name
            self.model_box.addItem(label, str(m.dir))
        self.mic_box.clear()
        self.mic_box.addItem("Varsayılan mikrofon", None)
        for i, name in list_input_devices():
            self.mic_box.addItem(name, i)
        return models

    def _load_values(self) -> None:
        """Denetimleri kayıtlı ayarlarla doldurur."""
        models = self._fill_lists()
        if models:
            self.model_box.setCurrentIndex(
                max(0, self.model_box.findData(str(resolve_model(models, self.cfg.model_dir).dir))))
        self.mic_box.setCurrentIndex(max(0, self.mic_box.findData(configured_device(self.cfg))))
        self.threads.setValue(self.cfg.num_threads)
        self.hotkey_edit.setKeySequence(QKeySequence(pynput_to_qt(self.cfg.hotkey)))
        self.ptt_box.setCurrentIndex(max(0, self.ptt_box.findData(self.cfg.ptt_key)))
        for switch, value in ((self.cb_live, self.cfg.live_typing), (self.cb_space, self.cfg.add_trailing_space),
                              (self.cb_overlay, self.cfg.show_overlay), (self.cb_itn, self.cfg.use_itn)):
            switch.setChecked(value)
        self.beep_on.setChecked(self.cfg.beep_enabled)
        self.beep_start_hz.setValue(self.cfg.beep_start_hz)
        self.beep_stop_hz.setValue(self.cfg.beep_stop_hz)
        self.beep_ms.setValue(self.cfg.beep_ms)
        self._beep_toggled(self.cfg.beep_enabled)

    def showEvent(self, event) -> None:
        """Kaydedilmeden bırakılan değişiklik uygulanmış gibi görünmesin; küçültüp geri açmak dokunmaz."""
        super().showEvent(event)
        if not event.spontaneous():
            self._load_values()

    # ------------------------------------------------------------ kartlar
    def _model_card(self) -> widgets.Card:
        card = widgets.Card("Model ve ses", "cpu")
        form = self._form()
        self.model_box = self._combo()
        form.addRow("Konuşma modeli", self.model_box)
        self.mic_box = self._combo()
        form.addRow("Mikrofon", self.mic_box)
        self.mic_test = MicTestPanel(lambda: self.mic_box.currentData())  # kaydetmeden önce seçili mikrofon denenir
        form.addRow("", self.mic_test)
        self.threads = QSpinBox()
        self.threads.setRange(1, 8)
        form.addRow("İşlemci iş parçacığı", self.threads)
        card.body.addLayout(form)
        return card

    def _hotkey_card(self) -> widgets.Card:
        card = widgets.Card("Kısayollar", "keyboard")
        form = self._form()
        self.hotkey_edit = QKeySequenceEdit()
        form.addRow("Başlat / Durdur", self.hotkey_edit)
        self.ptt_box = self._combo()
        for key, (label, _) in PTT_KEYS.items():
            self.ptt_box.addItem(label, key)
        self.ptt_box.setToolTip("Tuş basılı tutulduğu sürece dikte yapılır. Boşlukta kısa basış normal boşluk yazar; "
                                "yaklaşık 0,35 sn basılı tutunca dikte başlar.")
        form.addRow("Bas-konuş tuşu", self.ptt_box)
        card.body.addLayout(form)
        return card

    def _typing_card(self) -> widgets.Card:
        card = widgets.Card("Yazım", "pencil")
        self.cb_live, self.cb_space, self.cb_overlay = widgets.Switch(), widgets.Switch(), widgets.Switch()
        card.body.addWidget(widgets.switch_row(
            "Konuşurken anında yaz", self.cb_live,
            "Kapalıysa metin her cümlenin sonunda tek seferde yazılır. Geri silme (Backspace) ile sorun yaşayan "
            "uygulamalarda kapatın."))
        card.body.addWidget(widgets.switch_row("Cümle sonunda boşluk bırak", self.cb_space))
        card.body.addWidget(widgets.switch_row("Dinlerken ekranda gösterge", self.cb_overlay))
        return card

    def _correction_card(self) -> widgets.Card:
        card = widgets.Card("Düzeltmeler", "wand")
        self.cb_itn = widgets.Switch()
        card.body.addWidget(widgets.switch_row("Sayıları rakamla yaz", self.cb_itn, "beş yüz miligram → 500 mg"))
        return card

    def _beep_card(self) -> widgets.Card:
        card = widgets.Card("Bip sesi", "volume")
        self.beep_on = widgets.Switch()
        self.beep_on.toggled.connect(self._beep_toggled)
        card.body.addWidget(widgets.switch_row("Dikte başlarken ve biterken bip çal", self.beep_on))
        self.beep_start_hz = self._spin(200, 4000, 10, " Hz")
        self.beep_stop_hz = self._spin(200, 4000, 10, " Hz")
        self.beep_ms = self._spin(20, 1000, 10, " ms")
        self.btn_beep_start = widgets.button("Dinle", "player-play", "light")
        self.btn_beep_start.clicked.connect(self._play_start_tone)
        self.btn_beep_stop = widgets.button("Dinle", "player-play", "light")
        self.btn_beep_stop.clicked.connect(self._play_stop_tone)
        form = self._form()
        form.addRow("Başlama sesi", self._with_button(self.beep_start_hz, self.btn_beep_start))
        form.addRow("Bitiş sesi", self._with_button(self.beep_stop_hz, self.btn_beep_stop))
        form.addRow("Süre", self.beep_ms)
        card.body.addLayout(form)
        return card

    @staticmethod
    def _spin(low: int, high: int, step: int, suffix: str) -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setSingleStep(step)
        box.setSuffix(suffix)
        return box

    @staticmethod
    def _with_button(field: QWidget, button: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(field, 1)
        row.addWidget(button)
        return row

    def _beep_toggled(self, on: bool) -> None:
        for w in (self.beep_start_hz, self.beep_stop_hz, self.beep_ms, self.btn_beep_start, self.btn_beep_stop):
            w.setEnabled(on)

    def _play_start_tone(self) -> None:
        play_tone(self.beep_start_hz.value(), self.beep_ms.value())

    def _play_stop_tone(self) -> None:
        play_tone(self.beep_stop_hz.value(), self.beep_ms.value())

    @staticmethod
    def _form() -> QFormLayout:
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return form

    @staticmethod
    def _combo() -> QComboBox:
        """Uzun model ve mikrofon adları kartı genişletmesin; ad sığmazsa kısaltılır."""
        box = QComboBox()
        box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        box.setMinimumContentsLength(16)
        return box

    # ------------------------------------------------------------ kaydet
    def _save_clicked(self) -> None:
        self.save()

    def save(self) -> bool:
        seq = self.hotkey_edit.keySequence().toString(QKeySequence.PortableText)
        hk = qt_to_pynput(seq) if seq else self.cfg.hotkey
        if not is_valid(hk):
            QMessageBox.warning(self, "Kısayol", f"Geçersiz kısayol: {seq}")
            return False
        old = self._reload_keys()
        chosen = self.model_box.currentData() or ""
        # varsayılan seçiliyse boş bırak: sonraki sürümde varsayılan değişirse kullanıcı da geçer
        self.cfg.model_dir = "" if chosen == self._default_model_dir else chosen
        self.cfg.input_device = self.mic_box.currentData()
        self.cfg.input_device_name = self.mic_box.currentText() if self.cfg.input_device is not None else ""
        self.cfg.hotkey = hk
        self.cfg.ptt_key = self.ptt_box.currentData()
        self.cfg.num_threads = self.threads.value()
        self.cfg.use_itn = self.cb_itn.isChecked()
        self.cfg.add_trailing_space = self.cb_space.isChecked()
        self.cfg.live_typing = self.cb_live.isChecked()
        self.cfg.show_overlay = self.cb_overlay.isChecked()
        self.cfg.beep_enabled = self.beep_on.isChecked()
        self.cfg.beep_start_hz = self.beep_start_hz.value()
        self.cfg.beep_stop_hz = self.beep_stop_hz.value()
        self.cfg.beep_ms = self.beep_ms.value()
        self.cfg.save()
        self.settings_changed.emit(old != self._reload_keys())
        self.saved_badge.setVisible(True)
        QTimer.singleShot(2500, self._hide_saved_badge)
        return True

    def _reload_keys(self) -> tuple:
        return self.cfg.model_dir, self.cfg.num_threads, self.cfg.use_itn

    def _hide_saved_badge(self) -> None:
        self.saved_badge.setVisible(False)


class LicensePage(QWidget):
    license_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        card = widgets.Card("Ürün lisansı", "shield-check")
        self.status_badge = widgets.Badge()
        card.add_action(self.status_badge)
        self.lic_status = QLabel()
        self.lic_status.setObjectName("muted")
        self.lic_status.setWordWrap(True)
        card.body.addWidget(self.lic_status)

        machine_label = QLabel("Makine kodu")
        machine_label.setObjectName("fieldLabel")
        card.body.addWidget(machine_label)
        self.mcode = QLineEdit(lic.machine_code())
        self.mcode.setReadOnly(True)
        copy = widgets.button("Kopyala", "copy", "light")
        copy.clicked.connect(self._copy_machine_code)
        row = QHBoxLayout()
        row.addWidget(self.mcode, 1)
        row.addWidget(copy)
        card.body.addLayout(row)

        key_label = QLabel("Ürün anahtarı")
        key_label.setObjectName("fieldLabel")
        card.body.addWidget(key_label)
        self.key_edit = QPlainTextEdit(lic.load_saved() or "")
        self.key_edit.setFixedHeight(90)
        card.body.addWidget(self.key_edit)
        self.btn_activate = widgets.button("Etkinleştir", "key", "success")
        self.btn_activate.clicked.connect(self._activate)
        card.body.addWidget(self.btn_activate, alignment=Qt.AlignLeft)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(card)
        lay.addStretch()
        self.refresh()

    def refresh(self) -> None:
        info = lic.current()
        self.status_badge.set_state("Etkin" if info.valid else "Etkin değil", "success" if info.valid else "danger")
        self.lic_status.setText(info.message)

    def _copy_machine_code(self) -> None:
        QGuiApplication.clipboard().setText(self.mcode.text())

    def _activate(self) -> None:
        info = lic.activate(self.key_edit.toPlainText())
        if info.valid:
            QMessageBox.information(self, "Lisans", f"Ürün etkinleştirildi.\n{info.message}")
            self.license_changed.emit()
        else:
            QMessageBox.warning(self, "Lisans", info.message)
        self.refresh()


COPYRIGHT_YEAR = 2026  # Hakkında ve kurulum sözleşmesi (installer/lisans_sozlesmesi.txt) aynı yılı gösterir


class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        logo = QLabel()
        logo.setPixmap(icon_pixmap("stethoscope", theme.PRIMARY, 72))
        title = QLabel("Tıbbi Dikte")
        title.setObjectName("pageTitle")
        version = QLabel(f"Türkçe tıbbi dikte yazılımı · Sürüm {__version__}")
        rights = QLabel(f"© {COPYRIGHT_YEAR} Tıbbi Dikte. Tüm hakları saklıdır.")
        rights.setObjectName("muted")
        card = widgets.Card()
        card.body.setContentsMargins(24, 28, 24, 28)
        for widget in (logo, title, version, rights):
            card.body.addWidget(widget, alignment=Qt.AlignHCenter)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(card)
        lay.addStretch()
