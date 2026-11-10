"""Mikrofon sorunlarının tespiti: kayıt testi (Ayarlar › Mikrofonu test et), dikte sırasında canlı uyarı,
kayıtlı mikrofonun bulunması."""
import numpy as np
import pytest

from app import audio
from app.audio import LevelMonitor, analyze_recording, resolve_input_device

SR = 16000
rng = np.random.default_rng(0)


def _db_to_amp(db: float) -> float:
    return 10 ** (db / 20)


def _speech_like(seconds=5.0, speech_db=-20.0, noise_db=-65.0) -> np.ndarray:
    """Gürültü tabanı + aralıklı 'konuşma' patlamaları (0,4 sn konuşma, 0,3 sn duraklama)."""
    n = int(seconds * SR)
    pcm = rng.normal(0, _db_to_amp(noise_db), n).astype(np.float32)
    t = np.arange(n) / SR
    burst = ((t % 0.7) < 0.4).astype(np.float32)
    tone = np.sin(2 * np.pi * 220 * t) * _db_to_amp(speech_db) * np.sqrt(2)
    return (pcm + burst * tone).astype(np.float32)


def test_good_recording():
    r = analyze_recording(_speech_like(), SR)
    assert r.verdict == "good" and r.ok
    assert -24 < r.speech_db < -16
    assert r.noise_db < -55


def test_all_zero_is_silent():
    # sessize alınmış ya da Windows izni kapalı mikrofon hata vermez, tam sıfır verir
    r = analyze_recording(np.zeros(SR * 5, np.float32), SR)
    assert r.verdict == "silent" and not r.ok
    assert "izni" in r.message


def test_empty_recording_is_silent():
    assert analyze_recording(np.zeros(0, np.float32), SR).verdict == "silent"


def test_quiet_recording():
    r = analyze_recording(_speech_like(speech_db=-50, noise_db=-75), SR)
    assert r.verdict == "quiet"
    assert "kısık" in r.message


def test_clipping_recording():
    pcm = np.clip(_speech_like(speech_db=-20) * 30, -1, 1)
    r = analyze_recording(pcm, SR)
    assert r.verdict == "clipping"
    assert "patlıyor" in r.message


def test_noisy_room():
    r = analyze_recording(_speech_like(speech_db=-22, noise_db=-30), SR)
    assert r.verdict == "noisy"
    assert "gürültü" in r.message


# ------------------------------------------------------------- dikte sırasında canlı izleme
def _chunks(pcm: np.ndarray, size=1600):
    return [pcm[i:i + size] for i in range(0, len(pcm), size)]


def test_monitor_warns_when_nothing_ever_arrives():
    m = LevelMonitor(SR)
    zeros = _chunks(np.zeros(SR * 5, np.float32))
    states = [m.feed(c) for c in zeros]
    assert states[0] == ""                      # ilk anlar: henüz uyarı yok
    assert states[-1] == "silent"               # birkaç saniye tam sessizlik
    assert m.feed(_speech_like(0.1)) == ""      # ses gelince uyarı kalkar


def test_gated_microphone_pause_is_not_reported():
    # gerçek kayıt deseni: konuşma bitince ses birkaç yüz ms içinde tam sıfıra iner; başta hafif gürültü vardır
    r = analyze_recording(np.concatenate([_speech_like(3.0), np.zeros(SR * 2, np.float32)]), SR)
    assert r.verdict == "good"
    assert "-1" not in r.message.split("gürültü")[1][:6]   # "-180 dBFS" gibi anlamsız sayı yazılmaz
    m = LevelMonitor(SR)
    m.feed(np.full(1600, 3e-4, np.float32))     # açılışta gürültü bastırma henüz devreye girmemiş
    states = [m.feed(c) for c in _chunks(np.zeros(SR * 6, np.float32))]
    assert "silent" not in states


def test_monitor_does_not_warn_on_pause_after_speech():
    # bazı dikte mikrofonları duraklamada sesi tamamen keser (gürültü kapısı): düşünme arası uyarı vermemeli
    m = LevelMonitor(SR)
    for c in _chunks(_speech_like(2.0)):
        m.feed(c)
    states = [m.feed(c) for c in _chunks(np.zeros(SR * 6, np.float32))]
    assert "silent" not in states


def test_monitor_warns_on_sustained_clipping_and_recovers():
    m = LevelMonitor(SR)
    loud = np.clip(_speech_like(2.0, speech_db=-20) * 30, -1, 1)
    states = [m.feed(c) for c in _chunks(loud)]
    assert states[-1] == "clipping"
    states = [m.feed(c) for c in _chunks(_speech_like(4.0))]
    assert states[0] == "clipping"              # okunabilsin diye hemen kaybolmaz
    assert states[-1] == ""


def test_single_clipped_chunk_is_not_a_warning():
    m = LevelMonitor(SR)
    for c in _chunks(_speech_like(1.0)):
        m.feed(c)
    spike = _speech_like(0.1)
    spike[100] = 1.0
    assert m.feed(spike) == ""


def test_monitor_summary_has_levels_but_no_text():
    m = LevelMonitor(SR)
    for c in _chunks(_speech_like(3.0)):
        m.feed(c)
    s = m.summary(overflows=2)
    assert "3.0 sn" in s and "dBFS" in s and "ses kaybı 2" in s


# ------------------------------------------------------------- kayıtlı mikrofonun bulunması
DEVICES = [
    {"name": "Microsoft Ses Eşleyicisi - Input", "max_input_channels": 2},
    {"name": "Hoparlör (Realtek)", "max_input_channels": 0},
    {"name": "Mikrofon (USB Audio)", "max_input_channels": 1},
    {"name": "Mikrofon (Realtek)", "max_input_channels": 2},
]


@pytest.fixture
def devices(monkeypatch):
    monkeypatch.setattr(audio.sd, "query_devices", lambda: DEVICES)


def test_default_device_stays_default(devices):
    assert resolve_input_device(None, "") is None


def test_same_index_same_name(devices):
    assert resolve_input_device(2, "Mikrofon (USB Audio)") == 2


def test_device_found_by_name_when_index_shifted(devices):
    # USB mikrofon çıkarılıp takılınca aygıt numaraları kayar
    assert resolve_input_device(1, "Mikrofon (USB Audio)") == 2


def test_missing_device_falls_back_to_default(devices):
    assert resolve_input_device(5, "Mikrofon (Bluetooth)") is None


def test_old_config_without_name_keeps_valid_index(devices):
    assert resolve_input_device(3, "") == 3
    assert resolve_input_device(1, "") is None   # artık giriş aygıtı değil (hoparlör)
