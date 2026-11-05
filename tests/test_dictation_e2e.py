"""Uçtan uca: wav dosyasını sahte mikrofondan besler, "yazılan" metni yakalar (gerçek model ile)."""
import queue
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from app import dictation as dmod
from app.config import Config

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "tests" / "audio" / "09_Emel.wav"   # "Pantoprazol kırk miligram intravenöz ..."
MODEL = ROOT / "models" / "tibbi-tr-v2"

pytestmark = pytest.mark.skipif(not (AUDIO.exists() and (MODEL / "model.json").exists()),
                                reason="model veya test sesi yok")


class FakeMic:
    def __init__(self, sample_rate=16000, device=None):
        with wave.open(str(AUDIO)) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        pcm = np.concatenate([pcm, np.zeros(sample_rate * 2, dtype=np.float32)])  # sonda sessizlik
        self.q = queue.Queue()
        for i in range(0, len(pcm), 1600):
            self.q.put(pcm[i:i + 1600])

    def start(self): ...
    def stop(self): ...

    def read(self, timeout=0.2):
        try:
            return self.q.get_nowait()
        except queue.Empty:
            time.sleep(min(timeout, 0.05))
            return None


def test_dictation_pipeline(monkeypatch):
    monkeypatch.setattr(dmod, "Microphone", FakeMic)
    screen = {"text": ""}
    typed, states = [], []

    def typer(t):
        typed.append(t)
        screen["text"] += t

    def eraser(n):
        if n:
            screen["text"] = screen["text"][:-n]

    d = dmod.Dictation(Config(model_dir=str(MODEL)), on_state=states.append, typer=typer, eraser=eraser)
    d.load()
    d.toggle()
    deadline = time.time() + 30
    while not typed and time.time() < deadline:
        time.sleep(0.1)
    d.toggle()
    text = screen["text"]
    assert "Pantoprazol" in text
    assert "40 mg" in text
    assert "intravenöz" in text
    assert states[:2] == ["loading", "idle"] and "listening" in states and states[-1] == "idle"


def test_model_can_disable_hotwords(monkeypatch, tmp_path):
    """Terimleri kendisi öğrenmiş (ince ayarlı) model: model.json "hotwords": false -> ayar açık olsa da hotword
    verilmez (radyoloji testinde hotword bu modelin hatasını %5'ten %7,6'ya çıkarıyordu). Diğer modeller etkilenmez."""
    import json
    from app.engines.base import ModelInfo
    spec = json.loads((MODEL / "model.json").read_text(encoding="utf-8"))
    for k in ("tokens", "encoder", "decoder", "joiner", "bpe_vocab"):
        spec[k] = str(MODEL / spec[k])
    spec["hotwords"] = False
    (tmp_path / "model.json").write_text(json.dumps(spec), encoding="utf-8")
    tuned = ModelInfo.from_dir(tmp_path)
    assert tuned.hotwords is False and ModelInfo.from_dir(MODEL).hotwords is True

    monkeypatch.setattr(dmod, "discover_models", lambda: [tuned])
    d = dmod.Dictation(Config(model_dir=str(tmp_path), use_hotwords=True))
    d.load()
    assert d.engine.hotwords_file is None

    monkeypatch.setattr(dmod, "discover_models", lambda: [ModelInfo.from_dir(MODEL)])
    d2 = dmod.Dictation(Config(model_dir=str(MODEL), use_hotwords=True))
    d2.load()
    assert d2.engine.hotwords_file


def test_dictation_into_editor_sink(monkeypatch):
    """Test › Canlı dikte: metin dikte iş parçacığından editöre doğrudan (SendInput olmadan) yazılır."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication
    from app.editor import DictationEditor, TextSink

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(dmod, "Microphone", FakeMic)
    ed = DictationEditor()
    sink = TextSink(ed)
    d = dmod.Dictation(Config(model_dir=str(MODEL)), typer=sink.type, eraser=sink.erase)
    d.load()
    d.toggle()
    deadline = time.time() + 30
    while "mg" not in ed.toPlainText() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    d.toggle()
    QCoreApplication.processEvents()
    text = ed.toPlainText()
    assert "Pantoprazol" in text and "40 mg" in text and "intravenöz" in text
