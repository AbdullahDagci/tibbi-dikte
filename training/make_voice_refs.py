"""Chatterbox ses klonlama referansları: gerçek konuşma veri setlerinden farklı konuşmacılara ait, temiz klipler.

Aday: süresi 6–12 sn olan kesitler. Her aday mevcut modelle çözülür; transkriptine yakın (WER <= --max-wer)
olanlar seçilir: anlaşılır, gürültüsü düşük referans -> klonlanan ses de anlaşılır olur.

  python make_voice_refs.py --manifests data/manifests --sets issai_train:300,fleurs_train:100,mediaspeech_train:50 \
      --model ../models/tibbi-tr-v2 --out data/voice_refs
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

from synthcheck import pick_refs, word_error_rate

ROOT = Path(__file__).resolve().parent.parent


def read_cuts(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def load_wav(path: str):
    """PCM16 ya da float WAV (FLEURS 32 bit float) -> (float32 mono, örnekleme hızı)."""
    import soundfile as sf
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    return audio[:, 0], sr


def sf_write(dst: Path, audio, sr: int) -> None:
    """Referanslar tek biçimde (PCM16) saklanır."""
    import soundfile as sf
    sf.write(str(dst), audio, sr, subtype="PCM_16")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifests", required=True)
    ap.add_argument("--sets", required=True, help="ad:adet,ad:adet")
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-wer", type=float, default=0.25)
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    from app.engines.base import ModelInfo
    from app.engines.registry import load_engine
    eng = load_engine(ModelInfo.from_dir(Path(a.model)))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    index = out / "_index.tsv"
    with index.open("a", encoding="utf-8") as idx:  # setler ayrı ayrı eklenebilir
        for spec in a.sets.split(","):
            name, want = spec.split(":")
            cuts = {c["recording"]["sources"][0]["source"]: c for c in read_cuts(Path(a.manifests) / f"{name}.jsonl.gz")
                    if c["start"] == 0 and abs(c["duration"] - c["recording"]["duration"]) < 0.01}
            cands = pick_refs([(p, c["duration"]) for p, c in cuts.items()], int(want) * 4)
            kept = 0
            for p in cands:
                audio, sr = load_wav(p)
                text = cuts[p]["supervisions"][0]["text"]
                w = word_error_rate(text, eng.transcribe(audio, sr))
                if w > a.max_wer:
                    continue
                dst = out / f"{name.split('_')[0]}_{kept:04d}.wav"
                sf_write(dst, audio, sr)
                idx.write(f"{dst.name}\t{p}\t{w:.2f}\t{text}\n")
                kept += 1
                if kept >= int(want):
                    break
            print(f"{name}: {kept}/{want} referans ({len(cands)} adaydan)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
