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
