"""Mikrofon yakalama: float32 mono, modelin örnekleme hızında, kuyruğa parça parça.

Mikrofon sorunlarının tespiti de buradadır: kısa kayıt testi (analyze_recording), dikte sırasında canlı
izleme (LevelMonitor) ve kayıtlı mikrofonun yeniden bulunması (resolve_input_device).
"""
import logging
import queue
import threading
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd


log = logging.getLogger(__name__)

SILENCE_PEAK = 1e-4   # ~-80 dBFS: sessize alınmış ya da Windows izni kapalı mikrofon hata vermez, tam sıfır verir
CLIP_PEAK = 0.98      # tam ölçeğe dayanan örnek: ses patlıyor
QUIET_DB = -40.0      # konuşma bundan kısıksa model zorlanır
NOISY_FLOOR_DB = -45.0
MIN_SNR_DB = 15.0

# uyarı anahtarı -> (kısa başlık, ne yapmalı)
MIC_WARNINGS = {
    "silent": ("Mikrofondan ses gelmiyor",
               "Mikrofon sessize alınmış ya da Windows'ta mikrofon izni kapalı olabilir."),
    "clipping": ("Ses patlıyor", "Mikrofonu biraz uzaklaştırın ya da giriş düzeyini düşürün."),
    "lost": ("Mikrofondan veri gelmiyor", "Mikrofonun bağlantısı kopmuş olabilir; takılı olduğunu kontrol edin."),
}
MIC_OPEN_ERROR = "Mikrofon açılamadı: takılı mı, başka program kullanıyor mu? Ayarlar › Mikrofonu test et"


def _db(x: float) -> float:
    return float(20 * np.log10(x + 1e-9))


def rms(pcm: np.ndarray) -> float:
    return float(np.sqrt(np.mean(pcm * pcm))) if len(pcm) else 0.0


def level_fraction(pcm: np.ndarray) -> float:
    """Seviye çubukları ve küre için 0..1 (-55 dBFS .. -15 dBFS)."""
    return min(1.0, max(0.0, (_db(rms(pcm)) + 55) / 40))


