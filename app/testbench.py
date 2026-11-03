"""Test ve doğruluk ekranı: ses dosyası seç (veya mikrofonla kaydet) -> model çıktısı -> referansla karşılaştır.

Kartlar: kelime doğruluğu (1-WER), WER, CER, tıbbi terim isabeti, hız (RTF).
Fark görünümü: doğru / yanlış (üstü çizili referans + kırmızı çıktı) / eksik / fazla kelimeler.
"""
from __future__ import annotations

import html
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
                               QProgressBar, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from . import theme
from .medical.postprocess import read_lexicon, tr_lower
from .scoring import Score, score

AUDIO_FILTER = "Ses dosyaları (*.wav *.flac *.mp3 *.ogg *.opus *.m4a);;Tüm dosyalar (*.*)"


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Card(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)
        t = QLabel(title.upper())
        t.setObjectName("cardTitle")
        self.value = QLabel("—")
        self.value.setObjectName("cardValue")
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        for w in (t, self.value, self.sub):
            v.addWidget(w)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color:{color}" if color else "")
        self.sub.setText(sub)


class TestWindow(QDialog):
    def __init__(self, get_pipeline: Callable[[], tuple], term_files: list[Path], parent=None):
        """get_pipeline() -> (engine, postprocessor, meşgul_mu: bool)."""
        super().__init__(parent)
        self.get_pipeline = get_pipeline
        self.terms = {tr_lower(t) for f in term_files for t in read_lexicon(f) if " " not in t and len(t) >= 6}
        self.audio: np.ndarray | None = None
        self.sr = 16000
        self.audio_name = ""
        self._rec_stream = None
        self._rec_chunks: list[np.ndarray] = []
        self._sig = _Signals()
        self._sig.done.connect(self._show_result)
        self._sig.failed.connect(self._show_error)
        self.setWindowTitle("Tıbbi Dikte — Test ve Doğruluk")
        self.resize(980, 760)
        self._build()

    # ------------------------------------------------ arayüz
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        h1 = QLabel("Test ve Doğruluk")
        h1.setObjectName("h1")
        sub = QLabel("Bir ses dosyası seçin ya da mikrofonla kaydedin. Doğru metni (referans) girerseniz "
                     "doğruluk oranı ve kelime kelime fark gösterilir.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        root.addWidget(h1)
        root.addWidget(sub)

        row = QHBoxLayout()
        self.btn_open = QPushButton("Ses dosyası seç…")
        self.btn_open.clicked.connect(self._open)
        self.btn_rec = QPushButton("●  Mikrofonla kaydet")
        self.btn_rec.clicked.connect(self._toggle_record)
        self.btn_play = QPushButton("▶  Dinle")
        self.btn_play.clicked.connect(self._play)
        self.btn_play.setEnabled(False)
        self.file_label = QLabel("Ses seçilmedi")
        self.file_label.setObjectName("muted")
        self.rec_level = QProgressBar()
        self.rec_level.setRange(0, 100)
        self.rec_level.setFixedWidth(120)
        self.rec_level.setTextVisible(False)
        self.rec_level.hide()
        for w in (self.btn_open, self.btn_rec, self.btn_play):
            row.addWidget(w)
        row.addSpacing(8)
        row.addWidget(self.file_label, 1)
        row.addWidget(self.rec_level)
        root.addLayout(row)

        self.reference = QPlainTextEdit()
        self.reference.setPlaceholderText("Referans (doğru) metin — isteğe bağlı. Ses dosyasıyla aynı adlı .txt "
                                          "dosyası varsa otomatik yüklenir. Kayıt yapacaksanız önce metni yazıp "
                                          "sonra okuyun.")
        self.reference.setFixedHeight(90)
        root.addWidget(self.reference)

        row2 = QHBoxLayout()
        self.cb_post = QCheckBox("Tıbbi sonişlemeyi uygula (uygulamanın gerçekte yazacağı metin)")
        self.cb_post.setChecked(True)
        self.btn_run = QPushButton("Çözümle ve puanla")
        self.btn_run.setObjectName("primary")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._run)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(160)
        self.progress.hide()
        row2.addWidget(self.cb_post, 1)
        row2.addWidget(self.progress)
        row2.addWidget(self.btn_run)
        root.addLayout(row2)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.c_acc = Card("Kelime doğruluğu")
        self.c_wer = Card("Kelime hata oranı (WER)")
        self.c_cer = Card("Karakter hata oranı (CER)")
        self.c_term = Card("Tıbbi terim isabeti")
        self.c_speed = Card("Hız")
        for c in (self.c_acc, self.c_wer, self.c_cer, self.c_term, self.c_speed):
            cards.addWidget(c, 1)
        root.addLayout(cards)

        legend = QLabel(
            f"<span style='color:#1F2430'>doğru</span> &nbsp;·&nbsp; "
            f"<span style='color:{theme.BAD}'><b>yanlış</b></span> "
            f"<span style='color:#98A1B2'><s>referans</s></span> &nbsp;·&nbsp; "
            f"<span style='background:#FDECEC;color:{theme.BAD}'><s>&nbsp;eksik&nbsp;</s></span> &nbsp;·&nbsp; "
            f"<span style='background:#FFF4DB;color:{theme.WARN}'>&nbsp;fazla&nbsp;</span>"
            "&nbsp;&nbsp;&nbsp;<i>(karşılaştırmada sayı ve birimler okunuşuna çevrilir: 6 mm = altı milimetre)</i>")
        legend.setObjectName("muted")
        root.addWidget(legend)

        self.tabs = QTabWidget()
        self.diff = QTextBrowser()
        self.out_post = QPlainTextEdit()
        self.out_post.setReadOnly(True)
        self.out_raw = QPlainTextEdit()
        self.out_raw.setReadOnly(True)
        self.tabs.addTab(self.diff, "Karşılaştırma")
        self.tabs.addTab(self.out_post, "Uygulamanın yazacağı metin")
        self.tabs.addTab(self.out_raw, "Ham model çıktısı")
        root.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.missed = QLabel("")
        self.missed.setObjectName("muted")
        self.missed.setWordWrap(True)
        copy = QPushButton("Metni kopyala")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.out_post.toPlainText()))
        bottom.addWidget(self.missed, 1)
        bottom.addWidget(copy)
        root.addLayout(bottom)

    # ------------------------------------------------ ses
    def _set_audio(self, audio: np.ndarray, sr: int, name: str) -> None:
        self.audio, self.sr, self.audio_name = audio.astype(np.float32), sr, name
        self.file_label.setText(f"{name}  ·  {len(audio) / sr:.1f} sn  ·  {sr // 1000} kHz")
        self.btn_play.setEnabled(True)
        self.btn_run.setEnabled(True)

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ses dosyası seç", "", AUDIO_FILTER)
        if not path:
            return
        try:
            import soundfile as sf
            audio, sr = sf.read(path, dtype="float32", always_2d=True)
        except Exception as e:  # noqa: BLE001
            self._show_error(f"Ses dosyası okunamadı: {e}")
            return
        self._set_audio(audio.mean(axis=1), sr, Path(path).name)
        txt = Path(path).with_suffix(".txt")
        if txt.exists() and not self.reference.toPlainText().strip():
            self.reference.setPlainText(txt.read_text(encoding="utf-8").strip())

    def _toggle_record(self) -> None:
        import sounddevice as sd
        if self._rec_stream is None:
            self._rec_chunks = []
            def cb(indata, *_):
                self._rec_chunks.append(indata[:, 0].copy())
            self._rec_stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32", callback=cb)
            self._rec_stream.start()
            self._rec_t0 = time.monotonic()
            self.btn_rec.setText("■  Kaydı durdur")
            self.btn_rec.setObjectName("danger")
            self.btn_rec.setStyle(self.btn_rec.style())
            self.rec_level.show()
            self._rec_timer = QTimer(self, interval=100)
            self._rec_timer.timeout.connect(self._rec_tick)
            self._rec_timer.start()
        else:
            self._rec_stream.stop()
            self._rec_stream.close()
            self._rec_stream = None
            self._rec_timer.stop()
            self.rec_level.hide()
            self.btn_rec.setText("●  Mikrofonla kaydet")
            self.btn_rec.setObjectName("")
            self.btn_rec.setStyle(self.btn_rec.style())
            if self._rec_chunks:
                self._set_audio(np.concatenate(self._rec_chunks), 16000, "Mikrofon kaydı")

    def _rec_tick(self) -> None:
        last = self._rec_chunks[-1] if self._rec_chunks else np.zeros(1, np.float32)
        rms = float(np.sqrt(np.mean(last ** 2)))
        self.rec_level.setValue(int(max(0, min(100, (20 * np.log10(rms + 1e-9) + 55) / 40 * 100))))
        self.file_label.setText(f"Kaydediliyor…  {time.monotonic() - self._rec_t0:.0f} sn")

    def _play(self) -> None:
        import sounddevice as sd
        if self.audio is not None:
            sd.stop()
            sd.play(self.audio, self.sr)

    # ------------------------------------------------ çözümleme
    def _run(self) -> None:
        engine, post, busy = self.get_pipeline()
        if engine is None:
            self._show_error("Model henüz yüklenmedi. Birkaç saniye sonra tekrar deneyin.")
            return
        if busy:
            self._show_error("Dikte açıkken test yapılamaz. Önce dikteyi durdurun.")
            return
        self.btn_run.setEnabled(False)
        self.progress.show()
        audio, sr, ref, use_post = self.audio, self.sr, self.reference.toPlainText().strip(), self.cb_post.isChecked()

        def work():
            try:
                t0 = time.monotonic()
                raw = engine.transcribe(audio, sr)
                elapsed = time.monotonic() - t0
                final = post(raw) if (post and use_post) else raw
                result = {"raw": raw, "final": final, "elapsed": elapsed, "duration": len(audio) / sr}
                if ref:
                    result["score"] = score(ref, final, self.terms)
                    result["score_raw"] = score(ref, raw, self.terms)
                self._sig.done.emit(result)
            except Exception as e:  # noqa: BLE001
                self._sig.failed.emit(f"Çözümleme hatası: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _show_error(self, msg: str) -> None:
        self.progress.hide()
        self.btn_run.setEnabled(self.audio is not None)
        self.diff.setHtml(f"<p style='color:{theme.BAD}'>{html.escape(msg)}</p>")
        self.tabs.setCurrentIndex(0)

    def _show_result(self, r: dict) -> None:
        self.progress.hide()
        self.btn_run.setEnabled(True)
        self.out_post.setPlainText(r["final"])
        self.out_raw.setPlainText(r["raw"])
        rtf = r["elapsed"] / max(r["duration"], 1e-6)
        self.c_speed.set(f"{1 / max(rtf, 1e-6):.0f}× gerçek zaman", f"{r['duration']:.1f} sn ses → {r['elapsed']:.1f} sn",
                         theme.GOOD if rtf < 0.5 else theme.WARN)
        s: Score | None = r.get("score")
        if s is None:
            for c in (self.c_acc, self.c_wer, self.c_cer, self.c_term):
                c.set("—", "referans yok")
            self.diff.setHtml("<p style='color:#6B7486'>Referans metin girilmedi; yalnızca çıktı gösteriliyor.</p>"
                              f"<p style='font-size:12pt'>{html.escape(r['final'])}</p>")
            self.missed.setText("")
            return
        raw_s: Score = r["score_raw"]
        self.c_acc.set(f"%{s.accuracy * 100:.1f}", f"ham model: %{raw_s.accuracy * 100:.1f}", theme.grade_color(s.accuracy))
        self.c_wer.set(f"%{s.wer * 100:.1f}", f"{s.substitutions} yanlış · {s.deletions} eksik · {s.insertions} fazla",
                       theme.grade_color(1 - s.wer))
        self.c_cer.set(f"%{s.cer * 100:.1f}", f"{s.ref_words} referans kelime", theme.grade_color(1 - s.cer, 0.95, 0.85))
        if s.term_total:
            ta = s.term_accuracy
            self.c_term.set(f"%{ta * 100:.0f}", f"{s.term_hits}/{s.term_total} terim", theme.grade_color(ta))
        else:
            self.c_term.set("—", "metinde sözlük terimi yok")
        self.diff.setHtml(self._diff_html(s))
        self.missed.setText(("Kaçırılan terimler: " + ", ".join(dict.fromkeys(s.missed_terms))) if s.missed_terms else "")
        self.tabs.setCurrentIndex(0)

    @staticmethod
    def _diff_html(s: Score) -> str:
        parts = []
        for a in s.alignment:
            if a.op == "ok":
                parts.append(html.escape(a.hyp))
            elif a.op == "sub":
                parts.append(f"<span style='color:#98A1B2'><s>{html.escape(a.ref)}</s></span>&nbsp;"
                             f"<span style='color:{theme.BAD}'><b>{html.escape(a.hyp)}</b></span>")
            elif a.op == "del":
                parts.append(f"<span style='background:#FDECEC;color:{theme.BAD}'><s>&nbsp;{html.escape(a.ref)}&nbsp;</s></span>")
            else:
                parts.append(f"<span style='background:#FFF4DB;color:{theme.WARN}'>&nbsp;{html.escape(a.hyp)}&nbsp;</span>")
        return f"<div style='font-size:12.5pt; line-height:170%'>{' '.join(parts)}</div>"

    def closeEvent(self, e) -> None:
        if self._rec_stream is not None:
            self._toggle_record()
        super().closeEvent(e)
