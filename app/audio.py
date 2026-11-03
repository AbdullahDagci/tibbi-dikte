"""Mikrofon yakalama: float32 mono, modelin örnekleme hızında, kuyruğa parça parça."""
import queue

import numpy as np
import sounddevice as sd


def list_input_devices() -> list[tuple[int, str]]:
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append((i, d["name"]))
    return out


class Microphone:
    def __init__(self, sample_rate: int = 16000, device: int | None = None, block_ms: int = 100):
        self.sample_rate = sample_rate
        self.device = device
        self.blocksize = int(sample_rate * block_ms / 1000)
        self.q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream: sd.InputStream | None = None

    def _cb(self, indata, frames, time, status):  # noqa: ARG002
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
