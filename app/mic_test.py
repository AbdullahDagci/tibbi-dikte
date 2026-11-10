"""Ayarlar › Mikrofonu test et: seçili mikrofonla kısa kayıt, seviye çubuğu, düz cümleyle sonuç ve geri dinleme."""
from __future__ import annotations

import logging
import time
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from . import theme
from .audio import AudioPlayer, MicReport, analyze_recording, level_fraction
from .ui import widgets

log = logging.getLogger(__name__)

SR = 16000
TEST_SECONDS = 5
HINT = "Düğmeye basıp 5 saniye normal sesinizle bir cümle okuyun, ör. “Kalp boyutları normaldir, plevral efüzyon izlenmedi.”"
_COLOR = {"good": theme.GOOD, "noisy": theme.WARN, "quiet": theme.WARN}  # diğerleri: theme.BAD


class _Sig(QObject):
    play_ended = Signal()


class MicTestPanel(QWidget):
    def __init__(self, get_device: Callable[[], int | None], parent=None):
        super().__init__(parent)
        self._get_device = get_device
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._t0 = 0.0
        self.pcm: np.ndarray | None = None
        self.report: MicReport | None = None
        self._sig = _Sig()
        self._sig.play_ended.connect(self._play_ended)
        self.player = AudioPlayer(on_finished=self._sig.play_ended.emit)

        self.btn = widgets.button("Mikrofonu test et", "microphone", "light")
        self.btn.clicked.connect(self._toggle)
        self.btn_play = widgets.button("Kaydı dinle", "player-play", "light",
                                       tooltip="Programın mikrofondan duyduğu ses")
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_play.hide()
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(8)
        self.meter.hide()
        self.status = QLabel(HINT)
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self._timer = QTimer(self, interval=100)
        self._timer.timeout.connect(self._tick)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.btn)
        row.addWidget(self.btn_play)
        row.addStretch()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)
        lay.addLayout(row)
        lay.addWidget(self.meter)
        lay.addWidget(self.status)

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def _toggle(self) -> None:
        if self.recording:
            self._finish()
        else:
            self._start()

    def _start(self) -> None:
        import sounddevice as sd
        self.player.stop()
        self._sync_play()
        self._chunks = []
        try:
            stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=self._get_device(),
                                    callback=lambda d, *_: self._chunks.append(d[:, 0].copy()))
            stream.start()
        except Exception as e:  # noqa: BLE001 (aygıt yok, meşgul ya da izin yok)
            log.warning("Mikrofon testi açılamadı: %s", e)
            self._show(f"Mikrofon açılamadı: {e}. Mikrofon takılı mı, başka bir program (Teams, Zoom) "
                       "kullanıyor olabilir mi?", theme.BAD)
            return
        self._stream = stream
        self._t0 = time.monotonic()
        self.btn.setText("Durdur")
        widgets.set_variant(self.btn, "danger", icon="player-stop")
        self.btn_play.hide()
        self.meter.setValue(0)
        self.meter.show()
        self._timer.start()
        self._tick()

    def _tick(self) -> None:
        last = self._chunks[-1] if self._chunks else np.zeros(1, np.float32)
        self.meter.setValue(int(level_fraction(last) * 100))
        left = TEST_SECONDS - (time.monotonic() - self._t0)
        if left <= 0:
            self._finish()
            return
        self._show(f"Dinliyor… bir cümle okuyun ({left:.0f} sn)", theme.TEXT)

    def _finish(self) -> None:
        self._timer.stop()
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:  # noqa: BLE001
                log.warning("Mikrofon testi kapatılamadı: %s", e)
        self.btn.setText("Tekrar test et")
        widgets.set_variant(self.btn, "light", icon="microphone")
        self.meter.hide()
        self.pcm = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
        self.report = analyze_recording(self.pcm, SR)
        log.info("Mikrofon testi: %s (%s)", self.report.verdict, self.report.message)
        self._show(("✓ " if self.report.ok else "⚠ ") + self.report.message,
                   _COLOR.get(self.report.verdict, theme.BAD))
        if len(self.pcm):
            self.player.load(self.pcm, SR)
            self.btn_play.show()
            self._sync_play()

    def _toggle_play(self) -> None:
        if self.player.is_playing:
            self.player.stop()
        else:
            try:
                self.player.play()
            except Exception as e:  # noqa: BLE001 (hoparlör yok ya da meşgul)
                self._show(f"Ses çalınamadı: {e}", theme.BAD)
        self._sync_play()

    def _play_ended(self) -> None:
        self.player.finish()
        self._sync_play()

    def _sync_play(self) -> None:
        playing = self.player.is_playing
        self.btn_play.setText("Durdur" if playing else "Kaydı dinle")
        widgets.set_variant(self.btn_play, "light", icon="player-stop" if playing else "player-play")

    def _show(self, text: str, color: str) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color};")

    def stop(self) -> None:
        """Sayfadan çıkılınca kayıt ve çalma durur."""
        if self.recording:
            self._finish()
        self.player.stop()
        self._sync_play()

    def hideEvent(self, event) -> None:
        # kapanışta düğmeler önce silinebilir: yalnız kayıt ya da çalma sürüyorsa dokunulur
        if not event.spontaneous() and (self.recording or self.player.is_playing):
            self.stop()
        super().hideEvent(event)
