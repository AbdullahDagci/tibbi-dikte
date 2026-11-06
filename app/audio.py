"""Mikrofon yakalama: float32 mono, modelin örnekleme hızında, kuyruğa parça parça."""
import logging
import queue
import threading

import numpy as np
import sounddevice as sd


log = logging.getLogger(__name__)


def beep_tone(cfg, stopping: bool) -> tuple[int, int] | None:
    """(frekans Hz, süre ms); bip kapalıysa None. Elle bozulan ayar Windows'un kabul ettiği aralığa çekilir."""
    if not cfg.beep_enabled:
        return None
    hz = cfg.beep_stop_hz if stopping else cfg.beep_start_hz
    return min(max(int(hz), 37), 32767), max(int(cfg.beep_ms), 1)


def play_tone(hz: int, ms: int) -> None:
    """Bip sesini arka planda çalar; dikteyi ve arayüzü bekletmez."""
    try:
        import winsound
        threading.Thread(target=winsound.Beep, args=(hz, ms), daemon=True).start()
    except Exception:  # noqa: BLE001 (Windows dışı ortam: ses yok, dikte sürer)
        pass


def list_input_devices() -> list[tuple[int, str]]:
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append((i, d["name"]))
    return out


class AudioPlayer:
    """Bellekteki sesi çalar; duraklatılınca yerini korur, play() kaldığı yerden sürdürür.

    on_finished ses bitince PortAudio iş parçacığından çağrılır ve akış orada kapatılamaz:
    alıcı ana iş parçacığına geçip finish() çağırmalıdır.
    """

    def __init__(self, on_finished=None):
        self._on_finished = on_finished
        self._audio: np.ndarray | None = None
        self._sr = 16000
        self._pos = 0
        self._stream: sd.OutputStream | None = None
        self._ended = False

    @property
    def is_playing(self) -> bool:
        return self._stream is not None

    @property
    def is_paused(self) -> bool:
        return self._stream is None and self._pos > 0

    def load(self, audio: np.ndarray, sample_rate: int) -> None:
        self.stop()
        self._audio, self._sr = audio, sample_rate

    def play(self) -> None:
        if self._audio is None or self._stream is not None:
            return
        stream = sd.OutputStream(samplerate=self._sr, channels=1, dtype="float32",
                                 callback=self._fill, finished_callback=self._stream_finished)
        try:
            stream.start()
        except Exception:
            stream.close()
            raise
        self._stream = stream

    def pause(self) -> None:
        if self._stream is None:
            return
        unplayed = int(self._stream.latency * self._sr)  # aygıt tamponundaki ses kesilince kaybolur, tekrar çalınsın
        self._close_stream()
        self._pos = max(0, self._pos - unplayed)

    def stop(self) -> None:
        self._close_stream()
        self._pos = 0

    def finish(self) -> None:
        """Ses bittiyse akışı kapatıp başa döner; arada duraklatıldıysa dokunmaz."""
        if self._ended:
            self.stop()

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        self._ended = False
        if stream is None:
            return
        try:
            stream.abort()
            stream.close()
        except sd.PortAudioError as e:
            log.warning("ses akışı kapatılamadı: %s", e)

    def _fill(self, outdata, frames, time, status):  # noqa: ARG002
        if status:
            log.warning("ses çıkışı: %s", status)
        chunk = self._audio[self._pos:self._pos + frames]
        outdata[:len(chunk), 0] = chunk
        outdata[len(chunk):, 0] = 0
        self._pos += len(chunk)
        if len(chunk) < frames:
            self._ended = True
            raise sd.CallbackStop

    def _stream_finished(self) -> None:
        if self._ended and self._on_finished is not None:
            self._on_finished()


class Microphone:
    def __init__(self, sample_rate: int = 16000, device: int | None = None, block_ms: int = 100):
        self.sample_rate = sample_rate
        self.device = device
        self.blocksize = int(sample_rate * block_ms / 1000)
        self.q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream: sd.InputStream | None = None

    def _cb(self, indata, frames, time, status):  # noqa: ARG002
        if status:  # ör. input overflow: ses kartı verisi zamanında alınamadı, ses parçası kayboldu
            log.warning("mikrofon: %s", status)
        self.q.put(indata[:, 0].copy())

    def start(self) -> None:
        while not self.q.empty():
            self.q.get_nowait()
        self._stream = sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32",
                                      blocksize=self.blocksize, device=self.device, callback=self._cb)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read(self, timeout: float = 0.2) -> np.ndarray | None:
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None
