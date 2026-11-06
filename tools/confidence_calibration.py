"""Decoder güven skoru ölçüm/kalibrasyon aracı.

sherpa-onnx'in modified_beam_search çözücüsü her alt-token için log-olabilirlik (ys_probs) veriyor;
app/engines/sherpa_engine.py bunu kelime bazlı ham güven skoruna (0..1, kalibre edilmemiş) çeviriyor.
Bu araç, elimizdeki referanslı test seslerinde bu ham skoru gerçek doğruluğa (referansla hizalama,
app/scoring.py) karşı ölçer — amaç: Test ekranındaki turuncu/kırmızı renk eşiklerini tahminle değil,
"bu güven aralığındaki kelimelerin gerçekte ne kadarı yanlış çıkıyor" verisine bakarak koymak.

Not: ham `ys_probs` kalibre değildir (bkz. araştırma: Google RNN-T confidence, arXiv 2110.15222).
Bu araç bir kalibrasyon EĞRİSİ üretir (ham güven -> gözlenen doğruluk), final eşikleri değil.
Örnek sayısı küçükken (şu an tests/ + data/radiology_test/synthetic_audio ~ 100 cümle) sonuçlar
yalnızca kaba bir yön verir; gerçek karar için daha büyük/gerçek-ses bir küme gerekir.

Kullanım:
  python tools/confidence_calibration.py [--model models/tibbi-tr-v3-tam] [--sets tests,radyoloji_sentetik]
      [--bins 10] [--out benchmarks/confidence_calibration.csv] [--verbose]
"""
from __future__ import annotations

import argparse
import csv
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engines.base import ModelInfo  # noqa: E402
from app.engines.registry import discover_models, load_engine, resolve_model  # noqa: E402
from app.scoring import align, spoken_tokens  # noqa: E402

SET_LOCATIONS = {
    "tests": (ROOT / "tests" / "audio", ROOT / "tests" / "sentences_tr.txt"),
    "radyoloji_sentetik": (ROOT / "data" / "radiology_test" / "synthetic_audio",
                           ROOT / "data" / "radiology_test" / "sentences.txt"),
    "radyoloji_gercek": (ROOT / "data" / "radiology_test" / "audio",
                         ROOT / "data" / "radiology_test" / "sentences.txt"),
}


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    try:
        import soundfile as sf
        a, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return a.mean(axis=1), sr
    except Exception:
        with wave.open(str(path)) as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
            return pcm, w.getframerate()


def numbered_set(audio_dir: Path, sentences: Path) -> list[tuple[str, Path, str]]:
    if not audio_dir.is_dir() or not sentences.is_file():
        return []
    refs = [l.strip() for l in sentences.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for w in sorted(audio_dir.glob("*.wav")):
        try:
            out.append((w.stem, w, refs[int(w.name[:2])]))
        except (ValueError, IndexError):
            continue
    return out


def _norm_one(word: str) -> str:
    toks = spoken_tokens(word)
    return toks[0] if toks else ""


def collect_rows(set_name: str, items, engine, verbose: bool) -> list[dict]:
    rows: list[dict] = []
    for uid, path, ref in items:
        audio, sr = load_wav(path)
        raw_text, confs = engine.transcribe_with_confidence(audio, sr)
        if not confs:
            continue
        words, cvals = zip(*confs)
        norm = [_norm_one(w) for w in words]
        keep = [i for i, nw in enumerate(norm) if nw]
        hyp_tokens = [norm[i] for i in keep]
        hyp_orig = [words[i] for i in keep]
        hyp_conf = [cvals[i] for i in keep]
        al = align(list(spoken_tokens(ref)), hyp_tokens)
        it = iter(zip(hyp_orig, hyp_conf))
        for a in al:
            if a.op in ("ok", "sub", "ins"):
                ow, cv = next(it)
                rows.append({"set": set_name, "file": uid, "word": ow, "confidence": cv,
                            "correct": a.op == "ok"})
        if verbose:
            print(f"[{set_name}/{uid}] REF: {ref}\n  HAM: {raw_text}")
    return rows


def print_reliability_table(rows: list[dict], bins: int) -> None:
    if not rows:
        print("Hiç kelime toplanamadı (ses/metin bulunamadı ya da model güven vermiyor).")
        return
    edges = np.linspace(0.0, 1.0, bins + 1)
    print(f"\n{'güven aralığı':>16}  {'n':>5}  {'doğruluk':>9}  {'hata oranı':>10}")
    for lo, hi in zip(edges[:-1], edges[1:]):
        bucket = [r for r in rows if lo <= r["confidence"] < hi or (hi == 1.0 and r["confidence"] == 1.0)]
        if not bucket:
            continue
        acc = sum(r["correct"] for r in bucket) / len(bucket)
        print(f"  {lo:5.2f}-{hi:4.2f}  {len(bucket):5d}  {acc*100:8.1f}%  {100*(1-acc):9.1f}%")
    n = len(rows)
    acc_all = sum(r["correct"] for r in rows) / n
    print(f"\nToplam kelime: {n}  ·  genel doğruluk: %{acc_all*100:.1f}")
    if n < 300:
        print("UYARI: örnek sayısı küçük — bu tablo yön verir ama kesin eşik kararı için yetersiz "
              "(daha fazla gerçek radyolog kaydı gerekir, bkz. data/radiology_test/audio).")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model")
    ap.add_argument("--sets", default="tests,radyoloji_sentetik,radyoloji_gercek")
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--out", default=str(ROOT / "benchmarks" / "confidence_calibration.csv"))
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    model = ModelInfo.from_dir(Path(a.model)) if a.model else resolve_model(discover_models(), "")
    print("model:", model.name)
    engine = load_engine(model)

    rows: list[dict] = []
    for name in [s.strip() for s in a.sets.split(",") if s.strip()]:
        loc = SET_LOCATIONS.get(name)
        if loc is None:
            print(f"bilinmeyen set, atlandı: {name}")
            continue
        items = numbered_set(*loc)
        if not items:
            print(f"{name}: ses/metin bulunamadı, atlandı ({loc[0]})")
            continue
        print(f"{name}: {len(items)} örnek çözümleniyor…")
        rows += collect_rows(name, items, engine, a.verbose)

    out_path = Path(a.out)
    out_path.parent.mkdir(exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["set", "file", "word", "confidence", "correct"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nham veri: {out_path} ({len(rows)} kelime)")
    print_reliability_table(rows, a.bins)
    return 0


if __name__ == "__main__":
    sys.exit(main())
