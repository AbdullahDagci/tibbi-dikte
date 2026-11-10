"""Veri toplama ekranı: radyologlardan eğitim verisi (ses + doğru metin) toplar.

Modlar:
  Cümle oku     — ekranda bir rapor cümlesi; Enter ile kaydı başlat/durdur, Ctrl+Enter ile kaydet ve ilerle.
  Serbest dikte — kendi tarzında dikte; model metni çıkarır, radyolog düzeltir ve kaydeder (gerçek dikte üslubu).
Her kayıt kalite kontrolünden geçer (süre, patlama, kısıklık). Kayıt için konuşmacının KVKK açık rızası işaretlenmeli.
Çıktı: %APPDATA%/TibbiDikte/veri_toplama/<konuşmacı>/*.wav + aynı adlı .txt + manifest.csv
  -> training/prepare_data.py dir --src <klasör> --name radreal
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QProgressBar, QStackedWidget, QVBoxLayout, QWidget)

from . import theme
from .audio import MIC_OPEN_ERROR, level_fraction
from .paths import resource_dir, user_dir
from .ui import widgets

SR = 16000
OUT_ROOT = user_dir() / "veri_toplama"
DEFAULT_SENTENCES = resource_dir() / "medical" / "collect_sentences_tr.txt"


def quality(pcm: np.ndarray) -> tuple[bool, str]:
    """(kabul edilebilir mi, açıklama)"""
    dur = len(pcm) / SR
    if dur < 1.0:
        return False, f"Çok kısa ({dur:.1f} sn)"
    if dur > 30:
        return False, f"Çok uzun ({dur:.0f} sn) — cümleleri 30 sn'den kısa tutun"
    peak = float(np.abs(pcm).max())
    rms_db = 20 * np.log10(float(np.sqrt(np.mean(pcm ** 2))) + 1e-9)
    if peak >= 0.99:
        return False, "Ses patlıyor — mikrofonu biraz uzaklaştırın veya kazancı düşürün"
    if rms_db < -45:
        return False, f"Çok kısık ({rms_db:.0f} dBFS) — mikrofona yaklaşın"
    return True, f"Kalite iyi · {dur:.1f} sn · seviye {rms_db:.0f} dBFS"


class _Sig(QObject):
    transcribed = Signal(str)


class CollectPage(QWidget):
    def __init__(self, get_pipeline: Callable[[], tuple], parent=None,
                 get_device: Callable[[], int | None] = lambda: None):
        super().__init__(parent)
        self.setObjectName("page")
        self.setFocusPolicy(Qt.StrongFocus)
        self.get_pipeline = get_pipeline
        self.get_device = get_device  # Ayarlar'da seçili mikrofon
        self.sentences: list[str] = []
        self.sent_file = DEFAULT_SENTENCES
        self.idx = 0
        self.pcm: np.ndarray | None = None
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._sig = _Sig()
        self._sig.transcribed.connect(self._on_transcribed)
        self._state = self._load_state()
        self._build()
        self._load_sentences(Path(self._state.get("sentence_file", str(DEFAULT_SENTENCES))))
        self._refresh()

    # ------------------------------------------------ durum
    def _load_state(self) -> dict:
        f = OUT_ROOT / "durum.json"
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        OUT_ROOT.mkdir(parents=True, exist_ok=True)
        self._state.update(sentence_file=str(self.sent_file), speaker=self.speaker.text().strip())
        self._state.setdefault("index", {})[str(self.sent_file)] = self.idx
        (OUT_ROOT / "durum.json").write_text(json.dumps(self._state, ensure_ascii=False, indent=1), encoding="utf-8")

    # ------------------------------------------------ arayüz
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        speaker_label = QLabel("Konuşmacı kodu")
        speaker_label.setObjectName("fieldLabel")
        self.speaker = QLineEdit(self._state.get("speaker", ""))
        self.speaker.setPlaceholderText("ör. dr01 (isim yazmayın)")
        self.speaker.setFixedWidth(170)
        self.speaker.textChanged.connect(self._refresh)
        self.consent = QCheckBox("KVKK açık rıza formu imzalandı")
        self.consent.toggled.connect(self._refresh)
        self.mode = QComboBox()
        self.mode.addItems(["Cümle oku", "Serbest dikte"])
        self.mode.currentIndexChanged.connect(self._on_mode)
        pick = widgets.button("Cümle dosyası", "file-text", "light")
        pick.clicked.connect(self._pick_file)
        open_dir = widgets.button("Kayıt klasörü", "folder-open", "light")
        open_dir.clicked.connect(self._open_folder)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(speaker_label)
        row.addWidget(self.speaker)
        row.addWidget(self.consent)
        row.addWidget(widgets.InfoTip("Kayıtlar yalnızca bu bilgisayarda saklanır. Farklı konuşmacılar ve doğal dikte "
                                      "hızı en değerli veridir."))
        row.addStretch()
        row.addWidget(self.mode)
        setup = widgets.Card()
        setup.body.addLayout(row)
        root.addWidget(setup)

        card = widgets.Card()
        self.counter = QLabel("")
        self.counter.setObjectName("muted")
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(self.counter, 1)
        head.addWidget(pick)
        head.addWidget(open_dir)
        card.body.addLayout(head)
        self.stack = QStackedWidget()
        self.sentence = QLabel()
        self.sentence.setWordWrap(True)
        self.sentence.setStyleSheet("font-size: 21pt; line-height: 140%;")  # tema yazı boyutunu ezer
        self.sentence.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sentence.setMinimumHeight(140)
        self.free_text = QPlainTextEdit()
        self.free_text.setStyleSheet("font-size: 14pt;")
        self.free_text.setPlaceholderText("Kaydı başlatın ve dikte edin. Kayıt bitince metni düzeltip kaydedin.")
        self.stack.addWidget(self.sentence)
        self.stack.addWidget(self.free_text)
        card.body.addWidget(self.stack, 1)

        self.btn_rec = widgets.button("Kaydı başlat", "player-record", "primary", tooltip="Enter")
        self.btn_rec.clicked.connect(self._toggle_record)
        self.btn_play = widgets.button("Dinle", "player-play", "light")
        self.btn_play.clicked.connect(self._play)
        self.btn_save = widgets.button("Kaydet ve sonraki", "device-floppy", "success", tooltip="Ctrl+Enter")
        self.btn_save.clicked.connect(self._save)
        self.btn_skip = widgets.button("Atla", "player-skip-forward", "light")
        self.btn_skip.clicked.connect(self._skip)
        self.btn_back = widgets.icon_button("chevron-left", "Önceki cümle", "light")
        self.btn_back.clicked.connect(self._back)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setFixedWidth(110)
        ctl = QHBoxLayout()
        ctl.setSpacing(8)
        for w in (self.btn_rec, self.btn_play, self.btn_save, self.btn_skip, self.btn_back):
            ctl.addWidget(w)
        ctl.addStretch()
        ctl.addWidget(self.level)
        card.body.addLayout(ctl)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        card.body.addWidget(self.status)
        root.addWidget(card, 1)

        self.totals = QLabel("")
        self.totals.setObjectName("muted")
        root.addWidget(self.totals)

        for keys, slot in ((QKeySequence(Qt.Key_Return), self._enter), (QKeySequence(Qt.Key_Enter), self._enter),
                           (QKeySequence("Ctrl+Return"), self._save)):
            # Yalnızca bu sayfa açıkken: yoksa Sözlük'te basılan Enter kayıt başlatırdı
            QShortcut(keys, self, activated=slot, context=Qt.WidgetWithChildrenShortcut)
        self._timer = QTimer(self, interval=100)
        self._timer.timeout.connect(self._tick)

    def _open_folder(self) -> None:
        OUT_ROOT.mkdir(parents=True, exist_ok=True)
        os.startfile(str(OUT_ROOT))  # noqa: S606 (yerel klasör)

    def _skip(self) -> None:
        self._advance(1)

    def _back(self) -> None:
        self._advance(-1)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        # Enter kısayolları sayfa içindeyken çalışır; metin kutusundaki odak korunur (Enter orada yeni satırdır)
        if not e.spontaneous() and self.focusWidget() is None:
            self.setFocus()

    # ------------------------------------------------ cümleler
    def _load_sentences(self, path: Path) -> None:
        try:
            lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        except OSError:
            lines = []
        self.sentences, self.sent_file = lines, path
        self.idx = int(self._state.get("index", {}).get(str(path), 0)) % max(1, len(lines))
        self._show_sentence()

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Cümle dosyası (satır başına bir cümle)", "", "Metin (*.txt)")
        if path:
            self._load_sentences(Path(path))
            self._save_state()

    def _show_sentence(self) -> None:
        if self.sentences:
            self.sentence.setText(self.sentences[self.idx])
            self.counter.setText(f"Cümle {self.idx + 1} / {len(self.sentences)}  ·  {self.sent_file.name}")
        else:
            self.sentence.setText("Cümle dosyası bulunamadı. 'Cümle dosyası…' ile bir .txt seçin.")

    def _advance(self, d: int) -> None:
        if self.sentences:
            self.idx = (self.idx + d) % len(self.sentences)
        self.pcm = None
        self.free_text.clear()
        self._show_sentence()
        self._set_status("")
        self._save_state()
        self._refresh()

    def _on_mode(self) -> None:
        self.stack.setCurrentIndex(self.mode.currentIndex())
        self._refresh()

    # ------------------------------------------------ kayıt
    def _ready(self) -> tuple[bool, str]:
        if not self.speaker.text().strip():
            return False, "Konuşmacı kodunu girin."
        if not self.consent.isChecked():
            return False, "Kayıt için konuşmacının KVKK açık rızası gerekli."
        _, _, busy = self.get_pipeline()
        if busy:
            return False, "Dikte açıkken kayıt yapılamaz."
        return True, ""

    def _enter(self) -> None:
        if self.mode.currentIndex() == 1 and self.free_text.hasFocus() and self._stream is None:
            self.free_text.insertPlainText("\n")  # serbest metin düzenlenirken Enter = yeni satır
            return
        self._toggle_record()

    def _toggle_record(self) -> None:
        import sounddevice as sd
        if self._stream is None:
            ok, why = self._ready()
            if not ok:
                self._set_status(why, theme.BAD)
                return
            self._chunks = []
            try:
                stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=self.get_device(),
                                        callback=lambda d, *_: self._chunks.append(d[:, 0].copy()))
                stream.start()
            except Exception as e:  # noqa: BLE001 (aygıt yok, meşgul ya da izin yok)
                self._set_status(f"{MIC_OPEN_ERROR} ({e})", theme.BAD)
                return
            self._stream = stream
            self._t0 = time.monotonic()
            self._timer.start()
            self.btn_rec.setText("Durdur")
            widgets.set_variant(self.btn_rec, "danger", icon="player-stop")
            self._set_status("Kaydediliyor…", theme.BAD)
        else:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            self._timer.stop()
            self.level.setValue(0)
            self.btn_rec.setText("Tekrar kaydet")
            widgets.set_variant(self.btn_rec, "primary", icon="player-record")
            self.pcm = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
            good, msg = quality(self.pcm)
            self._set_status(msg + ("" if good else " — tekrar kaydedin"), theme.GOOD if good else theme.BAD)
            if good and self.mode.currentIndex() == 1:
                self._transcribe()
        self._refresh()

    def _tick(self) -> None:
        last = self._chunks[-1] if self._chunks else np.zeros(1, np.float32)
        self.level.setValue(int(level_fraction(last) * 100))
        self._set_status(f"Kaydediliyor…  {time.monotonic() - self._t0:.0f} sn", theme.BAD)

    def _transcribe(self) -> None:
        engine, post, _ = self.get_pipeline()
        if engine is None:
            return
        pcm = self.pcm
        self.free_text.setPlainText("(metne çevriliyor…)")

        def work():
            raw = engine.transcribe(pcm, SR)
            self._sig.transcribed.emit(post(raw) if post else raw)
        threading.Thread(target=work, daemon=True).start()

    def _on_transcribed(self, text: str) -> None:
        self.free_text.setPlainText(text)
        self.free_text.setFocus()
        self._set_status("Metni söylediğiniz hâline göre düzeltin, sonra Ctrl+Enter ile kaydedin.", theme.WARN)

    def _play(self) -> None:
        import sounddevice as sd
        if self.pcm is not None and len(self.pcm):
            sd.stop()
            sd.play(self.pcm, SR)

    def _save(self) -> None:
        if self._stream is not None:
            self._toggle_record()
        if self.pcm is None:
            self._set_status("Önce kayıt yapın.", theme.BAD)
            return
        good, msg = quality(self.pcm)
        if not good:
            self._set_status(msg + " — kaydedilmedi", theme.BAD)
            return
        text = (self.free_text.toPlainText() if self.mode.currentIndex() == 1 else self.sentence.text()).strip()
        if not text or text.startswith("("):
            self._set_status("Metin boş — kaydedilmedi", theme.BAD)
            return
        spk = "".join(ch for ch in self.speaker.text().strip() if ch.isalnum() or ch in "-_")
        d = OUT_ROOT / spk
        d.mkdir(parents=True, exist_ok=True)
        stem = f"{spk}_{dt.datetime.now():%Y%m%d_%H%M%S}"
        wav = d / f"{stem}.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((np.clip(self.pcm, -1, 1) * 32767).astype(np.int16).tobytes())
        wav.with_suffix(".txt").write_text(text, encoding="utf-8")
        man = OUT_ROOT / "manifest.csv"
        new = not man.exists()
        with man.open("a", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            if new:
                wr.writerow(["konusmaci", "dosya", "metin", "sure_sn", "mod", "zaman", "kvkk_riza"])
            wr.writerow([spk, f"{spk}/{wav.name}", text, f"{len(self.pcm) / SR:.2f}",
                         self.mode.currentText(), dt.datetime.now().isoformat(timespec="seconds"), "evet"])
        self._set_status(f"Kaydedildi: {wav.name}", theme.GOOD)
        self._advance(1 if self.mode.currentIndex() == 0 else 0)
        self.btn_rec.setText("Kaydı başlat")

    # ------------------------------------------------ özet
    def _set_status(self, msg: str, color: str | None = None) -> None:
        self.status.setText(f"<span style='color:{color}'>{msg}</span>" if color else msg)

    def _refresh(self) -> None:
        ok, why = self._ready()
        self.btn_rec.setEnabled(ok or self._stream is not None)
        self.btn_save.setEnabled(self.pcm is not None)
        self.btn_play.setEnabled(self.pcm is not None)
        if not ok and self._stream is None and not self.status.text():
            self._set_status(why, theme.WARN)
        tot_n = tot_s = spk_n = spk_s = 0
        spk = self.speaker.text().strip()
        man = OUT_ROOT / "manifest.csv"
        if man.exists():
            with man.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    s = float(r.get("sure_sn") or 0)
                    tot_n, tot_s = tot_n + 1, tot_s + s
                    if r.get("konusmaci") == spk:
                        spk_n, spk_s = spk_n + 1, spk_s + s
        self.totals.setText(f"Bu konuşmacı: {spk_n} kayıt · {spk_s / 60:.1f} dk     "
                            f"Toplam: {tot_n} kayıt · {tot_s / 3600:.2f} sa (hedef: 20–50 sa)")

    def hideEvent(self, e) -> None:
        """Sayfadan çıkınca ya da pencere kapanınca kayıt durur; simge durumuna küçültmek kaydı durdurmaz."""
        if not e.spontaneous():
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
                self._timer.stop()
            # Eski pencerenin kapanmasıyla aynı: yarım kayıt atılır, rıza bir sonraki konuşmacı için yeniden istenir
            self._chunks = []
            self.pcm = None
            self.level.setValue(0)
            self.btn_rec.setText("Kaydı başlat")
            widgets.set_variant(self.btn_rec, "primary", icon="player-record")
            self._set_status("")
            self.consent.setChecked(False)
            self._refresh()
            self._save_state()
        super().hideEvent(e)
