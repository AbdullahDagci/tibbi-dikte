"""Model başarı ölçümü (benchmark): her model aynı test setlerinden geçer, sonuçlar birikir ve karşılaştırılır.

  python tools/benchmark.py                                  # varsayılan model, tüm setler
  python tools/benchmark.py --model models/tibbi-tr-radyoloji-ft1 --label "ft1 (A yolu)"
  python tools/benchmark.py --sets fleurs,radyoloji_gercek --limit 200
  python tools/benchmark.py --report-only                    # yalnızca raporu yeniden üret

Setler (bulunanlar çalışır):
  fleurs            FLEURS-TR test (gerçek insan sesi, genel Türkçe) — training/data/manifests/fleurs_test.jsonl.gz
  radyoloji_gercek  radyologların kayıtları — data/radiology_test/audio + sentences.txt  (asıl ölçüt)
  radyoloji_sentetik data/radiology_test/synthetic_audio + sentences.txt
  genel_sentetik    tests/audio + tests/sentences_tr.txt
  vakalar           tests/cases/*.hyp.txt — yalnızca sonişleme (model çıktısı sabit)
Ölçütler: WER/CER (ham model ve uygulama çıktısı), kelime doğruluğu, tıbbi terim isabeti, hız (RTF).
Çıktı: benchmarks/results.jsonl (birikir) + benchmarks/RAPOR.md (karşılaştırma tablosu)
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# app.dictation mikrofon/klavye modüllerini içe aktarır; ekransız sunucuda çalışabilmek için yollar burada
MED = ROOT / "app" / "medical"
BUILTIN_LEXICON, RADIOLOGY_LEXICON = MED / "lexicon_tr.txt", MED / "radiology_terms_tr.txt"
BUILTIN_CORRECTIONS, RADIOLOGY_FUZZY, RADIOLOGY_KNOWN = (MED / "corrections_tr.tsv", MED / "radiology_fuzzy_tr.txt",
                                                         MED / "radiology_known_tr.txt")
from app.engines.base import ModelInfo  # noqa: E402
from app.engines.registry import discover_models, load_engine  # noqa: E402
from app.medical.postprocess import MedicalPostProcessor, read_lexicon, tr_capitalize, tr_lower  # noqa: E402


def write_hotwords(lexicon_files: list[Path], out: Path) -> Path:
    seen: dict[str, None] = {}
    for p in lexicon_files:
        for t in read_lexicon(p):
            seen.setdefault(t, None)
            if t[:1].islower():
                seen.setdefault(tr_capitalize(t), None)
    out.write_text("\n".join(seen), encoding="utf-8")
    return out
from app.scoring import score  # noqa: E402

OUT = ROOT / "benchmarks"
SET_NAMES = ["fleurs", "radyoloji_gercek", "radyoloji_sentetik", "genel_sentetik", "vakalar"]
SET_TITLES = {"fleurs": "FLEURS-TR test (gerçek ses, genel Türkçe)", "radyoloji_gercek": "Radyoloji — gerçek kayıtlar",
              "radyoloji_sentetik": "Radyoloji — sentetik", "genel_sentetik": "Genel tıbbi — sentetik",
              "vakalar": "Gerçek vakalar (yalnızca sonişleme)"}


# ------------------------------------------------------------------ veri
def load_wav(path: Path) -> tuple[np.ndarray, int]:
    try:
        import soundfile as sf
        a, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return a.mean(axis=1), sr
    except Exception:
        with wave.open(str(path)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768, w.getframerate()


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


def manifest_set(man: Path) -> list[tuple[str, Path, str]]:
    """lhotse CutSet jsonl.gz (lhotse gerektirmeden): ses yolu + transkript."""
    if not man.is_file():
        return []
    out = []
    with gzip.open(man, "rt", encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            src = c["recording"]["sources"][0]["source"]
            text = " ".join(s["text"] for s in c.get("supervisions", []))
            p = Path(src)
            if not p.is_absolute():
                p = (ROOT / "training" / p).resolve()
            out.append((c["id"], p, text))
    return out


def collect_sets(names: list[str], limit: int) -> dict[str, list]:
    sets = {
        "fleurs": manifest_set(ROOT / "training" / "data" / "manifests" / "fleurs_test.jsonl.gz"),
        "radyoloji_gercek": numbered_set(ROOT / "data" / "radiology_test" / "audio",
                                         ROOT / "data" / "radiology_test" / "sentences.txt"),
        "radyoloji_sentetik": numbered_set(ROOT / "data" / "radiology_test" / "synthetic_audio",
                                           ROOT / "data" / "radiology_test" / "sentences.txt"),
        "genel_sentetik": numbered_set(ROOT / "tests" / "audio", ROOT / "tests" / "sentences_tr.txt"),
    }
    out = {}
    for n in names:
        if n == "vakalar":
            continue
        items = sets.get(n, [])
        if limit and len(items) > limit:  # sabit ve tekrarlanabilir alt küme
            step = len(items) / limit
            items = [items[int(i * step)] for i in range(limit)]
        if items:
            out[n] = items
    return out


# ------------------------------------------------------------------ ölçüm
def make_post():
    return MedicalPostProcessor.from_files([BUILTIN_LEXICON, RADIOLOGY_LEXICON], [BUILTIN_CORRECTIONS],
                                           fuzzy_files=[BUILTIN_LEXICON, RADIOLOGY_FUZZY],
                                           protected_files=[RADIOLOGY_KNOWN],
                                           general_files=[MED / "general_tr_words.txt"])


def aggregate(scores: list) -> dict:
    ref = sum(s.ref_words for s in scores)
    errs = sum(s.substitutions + s.deletions + s.insertions for s in scores)
    chars = sum(max(1, len(" ".join(a.ref for a in s.alignment if a.ref))) for s in scores)
    cer = sum(s.cer * max(1, len(" ".join(a.ref for a in s.alignment if a.ref))) for s in scores) / max(1, chars)
    th, tt = sum(s.term_hits for s in scores), sum(s.term_total for s in scores)
    return {"wer": errs / max(1, ref), "cer": cer, "ref_words": ref,
            "term_acc": (th / tt) if tt else None, "terms": tt}


def run_audio_set(name, items, raw_engine, app_engine, post, terms) -> dict:
    raw_scores, app_scores, audio_sec, t_app = [], [], 0.0, 0.0
    worst = []
    for i, (uid, path, ref) in enumerate(items):
        pcm, sr = load_wav(path)
        audio_sec += len(pcm) / sr
        raw = raw_engine.transcribe(pcm, sr)
        t0 = time.monotonic()
        hyp = post(app_engine.transcribe(pcm, sr))
        t_app += time.monotonic() - t0
        rs, aps = score(ref, raw, terms), score(ref, hyp, terms)
        raw_scores.append(rs)
        app_scores.append(aps)
        worst.append((aps.wer, uid, ref, hyp))
        if (i + 1) % 50 == 0:
            print(f"  {name}: {i + 1}/{len(items)}", flush=True)
    worst.sort(reverse=True)
    return {"n": len(items), "hours": audio_sec / 3600, "raw": aggregate(raw_scores), "app": aggregate(app_scores),
            "rtf": t_app / max(audio_sec, 1e-6),
            "worst": [{"id": u, "wer": round(w, 3), "ref": r, "hyp": h} for w, u, r, h in worst[:5]]}


def run_cases(post, terms) -> dict | None:
    files = sorted((ROOT / "tests" / "cases").glob("*.hyp.txt"))
    if not files:
        return None
    raw_scores, app_scores = [], []
    for f in files:
        ref = f.with_name(f.name.replace(".hyp.", ".ref.")).read_text(encoding="utf-8")
        hyp = f.read_text(encoding="utf-8")
        raw_scores.append(score(ref, hyp, terms))
        app_scores.append(score(ref, post(hyp), terms))
    return {"n": len(files), "hours": 0.0, "raw": aggregate(raw_scores), "app": aggregate(app_scores), "rtf": None,
            "worst": []}


# ------------------------------------------------------------------ rapor
def pct(x):
    return "—" if x is None else f"%{x * 100:.1f}"


def write_report() -> Path:
    runs = []
    res = OUT / "results.jsonl"
    if res.exists():
        runs = [json.loads(l) for l in res.read_text(encoding="utf-8").splitlines() if l.strip()]
    lines = ["# Model başarı raporu", "",
             "Her satır bir ölçüm çalıştırması. **Uygulama** = hotword + tıbbi sonişleme (kullanıcının gördüğü metin). "
             "Doğruluk = 1 − WER. Karşılaştırmada sayı ve birimler okunuşuna çevrilir.", ""]
    for s in SET_NAMES:
        rows = [(r, r["sets"][s]) for r in runs if s in r.get("sets", {})]
        if not rows:
            continue
        best = min(x["app"]["wer"] for _, x in rows)
        lines += [f"## {SET_TITLES[s]}", "",
                  "| Tarih | Model | Örnek | Ham WER | **Uygulama WER** | Doğruluk | CER | Terim isabeti | Hız |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r, x in rows:
            mark = " 🏆" if x["app"]["wer"] == best and len(rows) > 1 else ""
            speed = "—" if not x.get("rtf") else f"{1 / x['rtf']:.0f}× gerçek zaman"
            lines.append(f"| {r['date']} | {r['label']}{mark} | {x['n']} | {pct(x['raw']['wer'])} | "
                         f"**{pct(x['app']['wer'])}** | {pct(1 - x['app']['wer'])} | {pct(x['app']['cer'])} | "
                         f"{pct(x['app']['term_acc'])} | {speed} |")
        last = rows[-1][1]
        if last.get("worst"):
            lines += ["", f"<details><summary>Son çalıştırmada en çok hata yapılan örnekler ({rows[-1][0]['label']})"
                      "</summary>", ""]
            for w in last["worst"]:
                lines += [f"- **{w['id']}** (WER %{w['wer'] * 100:.0f})", f"  - doğru: {w['ref']}", f"  - çıktı: {w['hyp']}"]
            lines += ["", "</details>"]
        lines.append("")
    out = OUT / "RAPOR.md"
    OUT.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="model klasörü (model.json); varsayılan: ilk bulunan")
    ap.add_argument("--label", help="raporda görünecek ad (varsayılan: model adı)")
    ap.add_argument("--sets", default=",".join(SET_NAMES))
    ap.add_argument("--limit", type=int, default=0, help="set başına en fazla örnek (hızlı ölçüm)")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    if a.report_only:
        print(write_report())
        return 0

    model = ModelInfo.from_dir(Path(a.model)) if a.model else discover_models()[0]
    label = a.label or model.name
    names = [s.strip() for s in a.sets.split(",") if s.strip()]
    terms = {tr_lower(t) for f in (BUILTIN_LEXICON, RADIOLOGY_LEXICON) for t in read_lexicon(f) if " " not in t}
    post = make_post()
    run = {"date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "label": label, "model_dir": str(model.dir),
           "sets": {}}
    audio_sets = collect_sets(names, a.limit)
    if audio_sets:
        OUT.mkdir(exist_ok=True)
        hw = write_hotwords([BUILTIN_LEXICON, RADIOLOGY_LEXICON], OUT / "_hotwords.txt")
        raw_engine = load_engine(model, num_threads=4)
        app_engine = load_engine(model, num_threads=4, hotwords_file=str(hw), hotwords_score=2.0) \
            if model.spec.get("bpe_vocab") else raw_engine
        for name, items in audio_sets.items():
            print(f"{SET_TITLES[name]}: {len(items)} örnek…", flush=True)
            run["sets"][name] = run_audio_set(name, items, raw_engine, app_engine, post, terms)
            r = run["sets"][name]
            print(f"  ham WER {pct(r['raw']['wer'])} -> uygulama {pct(r['app']['wer'])}, "
                  f"terim {pct(r['app']['term_acc'])}, {1 / r['rtf']:.0f}× gerçek zaman")
    if "vakalar" in names:
        c = run_cases(post, terms)
        if c:
            run["sets"]["vakalar"] = c
            print(f"Gerçek vakalar: ham {pct(c['raw']['wer'])} -> uygulama {pct(c['app']['wer'])}")
    skipped = [n for n in names if n not in run["sets"]]
    if skipped:
        print("bulunamayan setler (atlandı):", ", ".join(skipped))
    OUT.mkdir(exist_ok=True)
    with (OUT / "results.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(run, ensure_ascii=False) + "\n")
    print("rapor:", write_report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
