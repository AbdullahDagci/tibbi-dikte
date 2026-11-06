"""Test ekranı ses okuma: soundfile'ın açamadığı mp4/AAC dosyaları Qt çözücüsüyle okunur.

Sınama dosyaları tests/audio altında (ffmpeg ile üretildi):
  tone_440hz.mp4      1 sn, 440 Hz, AAC, 48 kHz tek kanal
  video_no_audio.mp4  1 sn, yalnızca görüntü
"""
import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import soundfile as sf  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from app.audio_file import load_audio  # noqa: E402
from app import testbench  # noqa: E402

AUDIO = Path(__file__).resolve().parent / "audio"
TONE = AUDIO / "tone_440hz.mp4"
NO_AUDIO = AUDIO / "video_no_audio.mp4"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _dominant_hz(audio: np.ndarray, sr: int) -> float:
    return float(np.argmax(np.abs(np.fft.rfft(audio))) * sr / len(audio))


def test_reads_aac_audio_from_mp4(qapp):
    audio, sr = load_audio(TONE)
    assert sr == 16000
    assert audio.dtype == np.float32 and audio.ndim == 1
    assert len(audio) / sr == pytest.approx(1.0, abs=0.1)
    assert _dominant_hz(audio, sr) == pytest.approx(440, abs=5)


def test_reads_mp4_from_path_with_turkish_letters_and_spaces(qapp, tmp_path):
    target = tmp_path / "Çekim Raporu ğüşİ.mp4"
    shutil.copy(TONE, target)
    audio, sr = load_audio(target)
    assert len(audio) / sr == pytest.approx(1.0, abs=0.1)


def test_wav_keeps_its_sample_rate_and_is_mixed_to_mono(qapp, tmp_path):
    path = tmp_path / "stereo.wav"
    stereo = np.column_stack([np.full(4410, 0.5), np.zeros(4410)])
    sf.write(path, stereo, 44100)
    audio, sr = load_audio(path)
    assert sr == 44100
    assert audio.shape == (4410,)
    assert audio[0] == pytest.approx(0.25, abs=1e-3)


def test_corrupt_file_raises_instead_of_hanging(qapp, tmp_path):
    path = tmp_path / "bozuk.mp4"
    path.write_bytes(b"bu bir video degil" * 100)
    with pytest.raises(RuntimeError):
        load_audio(path)


def test_video_without_audio_track_raises(qapp):
    with pytest.raises(RuntimeError):
        load_audio(NO_AUDIO)


def test_file_dialog_lists_mp4():
    assert "*.mp4" in testbench.AUDIO_FILTER.split(";;")[0]


@pytest.fixture
def window(qapp):
    """Uygulamadaki gibi açıkça silinir: kapatılmadan çöpe düşen pencere süreci kapanışta düşürür."""
    win = testbench.TestPage(lambda: (None, None, False), [])
    yield win
    win.close()
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


def test_test_window_opens_mp4_and_enables_run(window, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(TONE), ""))
    window._open()
    assert window.audio is not None and len(window.audio) / window.sr == pytest.approx(1.0, abs=0.1)
    assert window.btn_run.isEnabled()
    assert "tone_440hz.mp4" in window.file_label.text()


def test_test_window_shows_error_for_video_without_audio(window, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(NO_AUDIO), ""))
    window._open()
    assert window.audio is None
    assert not window.btn_run.isEnabled()
    assert "okunamadı" in window.diff.toPlainText()