def frame_levels(pcm: np.ndarray, sample_rate: int, frame_ms: int = 30) -> np.ndarray:
    """30 ms'lik çerçevelerin dBFS seviyeleri."""
    n = max(1, sample_rate * frame_ms // 1000)
    usable = len(pcm) // n * n
    if usable == 0:
        return np.array([_db(rms(pcm))])
    frames = pcm[:usable].reshape(-1, n)
    return 20 * np.log10(np.sqrt(np.mean(frames * frames, axis=1)) + 1e-9)


@dataclass
class MicReport:
    verdict: str      # "good" | "silent" | "quiet" | "clipping" | "noisy"
    message: str
    speech_db: float  # konuşma seviyesi: en yüksek %5'lik çerçeveler
    noise_db: float   # gürültü tabanı: en sessiz %10'luk çerçeveler
    peak_db: float

    @property
    def ok(self) -> bool:
        return self.verdict == "good"


def analyze_recording(pcm: np.ndarray, sample_rate: int) -> MicReport:
    """Ayarlar › Mikrofonu test et: birkaç saniyelik kaydı düz bir cümleyle değerlendirir."""
    peak = float(np.max(np.abs(pcm))) if len(pcm) else 0.0
    if peak < SILENCE_PEAK:
        return MicReport("silent", "Mikrofondan hiç ses gelmiyor. Mikrofon sessize alınmış olabilir ya da Windows "
                         "Ayarlar › Gizlilik › Mikrofon bölümünde masaüstü uygulamalarının izni kapalı olabilir.",
                         -120.0, -120.0, _db(peak))
    levels = np.maximum(frame_levels(pcm, sample_rate), -120.0)
    speech, noise = float(np.percentile(levels, 95)), float(np.percentile(levels, 10))
    # bazı mikrofonlar (ya da Windows gürültü bastırması) duraklamada sesi tam sıfıra indirir
    nums = f"konuşma {speech:.0f} dBFS · " + ("gürültü yok denecek kadar az" if noise < -90 else f"gürültü {noise:.0f} dBFS")
    clipped = float(np.mean(np.abs(pcm) >= CLIP_PEAK))
    if clipped > 0.001:
        return MicReport("clipping", f"Ses patlıyor: mikrofonu biraz uzaklaştırın ya da Windows Ses › Giriş "
                         f"düzeyini düşürün. ({nums})", speech, noise, _db(peak))
    if speech < QUIET_DB:
        return MicReport("quiet", f"Ses çok kısık ya da konuşma duyulmadı: mikrofona yaklaşın veya Windows Ses › "
                         f"Giriş düzeyini artırın. ({nums})", speech, noise, _db(peak))
    if noise > NOISY_FLOOR_DB and speech - noise < MIN_SNR_DB:
        return MicReport("noisy", f"Ortam gürültüsü yüksek, konuşma gürültüden zor ayrılıyor: mikrofonu ağzınıza "
                         f"yaklaştırın ya da gürültü kaynağını azaltın. ({nums})", speech, noise, _db(peak))
    return MicReport("good", f"Mikrofon iyi çalışıyor. ({nums})", speech, noise, _db(peak))


class LevelMonitor:
    """Dikte sırasında gelen parçaları izler: uyarı anahtarını (MIC_WARNINGS, "" = sorun yok) ve oturum özetini tutar.

    Sessizlik uyarısı yalnızca oturumda hiç ses gelmediyse verilir: bazı mikrofonlar (ya da Windows gürültü
    bastırması) duraklamada sesi tam sıfıra indirir (veri toplama kayıtlarında görüldü), düşünme arası "ses gelmiyor"
    uyarısı yanlış alarm olurdu. Sessize alınmış ya da izni kapalı mikrofon ise ilk andan itibaren yalnız sıfır verir.
    """
    SILENT_WARN_S = 4.0
    CLIP_WINDOW_S = 2.0
    CLIP_CHUNKS = 3
    CLIP_HOLD_S = 3.0   # uyarı okunabilsin diye patlama bittikten sonra bir süre kalır

    def __init__(self, sample_rate: int):
        self.sr = sample_rate
        self.seconds = 0.0
        self.silent_run = 0.0
        self.silent_total = 0.0
        self.clipped_chunks = 0
        self.heard = False
        self.warning = ""
        self._clip_times: deque[float] = deque()
        self._levels: list[float] = []
        self._peak = 0.0

    def feed(self, chunk: np.ndarray) -> str:
        if not len(chunk):
            return self.warning
        dur = len(chunk) / self.sr
        peak = float(np.max(np.abs(chunk)))
        self.seconds += dur
        self._peak = max(self._peak, peak)
        self._levels.append(_db(rms(chunk)))
        if peak < SILENCE_PEAK:
            self.silent_run += dur
            self.silent_total += dur
        else:
            self.silent_run = 0.0
            self.heard = True
        if peak >= CLIP_PEAK:
            self.clipped_chunks += 1
            self._clip_times.append(self.seconds)
        recent = sum(1 for t in self._clip_times if self.seconds - t <= self.CLIP_WINDOW_S)
        if not self.heard and self.silent_run >= self.SILENT_WARN_S:
            self.warning = "silent"
        elif recent >= self.CLIP_CHUNKS:
            self.warning = "clipping"
        elif self.warning == "clipping" and self._clip_times and self.seconds - self._clip_times[-1] < self.CLIP_HOLD_S:
            pass
        else:
            self.warning = ""
        while self._clip_times and self.seconds - self._clip_times[0] > self.CLIP_HOLD_S:
            self._clip_times.popleft()
        return self.warning

    def summary(self, overflows: int = 0) -> str:
        """Günlüğe yazılacak tek satır: yalnız ses seviyeleri, metin içermez."""
        lv = np.array(self._levels) if self._levels else np.array([-120.0])
        return (f"mikrofon özeti: {self.seconds:.1f} sn, konuşma {np.percentile(lv, 95):.0f} dBFS, "
                f"gürültü tabanı {np.percentile(lv, 10):.0f} dBFS, en yüksek {_db(self._peak):.0f} dBFS, "
                f"patlayan parça {self.clipped_chunks}, tam sessiz {self.silent_total:.1f} sn, ses kaybı {overflows}")


def resolve_input_device(index: int | None, name: str = "") -> int | None:
    """Ayarlarda seçilen mikrofonun bugünkü numarası. USB mikrofon takılıp çıkınca aygıt numaraları kayar: numara
    artık o adı taşımıyorsa aynı adlı aygıt aranır; bulunamazsa varsayılan mikrofon (None) kullanılır."""
    if index is None and not name:
        return None
    try:
        devices = sd.query_devices()
    except Exception:  # noqa: BLE001 (ses sistemi okunamadı: kayıtlı numarayla denenir)
        return index

    def is_input(i: int | None) -> bool:
        return i is not None and 0 <= i < len(devices) and devices[i]["max_input_channels"] > 0

    if is_input(index) and (not name or devices[index]["name"] == name):
        return index
    if name:
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0 and d["name"] == name:
                log.info("Mikrofon %r artık %d numarada (eskiden %s)", name, i, index)
                return i
    log.warning("Ayarlardaki mikrofon bulunamadı (%s, %r): varsayılan mikrofon kullanılıyor", index, name)
    return None


def configured_device(cfg) -> int | None:
    return resolve_input_device(cfg.input_device, getattr(cfg, "input_device_name", ""))


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
        self.overflows = 0

    def _cb(self, indata, frames, time, status):  # noqa: ARG002
        if status:  # ör. input overflow: ses kartı verisi zamanında alınamadı, ses parçası kayboldu
            log.warning("mikrofon: %s", status)
            if status.input_overflow:
                self.overflows += 1
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
