"""Modelleri gerçek konuşma test setlerinde (lhotse manifest) karşılaştırır: ince ayar genel Türkçeyi bozdu mu?

Derlem WER'i (toplam hata / toplam referans kelime); büyük/küçük harf ve noktalama yok sayılır. Ham model çıktısı
(hotword ve son işlem yok) — modelin kendisini ölçer.

  python eval_manifest.py --models ../models/tibbi-tr-v2,../models/mihu-tr-radyoloji-ft1 \
      --sets fleurs_test,issai_test --limit 600
"""
from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
from pathlib import Path

from synthcheck import word_errors

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def read_cuts(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", required=True, help="virgülle ayrılmış model klasörleri")
    ap.add_argument("--sets", default="fleurs_test,issai_test")
    ap.add_argument("--manifests", default=str(HERE / "data" / "manifests"))
    ap.add_argument("--limit", type=int, default=600, help="set başına rastgele kesit (0: hepsi)")
    a = ap.parse_args()
    import soundfile as sf
    sys.path.insert(0, str(ROOT))
    from app.engines.base import ModelInfo
    from app.engines.registry import load_engine

    models = [Path(m) for m in a.models.split(",")]
    engines = [load_engine(ModelInfo.from_dir(m)) for m in models]
    print("set".ljust(22) + "".join(m.name[:28].ljust(30) for m in models))
    for name in a.sets.split(","):
        cuts = read_cuts(Path(a.manifests) / f"{name}.jsonl.gz")
        if a.limit and len(cuts) > a.limit:
            cuts = random.Random(0).sample(cuts, a.limit)
        errs, words = [0] * len(engines), 0
        for c in cuts:
            audio, sr = sf.read(c["recording"]["sources"][0]["source"], dtype="float32", always_2d=True)
            s0 = int(c["start"] * sr)
            audio = audio[s0:s0 + int(c["duration"] * sr), 0]
            ref = c["supervisions"][0]["text"]
            for k, eng in enumerate(engines):
                e, n = word_errors(ref, eng.transcribe(audio, sr))
                errs[k] += e
            words += n
        print(f"{name} ({len(cuts)})".ljust(22) + "".join(f"WER {100 * e / max(1, words):5.1f}%".ljust(30) for e in errs),
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
