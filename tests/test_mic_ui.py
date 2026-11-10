"""Mikrofon sorunlarının kullanıcıya gösterilmesi: dikte uyarıları, gösterge, Ayarlar › Mikrofonu test et,
Test/Veri toplama ekranlarının seçili mikrofonu kullanması."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import queue  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import sounddevice as sd  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import dictation as dmod  # noqa: E402
from app.audio import MIC_OPEN_ERROR  # noqa: E402
from app.config import Config  # noqa: E402

SR = 16000


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _dispose(widget):
    """Sahipsiz pencere çöp toplayıcıya bırakılmaz (PySide sonraki bir testte çökebilir)."""
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


# ------------------------------------------------------------------ dikte
class FakeSession:
    def accept(self, chunk): return []
    def partial(self): return ""
    def flush(self): return []
    def word_confidences(self): return None


class FakeEngine:
    sample_rate = SR
    def new_session(self): return FakeSession()


def _fake_mic(pcm: np.ndarray, fail: bool = False):
    class FakeMic:
        def __init__(self, sample_rate=SR, device=None):
            self.q = queue.Queue()
            for i in range(0, len(pcm), 1600):
                self.q.put(pcm[i:i + 1600])

        def start(self):
            if fail:
                raise sd.PortAudioError("Invalid device")

        def stop(self): ...

        def read(self, timeout=0.2):
            try:
                return self.q.get_nowait()
            except queue.Empty:
                time.sleep(0.02)
                return None
    return FakeMic


def _dictation(monkeypatch, pcm, fail=False):
    monkeypatch.setattr(dmod, "Microphone", _fake_mic(pcm, fail))
    warnings, states = [], []
    d = dmod.Dictation(Config(), on_state=states.append, on_warning=warnings.append)
    d.engine = FakeEngine()
    return d, warnings, states


def _wait(cond, seconds=5.0):
    deadline = time.time() + seconds
    while not cond() and time.time() < deadline:
        time.sleep(0.02)


def test_dictation_warns_when_microphone_gives_only_zeros(monkeypatch):
    d, warnings, _ = _dictation(monkeypatch, np.zeros(SR * 6, np.float32))
    d.start_listening()
    _wait(lambda: "silent" in warnings)
    d.stop_listening()
    assert warnings[0] == "silent"
    assert warnings[-1] == ""        # dikte bitince uyarı kalkar


def test_dictation_warns_when_microphone_stops_delivering(monkeypatch):
    d, warnings, _ = _dictation(monkeypatch, np.full(SR // 2, 0.01, np.float32))
    d.start_listening()
    _wait(lambda: "lost" in warnings, seconds=dmod.NO_DATA_S + 3)
    d.stop_listening()
    assert "lost" in warnings


def test_normal_audio_gives_no_warning(monkeypatch):
    t = np.arange(SR * 2) / SR
    d, warnings, _ = _dictation(monkeypatch, (0.05 * np.sin(2 * np.pi * 200 * t)).astype(np.float32))
    d.start_listening()
    time.sleep(0.5)
    d.stop_listening()
    assert warnings == []


def test_microphone_open_failure_is_explained(monkeypatch):
    d, _, states = _dictation(monkeypatch, np.zeros(0, np.float32), fail=True)
    d.start_listening()
    _wait(lambda: "error" in states)
    assert "error" in states
    assert d.last_error == MIC_OPEN_ERROR


# ------------------------------------------------------------------ gösterge
def test_overlay_shows_and_clears_mic_warning(qapp):
    from app.overlay import ListeningOverlay
    o = ListeningOverlay()
    o.start()
    o.set_warning("silent")
    assert "Mikrofondan ses gelmiyor" in o.caption.text()
    assert "izni" in o.text.text()           # henüz metin yokken ne yapılacağı da yazar
    o.set_warning("")
    assert "Mikrofondan" not in o.caption.text()
    o.set_warning("clipping")
    o.start()                                # yeni dikte temiz başlar
    assert "patlıyor" not in o.caption.text()
    _dispose(o)


# ------------------------------------------------------------------ Ayarlar › Mikrofonu test et
class FakeStream:
    instances = []

    def __init__(self, data: np.ndarray, **kw):
        self.kw, self.data = kw, data
        FakeStream.instances.append(self)

    def start(self):
        for i in range(0, len(self.data), 1600):
            self.kw["callback"](self.data[i:i + 1600, None], 1600, None, None)

    def stop(self): ...
    def close(self): ...


@pytest.fixture
def fake_stream(monkeypatch):
    FakeStream.instances.clear()
    holder = {"data": np.zeros(SR, np.float32)}
    monkeypatch.setattr(sd, "InputStream", lambda **kw: FakeStream(holder["data"], **kw))
    return holder


def test_mic_test_panel_reports_silence_with_selected_device(qapp, fake_stream):
    from app.mic_test import MicTestPanel
    p = MicTestPanel(lambda: 7)
    fake_stream["data"] = np.zeros(SR * 5, np.float32)
    p._toggle()
    assert p.recording
    p._toggle()                              # 5 sn beklemeden durdurulabilir
    assert not p.recording
    assert FakeStream.instances[-1].kw["device"] == 7
    assert p.report.verdict == "silent"
    assert "izni" in p.status.text()
    assert not p.btn_play.isHidden()         # duyulan sesi dinleyebilir
    _dispose(p)


def test_mic_test_panel_good_recording(qapp, fake_stream):
    from app.mic_test import MicTestPanel
    rng = np.random.default_rng(1)
    t = np.arange(SR * 5) / SR
    pcm = (rng.normal(0, 3e-4, len(t)) + ((t % 0.7) < 0.4) * 0.14 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    fake_stream["data"] = pcm
    p = MicTestPanel(lambda: None)
    p._toggle()
    p._toggle()
    assert p.report.ok
    assert "iyi" in p.status.text()
    _dispose(p)


def test_mic_test_panel_open_failure(qapp, monkeypatch):
    from app.mic_test import MicTestPanel

    def boom(**kw):
        raise sd.PortAudioError("Device unavailable")
    monkeypatch.setattr(sd, "InputStream", boom)
    p = MicTestPanel(lambda: 3)
    p._toggle()
    assert not p.recording
    assert "açılamadı" in p.status.text()
    _dispose(p)


def test_settings_saves_device_name(qapp, monkeypatch, tmp_path):
    from app import config as cmod
    from app import settings_window as sw
    monkeypatch.setattr(cmod, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(sw, "list_input_devices", lambda: [(2, "Mikrofon (USB Audio)")])
    monkeypatch.setattr(sw, "configured_device", lambda cfg: cfg.input_device)
    cfg = Config()
    page = sw.SettingsPage(cfg)
    page.mic_box.setCurrentIndex(page.mic_box.findData(2))
    assert page.save()
    assert (cfg.input_device, cfg.input_device_name) == (2, "Mikrofon (USB Audio)")
    page.mic_box.setCurrentIndex(0)
    page.save()
    assert (cfg.input_device, cfg.input_device_name) == (None, "")
    _dispose(page)


# ------------------------------------------------------------------ Test ekranı seçili mikrofonu kullanır
def test_testbench_records_from_selected_device(qapp, fake_stream):
    from app.testbench import TestPage
    page = TestPage(lambda: (None, None, False), [], get_device=lambda: 4)
    fake_stream["data"] = np.zeros(SR, np.float32)
    page._toggle_record()
    assert FakeStream.instances[-1].kw["device"] == 4
    page._toggle_record()
    assert "ses gelmiyor" in page.file_label.text()   # kötü kayıt: önce mikrofon kontrol edilmeli
    _dispose(page)
