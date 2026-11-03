"""Model keşfi ve motor seçimi.

Yeni bir runtime eklemek için: SttEngine'den türeyen sınıfı yazıp ENGINES'e ekleyin,
model.json'da "engine" alanına anahtarını yazın.
"""
from __future__ import annotations

from pathlib import Path

from ..paths import models_dirs
from .base import ModelInfo, SttEngine


def _sherpa(model: ModelInfo, **kw) -> SttEngine:
    from .sherpa_engine import SherpaOfflineEngine, SherpaOnlineEngine
    cls = SherpaOnlineEngine if model.spec.get("mode", "online") == "online" else SherpaOfflineEngine
    return cls(model, **kw)


ENGINES = {
    "sherpa-onnx": _sherpa,
}


def discover_models(extra_dirs: list[Path] | None = None) -> list[ModelInfo]:
    found: list[ModelInfo] = []
    for root in [*models_dirs(), *(extra_dirs or [])]:
        for d in sorted(Path(root).iterdir()):
            if (d / "model.json").is_file():
                try:
                    found.append(ModelInfo.from_dir(d))
                except Exception:  # bozuk model.json listeyi bozmasın
                    continue
    return found


def load_engine(model: ModelInfo, **kw) -> SttEngine:
    factory = ENGINES.get(model.engine)
    if factory is None:
        raise ValueError(f"Bilinmeyen motor: {model.engine!r} ({model.dir})")
    return factory(model, **kw)
