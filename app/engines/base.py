"""STT motor arayüzü.

Her motor bir model klasöründen (model.json) yüklenir ve bir dikte oturumu üretir.
Oturum ses parçalarını alır ve *kesinleşmiş* metin parçalarını döndürür; uygulama yalnızca
kesinleşmiş metni yazar (yazılmış metni geri silmek zorunda kalmamak için).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Hafif yeniden örnekleme (sinc yerine doğrusal + kenar yumuşatma; konuşma tanıma için yeterli)."""
    if sr_in == sr_out or len(x) == 0:
        return x.astype(np.float32)
    if sr_in > sr_out:  # örtüşmeyi (aliasing) azaltmak için basit alçak geçiren: kayan ortalama
        k = max(1, int(round(sr_in / sr_out)))
        if k > 1:
            x = np.convolve(x, np.ones(k, dtype=np.float32) / k, mode="same")
    n = int(round(len(x) * sr_out / sr_in))
    t = np.linspace(0, len(x) - 1, n)
    return np.interp(t, np.arange(len(x)), x).astype(np.float32)


@dataclass
class ModelInfo:
    dir: Path
    spec: dict

    @property
    def name(self) -> str:
        return self.spec.get("name", self.dir.name)

    @property
    def attribution(self) -> str:
        """Modelin lisansının arayüzde gösterilmesini zorunlu tuttuğu ibare (yoksa boş)."""
        return self.spec.get("attribution", "")

    @property
    def engine(self) -> str:
        return self.spec.get("engine", "sherpa-onnx")

    @property
    def sample_rate(self) -> int:
        return int(self.spec.get("sample_rate", 16000))

    @property
    def hotwords(self) -> bool:
        """False: model tıbbi terimleri eğitimde öğrendi, hotword yardımı ona zarar verir (model.json "hotwords")."""
        return bool(self.spec.get("hotwords", True))

    def path(self, key: str) -> str | None:
        """model.json'daki dosya adını mutlak yola çevirir (yoksa None)."""
        name = self.spec.get(key)
        return str(self.dir / name) if name else None

    @classmethod
    def from_dir(cls, d: Path) -> "ModelInfo":
        spec = json.loads((d / "model.json").read_text(encoding="utf-8"))
        return cls(dir=d, spec=spec)


class DictationSession(ABC):
    @abstractmethod
    def accept(self, samples: np.ndarray) -> list[str]:
        """float32 mono örnekleri al, kesinleşen metin parçalarını döndür."""

    @abstractmethod
    def flush(self) -> list[str]:
        """Dikte durdurulurken kalan sesi çöz ve son parçaları döndür."""

    def partial(self) -> str:
        """Henüz kesinleşmemiş (o an söylenmekte olan) metin — yalnızca ekranda göstermek için."""
        return ""


class SttEngine(ABC):
    def __init__(self, model: ModelInfo, *, num_threads: int = 2,
                 hotwords_file: str | None = None, hotwords_score: float = 2.0):
        self.model = model
        self.num_threads = num_threads
        self.hotwords_file = hotwords_file
        self.hotwords_score = hotwords_score

    @property
    def sample_rate(self) -> int:
        return self.model.sample_rate

    @abstractmethod
    def new_session(self) -> DictationSession: ...

    def transcribe(self, samples: np.ndarray, sample_rate: int | None = None) -> str:
        """Tüm bir kaydı çöz (test / ses dosyası için). Farklı örnekleme hızı modele uyarlanır."""
        if sample_rate and sample_rate != self.sample_rate:
            samples = resample(samples, sample_rate, self.sample_rate)
        s = self.new_session()
        chunk = self.sample_rate // 10
        parts: list[str] = []
        for i in range(0, len(samples), chunk):
            parts += s.accept(samples[i:i + chunk])
        parts += s.flush()
        return " ".join(p for p in parts if p)
