"""Ayarlar penceresi: Genel · Sözlük · Lisans · Hakkında."""
from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from . import __version__, user_dict
from .audio import list_input_devices
from .config import Config
from .dictation import USER_CORRECTIONS, USER_LEXICON, ensure_user_files
from .engines.registry import discover_models, resolve_model
from .hotkey import is_valid, pynput_to_qt, qt_to_pynput
from .lexicon_editor import LexiconEditor
from .licensing import license as lic
from .paths import install_dir
from .ptt import PTT_KEYS

TAB_GENERAL, TAB_LEXICON, TAB_LICENSE, TAB_ABOUT = range(4)


class SettingsWindow(QDialog):
    settings_changed = Signal(bool)   # True = model/sözlük yeniden yüklenmeli
    license_changed = Signal()

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Tıbbi Dikte — Ayarlar")
        self.setMinimumSize(760, 560)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "Genel")
        self.tabs.addTab(self._lexicon_tab(), "Sözlük")
        self.tabs.addTab(self._license_tab(), "Lisans")
        self.tabs.addTab(self._about_tab(), "Hakkında")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Save).setText("Kaydet")
        buttons.button(QDialogButtonBox.Close).setText("Kapat")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(buttons)

    # ------------------------------------------------------------ Genel
    def _general_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.model_box = QComboBox()
        models = discover_models()
        self._default_model_dir = str(resolve_model(models, "").dir) if models else ""
        for m in models:
            label = f"{m.name} (varsayılan)" if str(m.dir) == self._default_model_dir else m.name
            self.model_box.addItem(label, str(m.dir))
        if models:
            self.model_box.setCurrentIndex(
                max(0, self.model_box.findData(str(resolve_model(models, self.cfg.model_dir).dir))))
        f.addRow("Konuşma modeli:", self.model_box)

        self.mic_box = QComboBox()
        self.mic_box.addItem("Varsayılan mikrofon", None)
        for i, name in list_input_devices():
            self.mic_box.addItem(name, i)
        idx = self.mic_box.findData(self.cfg.input_device)
        self.mic_box.setCurrentIndex(max(0, idx))
        f.addRow("Mikrofon:", self.mic_box)

        self.hotkey_edit = QKeySequenceEdit(QKeySequence(pynput_to_qt(self.cfg.hotkey)))
        f.addRow("Başlat/Durdur kısayolu:", self.hotkey_edit)

        self.ptt_box = QComboBox()
        for key, (label, _) in PTT_KEYS.items():
            self.ptt_box.addItem(label, key)
        self.ptt_box.setCurrentIndex(max(0, self.ptt_box.findData(self.cfg.ptt_key)))
        self.ptt_box.setToolTip("Tuş basılı tutulduğu sürece dikte yapılır. Boşlukta kısa basış normal boşluk yazar; "
                                "yaklaşık 0,35 sn basılı tutunca dikte başlar.")
        f.addRow("Bas-konuş tuşu:", self.ptt_box)

        self.threads = QSpinBox()
        self.threads.setRange(1, 8)
        self.threads.setValue(self.cfg.num_threads)
        f.addRow("İşlemci iş parçacığı:", self.threads)

        self.cb_hot = QCheckBox("Tıbbi terimleri modele öncelikli tanıt (hotword)")
        self.cb_hot.setChecked(self.cfg.use_hotwords)
        self.cb_hot.setToolTip("Radyoloji için ince ayarlanmış modeller (Tıbbi Türkçe v3) terimleri kendisi öğrendi; "
                               "bu modellerde hotword otomatik olarak kullanılmaz.")
        self.cb_fuzzy = QCheckBox("Yanlış duyulan tıbbi terimleri otomatik düzelt")
        self.cb_fuzzy.setChecked(self.cfg.fuzzy_correction)
        self.cb_ctx = QCheckBox("Bağlama göre kelime düzelt (rapor dil modeli; ör. \"bacağı yayılan\" → \"bacağa\")")
        self.cb_ctx.setChecked(self.cfg.use_context)
        self.cb_itn = QCheckBox("Sayıları rakamla yaz (beş yüz miligram → 500 mg)")
        self.cb_itn.setChecked(self.cfg.use_itn)
        self.cb_live = QCheckBox("Konuşurken anında yaz (cümle sonunda düzeltilmiş hâliyle günceller)")
        self.cb_live.setChecked(self.cfg.live_typing)
        self.cb_live.setToolTip("Kapalıysa metin her cümlenin sonunda tek seferde yazılır. Geri silme (Backspace) "
                                "ile sorun yaşayan uygulamalarda kapatın.")
        self.cb_space = QCheckBox("Her cümleden sonra boşluk bırak")
        self.cb_space.setChecked(self.cfg.add_trailing_space)
        self.cb_overlay = QCheckBox("Dinlerken ekranda gösterge ve canlı metin göster")
        self.cb_overlay.setChecked(self.cfg.show_overlay)
        self.cb_post = QCheckBox("Tıbbi düzeltmeleri uygula (sayı, terim, sözlük) — kapalıysa model ne duyduysa o yazılır")
        self.cb_post.setChecked(self.cfg.use_postprocess)
        self.cb_post.toggled.connect(self._post_toggled)
        self._post_toggled(self.cfg.use_postprocess)
        for cb in (self.cb_live, self.cb_hot, self.cb_post, self.cb_fuzzy, self.cb_ctx, self.cb_itn, self.cb_space,
                   self.cb_overlay):
            f.addRow(cb)
        return w

    def _post_toggled(self, on: bool) -> None:
        for cb in (self.cb_fuzzy, self.cb_ctx, self.cb_itn):
            cb.setEnabled(on)

    # ------------------------------------------------------------ Sözlük
    def _lexicon_tab(self) -> QWidget:
        ensure_user_files()
        w = QWidget()
        v = QVBoxLayout(w)
        info = QLabel("Sözlük, modelin <b>yanlış yazdığı</b> kelimeleri sizin istediğiniz <b>doğru yazıma</b> çevirir. "
                      "Örnek: model <i>protrüzyon</i> yerine <i>protezyon</i> yazıyorsa doğru yazım "
                      "<b>protrüzyon</b>, söyleniş <b>protezyon</b>. Söyleniş olmadan eklenen terim de işe yarar: "
                      "büyük/küçük harfi korunur (<i>Doppler</i>) ve 8+ harfli terime çok yakın yazımlar ona "
                      "düzeltilir. Söyleniş bir sesli komuta da bağlanabilir (<i>alt sağa geç</i> → alt satıra geç).")
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        v.addWidget(info)
        self._lex_loaded = user_dict.load(USER_LEXICON, USER_CORRECTIONS)
        self.lex_editor = LexiconEditor(self._lex_loaded)
        v.addWidget(self.lex_editor, 1)

        row = QHBoxLayout()
        row.addStretch()
        imp = QPushButton("İçe aktar…")
        imp.clicked.connect(self._import_lexicon)
        exp = QPushButton("Dışa aktar…")
        exp.clicked.connect(self._export_lexicon)
        for b in (imp, exp):
            row.addWidget(b)
        v.addLayout(row)
        return w

    def _lexicon_entries(self) -> list[user_dict.Entry]:
        return self.lex_editor.entries()

    def _import_lexicon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Sözlüğü içe aktar", "",
                                              "Sözlük dosyaları (*.csv *.tsv *.txt);;Tüm dosyalar (*.*)")
        if not path:
            return
        try:
            incoming = user_dict.import_file(Path(path))
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            QMessageBox.warning(self, "İçe aktar", f"Dosya okunamadı:\n{e}")
            return
        merged, nt, nv = user_dict.merge(self._lexicon_entries(), incoming)
        self.lex_editor.set_entries(merged)
        QMessageBox.information(self, "İçe aktar", f"{nt} yeni terim, {nv} yeni varyant eklendi; mevcut "
                                                   "sözlük korundu.\nUygulamak için Kaydet'e basın.")

    def _export_lexicon(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Sözlüğü dışa aktar", "tibbi_dikte_sozluk.csv",
                                              "CSV (Excel) (*.csv)")
        if not path:
            return
        entries = self._lexicon_entries()
        user_dict.export_file(entries, Path(path))
        QMessageBox.information(self, "Dışa aktar", f"{len(entries)} terim kaydedildi:\n{path}")

    # ------------------------------------------------------------ Lisans
    def _license_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Makine kodunuz (ürün anahtarı almak için satıcıya iletin):"))
        row = QHBoxLayout()
        self.mcode = QLineEdit(lic.machine_code())
        self.mcode.setReadOnly(True)
        copy = QPushButton("Kopyala")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.mcode.text()))
        row.addWidget(self.mcode)
        row.addWidget(copy)
        v.addLayout(row)
        v.addSpacing(12)
        v.addWidget(QLabel("Ürün anahtarı:"))
        self.key_edit = QPlainTextEdit(lic.load_saved() or "")
        self.key_edit.setFixedHeight(90)
        v.addWidget(self.key_edit)
        act = QPushButton("Etkinleştir")
        act.clicked.connect(self._activate)
        v.addWidget(act, alignment=Qt.AlignLeft)
        self.lic_status = QLabel()
        self.lic_status.setWordWrap(True)
        v.addWidget(self.lic_status)
        v.addStretch()
        self._refresh_license()
        return w

    def _refresh_license(self) -> None:
        info = lic.current()
        color = "#1a7f37" if info.valid else "#b42318"
        self.lic_status.setText(f"<b style='color:{color}'>{'Etkin' if info.valid else 'Etkin değil'}</b> — {info.message}")

    def _activate(self) -> None:
        info = lic.activate(self.key_edit.toPlainText())
        if info.valid:
            QMessageBox.information(self, "Lisans", f"Ürün etkinleştirildi.\n{info.message}")
            self.license_changed.emit()
        else:
            QMessageBox.warning(self, "Lisans", info.message)
        self._refresh_license()

    # ------------------------------------------------------------ Hakkında
    def _about_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        lbl = QLabel(
            f"<h3>Tıbbi Dikte {__version__}</h3>"
            "<p>İmlecin bulunduğu alana Türkçe konuşmayı yazar. Ses bilgisayardan dışarı çıkmaz; "
            "tanıma tamamen yerel olarak yapılır.</p>")
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.RichText)
        v.addWidget(lbl)
        # Seçili modelin lisansı bir ibare gerektiriyorsa (model.json "attribution") burada gösterilir.
        self.attribution = QLabel()
        self.attribution.setObjectName("muted")
        v.addWidget(self.attribution)
        self.model_box.currentIndexChanged.connect(self._update_attribution)
        self._update_attribution()
        notices = QPushButton("Açık kaynak lisansları")
        notices.clicked.connect(self._open_notices)
        v.addWidget(notices, alignment=Qt.AlignLeft)
        v.addStretch()
        return w

    def _update_attribution(self) -> None:
        models = discover_models()
        m = resolve_model(models, self.model_box.currentData() or "") if models else None
        text = f"{m.name} ({m.attribution})" if m is not None and m.attribution else ""
        self.attribution.setText(f"Konuşma tanıma: {text}" if text else "")
        self.attribution.setVisible(bool(text))

    @staticmethod
    def _open_notices() -> None:
        import os
        notice = install_dir() / "NOTICE.txt"
        if notice.exists():
            os.startfile(str(notice))  # noqa: S606 (yerel dosya, varsayılan metin düzenleyici)

    # ------------------------------------------------------------ kaydet
    def _save(self) -> None:
        seq = self.hotkey_edit.keySequence().toString(QKeySequence.PortableText)
        hk = qt_to_pynput(seq) if seq else self.cfg.hotkey
        if not is_valid(hk):
            QMessageBox.warning(self, "Kısayol", f"Geçersiz kısayol: {seq}")
            return
        entries = self._lexicon_entries()
        clash = user_dict.conflicts(entries)
        if clash:
            lines = "\n".join(f"• “{v}” → {', '.join(t)}" for v, t in clash[:10])
            QMessageBox.warning(self, "Sözlük", "Aynı varyant birden çok terime bağlı; birini seçin:\n" + lines)
            self.tabs.setCurrentIndex(TAB_LEXICON)
            return
        old = (self.cfg.model_dir, self.cfg.num_threads, self.cfg.use_hotwords, self.cfg.use_itn,
               self.cfg.fuzzy_correction, self.cfg.use_context)
        chosen = self.model_box.currentData() or ""
        # varsayılan seçiliyse boş bırak: sonraki sürümde varsayılan değişirse kullanıcı da geçer
        self.cfg.model_dir = "" if chosen == self._default_model_dir else chosen
        self.cfg.input_device = self.mic_box.currentData()
        self.cfg.hotkey = hk
        self.cfg.ptt_key = self.ptt_box.currentData()
        self.cfg.num_threads = self.threads.value()
        self.cfg.use_hotwords = self.cb_hot.isChecked()
        self.cfg.fuzzy_correction = self.cb_fuzzy.isChecked()
        self.cfg.use_context = self.cb_ctx.isChecked()
        self.cfg.use_itn = self.cb_itn.isChecked()
        self.cfg.use_postprocess = self.cb_post.isChecked()
        self.cfg.add_trailing_space = self.cb_space.isChecked()
        self.cfg.live_typing = self.cb_live.isChecked()
        self.cfg.show_overlay = self.cb_overlay.isChecked()
        self.cfg.save()

        lex_changed = entries != self._lex_loaded
        if lex_changed:
            user_dict.save(entries, USER_LEXICON, USER_CORRECTIONS)
        new = (self.cfg.model_dir, self.cfg.num_threads, self.cfg.use_hotwords, self.cfg.use_itn,
               self.cfg.fuzzy_correction, self.cfg.use_context)
        self.settings_changed.emit(lex_changed or old != new)
        self.close()

    def show_tab(self, tab: int) -> None:
        self.tabs.setCurrentIndex(tab)
        self.show()
        self.raise_()
        self.activateWindow()
