"""Test ekranı için ses dosyası okuma: önce soundfile (wav, flac, mp3, ogg), onun açamadıkları (mp4, m4a…) Qt ile."""
from __future__ import annotations

from pathlib import Path

import numpy as np

QT_SAMPLE_RATE = 16000  # modellerin örnekleme hızı
_STALL_MS = 30_000  # bu kadar süre yeni veri gelmezse çözme takılmış sayılır


def load_audio(path: str | Path) -> tuple[np.ndarray, int]:
    """(tek kanal float32 ses, örnekleme hızı) döndürür; okunamazsa RuntimeError yükseltir."""
    import soundfile as sf
    try:
        audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except sf.LibsndfileError:
        return _decode_with_qt(path), QT_SAMPLE_RATE
    return audio.mean(axis=1), sr


def _decode_with_qt(path: str | Path) -> np.ndarray:
    """QAudioDecoder (Qt'nin FFmpeg arka ucu) ile 16 kHz tek kanala çözer; çalışan bir Qt uygulaması gerekir."""
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat

    fmt = QAudioFormat()
    fmt.setSampleRate(QT_SAMPLE_RATE)
    fmt.setChannelCount(1)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
    decoder = QAudioDecoder()
    decoder.setAudioFormat(fmt)
    decoder.setSource(QUrl.fromLocalFile(str(path)))

    chunks: list[np.ndarray] = []
    failure: list[str] = []
    finished: list[bool] = []
    loop = QEventLoop()
    stall = QTimer(singleShot=True, interval=_STALL_MS)

    def finish() -> None:
        finished.append(True)
        loop.quit()

    def on_buffer() -> None:
        stall.start()
        buffer = decoder.read()
        if buffer.isValid():
            chunks.append(np.frombuffer(bytes(buffer.constData()), dtype=np.float32))

    def on_error(*_) -> None:
        failure.append(decoder.errorString() or "ses çözülemedi")
        finish()

    def on_stall() -> None:
        failure.append("ses çözme zaman aşımına uğradı")
        finish()

    decoder.bufferReady.connect(on_buffer)
    decoder.finished.connect(finish)
    decoder.error.connect(on_error)
    stall.timeout.connect(on_stall)
    stall.start()
    decoder.start()
    if not finished:  # hata start() içinde de gelebilir; o durumda döngüye girilmez
        loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    stall.stop()
    decoder.stop()

    if failure:
        raise RuntimeError(failure[0])
    if not chunks:
        raise RuntimeError("dosyada ses bulunamadı")
    return np.concatenate(chunks)
