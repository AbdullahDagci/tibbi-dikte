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
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QSizePolicy, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from . import theme
from .audio import MIC_OPEN_ERROR, AudioPlayer, analyze_recording, level_fraction
from .audio_file import load_audio
from .medical.postprocess import read_lexicon, tr_lower
from .scoring import Score, score
from .ui import widgets

AUDIO_FILTER = "Ses ve video dosyaları (*.wav *.flac *.mp3 *.ogg *.opus *.m4a *.mp4);;Tüm dosyalar (*.*)"


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    play_ended = Signal()


class TestPage(QWidget):
    __test__ = False  # pytest bunu test sınıfı sanmasın

    def __init__(self, get_pipeline: Callable[[], tuple], term_files: list[Path], parent=None,
                 get_device: Callable[[], int | None] = lambda: None):
        """get_pipeline() -> (engine, postprocessor, meşgul_mu: bool). get_device() -> Ayarlar'da seçili mikrofon."""
        super().__init__(parent)
        self.setObjectName("page")
        self.get_pipeline = get_pipeline
        self.get_device = get_device
        self._term_files = term_files
        self._load_terms()
        self.audio: np.ndarray | None = None
        self.sr = 16000
        self.audio_name = ""
        self._rec_stream = None
        self._rec_chunks: list[np.ndarray] = []
        self._sig = _Signals()
        self._sig.done.connect(self._show_result)
        self._sig.failed.connect(self._show_error)
        self._sig.play_ended.connect(self._play_ended)
        self.player = AudioPlayer(on_finished=self._sig.play_ended.emit)
        self._build()

    def _load_terms(self) -> None:
        self.terms = {tr_lower(t) for f in self._term_files for t in read_lexicon(f) if " " not in t and len(t) >= 6}

    # ------------------------------------------------ arayüz
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        self.btn_open = widgets.button("Dosya seç", "folder-open", "primary")
        self.btn_open.clicked.connect(self._open)
        self.btn_rec = widgets.button("Mikrofonla kaydet", "microphone", "info")
        self.btn_rec.clicked.connect(self._toggle_record)
        self.btn_play = widgets.button("Dinle", "player-play", "light")
        self.btn_play.clicked.connect(self._play)
        self.btn_pause = widgets.button("Duraklat", "player-pause", "light")
        self.btn_pause.clicked.connect(self._pause)
        self.btn_stop = widgets.button("Durdur", "player-stop", "light")
        self.btn_stop.clicked.connect(self._stop)
        self._sync_player()
        self.file_label = QLabel("Ses seçilmedi")
        self.file_label.setObjectName("muted")
        self.file_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # uzun ad pencereyi genişletmesin
        self.rec_level = QProgressBar()
        self.rec_level.setRange(0, 100)
        self.rec_level.setFixedWidth(120)
        self.rec_level.setTextVisible(False)
        self.rec_level.hide()
        row = QHBoxLayout()
        row.setSpacing(8)
        for w in (self.btn_open, self.btn_rec, self.btn_play, self.btn_pause, self.btn_stop):
            row.addWidget(w)
        row.addSpacing(6)
        row.addWidget(self.file_label, 1)
        row.addWidget(self.rec_level)

        self.reference = QPlainTextEdit()
        self.reference.setPlaceholderText("Referans (doğru) metin, isteğe bağlı")
        self.reference.setFixedHeight(76)

        self.cb_post = widgets.Switch()
        self.cb_post.setChecked(True)
        self.btn_run = widgets.button("Çözümle ve puanla", "wand", "success")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._run)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(160)
        self.progress.hide()
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("Tıbbi sonişleme"))
        row2.addWidget(widgets.InfoTip("Açıkken uygulamanın gerçekte yazacağı metin puanlanır. Ses dosyasıyla aynı adlı "
                                       ".txt dosyası varsa referans olarak otomatik yüklenir."))
        row2.addWidget(self.cb_post)
        row2.addStretch()
        row2.addWidget(self.progress)
        row2.addWidget(self.btn_run)

        source = widgets.Card()
        source.body.addLayout(row)
        source.body.addWidget(self.reference)
        source.body.addLayout(row2)
        root.addWidget(source)

        self.c_acc = widgets.StatTile("Kelime doğruluğu", "circle-check")
        self.c_wer = widgets.StatTile("Kelime hata oranı", "alert-triangle")
        self.c_cer = widgets.StatTile("Karakter hata oranı", "table")
        self.c_term = widgets.StatTile("Terim isabeti", "stethoscope")
        self.c_speed = widgets.StatTile("Hız", "cpu")
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        for tile in (self.c_acc, self.c_wer, self.c_cer, self.c_term, self.c_speed):
            tiles.addWidget(tile, 1)
        root.addLayout(tiles)

        self.tabs = QTabWidget()
        self.diff = QTextBrowser()
        self.out_post = QPlainTextEdit()
        self.out_post.setReadOnly(True)
        self.out_raw = QPlainTextEdit()
        self.out_raw.setReadOnly(True)
        self.tabs.addTab(self.diff, "Karşılaştırma")
        self.tabs.addTab(self.out_post, "Uygulamanın yazacağı metin")
        self.tabs.addTab(self.out_raw, "Ham model çıktısı")

        legend = QLabel(
            f"<span style='color:{theme.TEXT}'>doğru</span> &nbsp;·&nbsp; "
            f"<span style='color:{theme.BAD}'><b>yanlış</b></span> "
            f"<span style='color:{theme.MUTED}'><s>referans</s></span> &nbsp;·&nbsp; "
            f"<span style='background:{theme.DANGER_LIGHT};color:{theme.BAD}'><s>&nbsp;eksik&nbsp;</s></span> &nbsp;·&nbsp; "
            f"<span style='background:{theme.WARNING_LIGHT};color:{theme.WARN}'>&nbsp;fazla&nbsp;</span>")
        legend.setObjectName("muted")
        self.missed = QLabel("")
        self.missed.setObjectName("muted")
        self.missed.setWordWrap(True)
        copy = widgets.button("Metni kopyala", "copy", "light")
        copy.clicked.connect(self._copy_output)
        bottom = QHBoxLayout()
        bottom.addWidget(legend)
        bottom.addWidget(widgets.InfoTip("Karşılaştırmada sayı ve birimler okunuşuna çevrilir: 6 mm = altı milimetre."))
        bottom.addWidget(self.missed, 1)
        bottom.addWidget(copy)

        result = widgets.Card()
        result.body.addWidget(self.tabs, 1)
        result.body.addLayout(bottom)
        root.addWidget(result, 1)

    def _copy_output(self) -> None:
        QGuiApplication.clipboard().setText(self.out_post.toPlainText())

    # ------------------------------------------------ ses
    def _set_audio(self, audio: np.ndarray, sr: int, name: str) -> None:
        self.audio, self.sr, self.audio_name = audio.astype(np.float32), sr, name
        self.player.load(self.audio, sr)
        self._set_file_label(f"{name}  ·  {len(audio) / sr:.1f} sn  ·  {sr // 1000} kHz")
        self._sync_player()
        self.btn_run.setEnabled(True)

    def _set_file_label(self, text: str) -> None:
        self.file_label.setText(text)
        self.file_label.setToolTip(text)

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ses dosyası seç", "", AUDIO_FILTER)
        if not path:
            return
        try:
            audio, sr = load_audio(path)
        except Exception as e:  # noqa: BLE001
            self._show_error(f"Ses dosyası okunamadı: {e}")
            return
        self._set_audio(audio, sr, Path(path).name)
        txt = Path(path).with_suffix(".txt")
        if txt.exists() and not self.reference.toPlainText().strip():
            self.reference.setPlainText(txt.read_text(encoding="utf-8").strip())

    def _toggle_record(self) -> None:
        import sounddevice as sd
        if self._rec_stream is None:
            self._rec_chunks = []
            def cb(indata, *_):
                self._rec_chunks.append(indata[:, 0].copy())
            try:  # dikte hangi mikrofonu kullanıyorsa test de onu kullanır
                stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32", device=self.get_device(),
                                        callback=cb)
                stream.start()
            except Exception as e:  # noqa: BLE001 (aygıt yok, meşgul ya da izin yok)
                self._show_error(f"{MIC_OPEN_ERROR} ({e})")
                return
            self._rec_stream = stream
            self.player.stop()  # hoparlörden çıkan ses kayda girmesin
            self._sync_player()
            self._rec_t0 = time.monotonic()
            self.btn_rec.setText("Kaydı durdur")
            widgets.set_variant(self.btn_rec, "danger", icon="player-stop")
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
            self.btn_rec.setText("Mikrofonla kaydet")
            widgets.set_variant(self.btn_rec, "info", icon="microphone")
            self._sync_player()
            if self._rec_chunks:
                pcm = np.concatenate(self._rec_chunks)
                self._set_audio(pcm, 16000, "Mikrofon kaydı")
                report = analyze_recording(pcm, 16000)  # sonuç kötüyse önce mikrofona bakılmalı, modele değil
                if not report.ok:
                    self._set_file_label(f"Mikrofon kaydı  ·  ⚠ {report.message}")

    def _rec_tick(self) -> None:
        last = self._rec_chunks[-1] if self._rec_chunks else np.zeros(1, np.float32)
        self.rec_level.setValue(int(level_fraction(last) * 100))
        self.file_label.setText(f"Kaydediliyor…  {time.monotonic() - self._rec_t0:.0f} sn")

    def _play(self) -> None:
        try:
            self.player.play()
        except Exception as e:  # noqa: BLE001 (ses aygıtı yok ya da meşgul)
            self._set_file_label(f"Ses çalınamadı: {e}")
        self._sync_player()

    def _pause(self) -> None:
        self.player.pause()
        self._sync_player()

    def _stop(self) -> None:
        self.player.stop()
        self._sync_player()

    def _play_ended(self) -> None:
        self.player.finish()
        self._sync_player()

    def _sync_player(self) -> None:
        playing, paused = self.player.is_playing, self.player.is_paused
        self.btn_play.setEnabled(self.audio is not None and not playing and self._rec_stream is None)
        self.btn_play.setText("Devam et" if paused else "Dinle")
        self.btn_pause.setEnabled(playing)
        self.btn_stop.setEnabled(playing or paused)

    # ------------------------------------------------ çözümleme
    def _run(self) -> None:
        self._load_terms()  # sözlüğe yeni eklenen terimler de sayılsın
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
        self.c_speed.set(f"{1 / max(rtf, 1e-6):.0f}×", f"gerçek zaman · {r['duration']:.1f} sn ses → {r['elapsed']:.1f} sn",
                         theme.GOOD if rtf < 0.5 else theme.WARN)
        s: Score | None = r.get("score")
        if s is None:
            for c in (self.c_acc, self.c_wer, self.c_cer, self.c_term):
                c.set("—", "referans yok")
            self.diff.setHtml(f"<p style='color:{theme.MUTED}'>Referans metin girilmedi; yalnızca çıktı gösteriliyor.</p>"
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
                parts.append(f"<span style='color:{theme.MUTED}'><s>{html.escape(a.ref)}</s></span>&nbsp;"
                             f"<span style='color:{theme.BAD}'><b>{html.escape(a.hyp)}</b></span>")
            elif a.op == "del":
                parts.append(f"<span style='background:{theme.DANGER_LIGHT};color:{theme.BAD}'><s>&nbsp;{html.escape(a.ref)}&nbsp;</s></span>")
            else:
                parts.append(f"<span style='background:{theme.WARNING_LIGHT};color:{theme.WARN}'>&nbsp;{html.escape(a.hyp)}&nbsp;</span>")
        return f"<div style='font-size:12.5pt; line-height:170%'>{' '.join(parts)}</div>"

    def hideEvent(self, e) -> None:
        """Sayfadan çıkınca ya da pencere kapanınca kayıt durur, ses duraklar; simge durumuna küçültmek bunları etkilemez."""
        if not e.spontaneous():
            if self._rec_stream is not None:
                self._toggle_record()
            self._pause()
        super().hideEvent(e)
