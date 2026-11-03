"""Rapor metinlerinden bağlamsal düzeltme dil modeli (kelime 3-gram) kurar.

Girdi: bir klasör (alt klasörler dahil) — .txt (UTF-8), .csv, .xlsx dosyaları. CSV/XLSX'te en uzun metin
sütunu rapor metni kabul edilir (--column ile seçilebilir).
Çıktı: app/medical/context_lm.json.gz (uygulamaya gömülür) — yalnızca en az --min-count kez geçen
n-gramlar tutulur; tek bir rapora özgü ifadeler (isim, numara vb.) modele girmez.

Metinler modelin ÇIKTI biçimine getirilir (küçük harf, noktalamasız, sayılar yazıyla), çünkü düzeltme
ITN'den önce, ham model çıktısı üzerinde yapılır.

  python tools/build_context_lm.py data/reports --min-count 3 [--eval]
  --eval: metinlerin %5'ini ayırıp yapay ses-benzeri hatalarla düzeltme isabetini ölçer ve eşik önerir.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.medical.context import BOS, EOS, ContextCorrector, ContextLM  # noqa: E402
from app.scoring import spoken_tokens  # noqa: E402

OUT = ROOT / "app" / "medical" / "context_lm.json.gz"


def read_texts(src: Path, column: str | None) -> list[str]:
    texts: list[str] = []
    files = [src] if src.is_file() else sorted(p for p in src.rglob("*") if p.is_file())
    for f in files:
        ext = f.suffix.lower()
        if ext == ".txt":
            texts.append(f.read_text(encoding="utf-8", errors="replace"))
        elif ext == ".csv":
            with f.open(encoding="utf-8", errors="replace", newline="") as fh:
                rows = list(csv.reader(fh, delimiter=";" if ";" in fh.readline() else ","))
            texts += _pick_column(rows, column)
        elif ext in (".xlsx", ".xlsm"):
            import openpyxl
            ws = openpyxl.load_workbook(f, read_only=True).active
            rows = [[("" if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]
            texts += _pick_column(rows, column)
    return texts


def _pick_column(rows: list[list[str]], column: str | None) -> list[str]:
    if not rows:
        return []
    header = rows[0]
    if column and column in header:
        idx = header.index(column)
    else:  # ortalama metin uzunluğu en büyük sütun
        n = max(len(r) for r in rows)
        lens = [sum(len(r[i]) for r in rows[1:] if i < len(r)) for i in range(n)]
        idx = max(range(n), key=lambda i: lens[i])
    return [r[idx] for r in rows[1:] if idx < len(r) and r[idx].strip()]


def sentences(texts: list[str]) -> list[list[str]]:
    out = []
    for t in texts:
        for s in re.split(r"(?<=[.!?:;])\s+|\n+|•", t):
            toks = spoken_tokens(s)
            if len(toks) >= 2:
                out.append(toks)
    return out


def count(sents: list[list[str]], min_count: int) -> dict:
    uni, bi, tri = Counter(), Counter(), Counter()
    for s in sents:
        seq = [BOS, BOS] + s + [EOS]
        uni.update(seq[2:])
        for i in range(2, len(seq)):
            bi[f"{seq[i - 1]} {seq[i]}"] += 1
            tri[f"{seq[i - 2]} {seq[i - 1]} {seq[i]}"] += 1
    uni[BOS] = len(sents)
    bi.update({f"{BOS} {BOS}": len(sents)})
    keep = lambda c: {k: v for k, v in c.items() if v >= min_count}  # noqa: E731
    tri_k = keep(tri)
    bi_k = keep(bi)
    for k in tri_k:  # 3-gram olasılığı için bağlam 2-gramı mutlaka bulunmalı
        ctx = k.rsplit(" ", 1)[0]
        bi_k.setdefault(ctx, bi[ctx])
    return {"uni": keep(uni) | {BOS: uni[BOS]}, "bi": bi_k, "tri": tri_k}


_SWAPS = [("a", "ı"), ("e", "i"), ("ı", "i"), ("u", "ü"), ("o", "ö"), ("a", "e"), ("d", "t"), ("b", "p"),
          ("l", "n"), ("k", "ğ"), ("s", "z")]


def corrupt(word: str, rnd: random.Random) -> str:
    """Ses tanıma benzeri hata: ünlü/ünsüz karışması (özellikle son hecede: bacağa -> bacağı)."""
    cands = [(i, a, b) for i, ch in enumerate(word) for a, b in _SWAPS for x, y in ((a, b), (b, a)) if ch == x
             and i >= len(word) // 2]
    if not cands:
        return word
    i, a, b = rnd.choice(cands)
    return word[:i] + (b if word[i] == a else a) + word[i + 1:]


def evaluate(lm_data: dict, held: list[list[str]], seed: int = 0) -> None:
    lm = ContextLM(lm_data)
    rnd = random.Random(seed)
    print("\neşik  düzeltilen-hata  bozulan-doğru  (yapay hata oranı %10)")
    for th in (3.0, 4.0, 5.0, 6.0, 8.0):
        cc = ContextCorrector(lm, threshold=th)
        fixed = broken = errors = correct_words = 0
        for s in held[:3000]:
            noisy = [corrupt(w, rnd) if len(w) >= 4 and rnd.random() < 0.10 else w for w in s]
            out = cc(" ".join(noisy)).split()
            if len(out) != len(s):
                continue
            for ref, n, o in zip(s, noisy, out):
                if n != ref:
                    errors += 1
                    fixed += o == ref
                else:
                    correct_words += 1
                    broken += o != ref
        print(f"{th:4.1f}  %{100 * fixed / max(errors, 1):5.1f}           %{100 * broken / max(correct_words, 1):.2f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--column")
    ap.add_argument("--min-count", type=int, default=3)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--eval", action="store_true")
    a = ap.parse_args()
    texts = read_texts(Path(a.src), a.column)
    sents = sentences(texts)
    print(f"{len(texts)} metin, {len(sents)} cümle, {sum(map(len, sents))} kelime")
    if a.eval:
        rnd = random.Random(1)
        rnd.shuffle(sents)
        k = max(1, len(sents) // 20)
        held, train = sents[:k], sents[k:]
        evaluate(count(train, a.min_count), held)
    data = count(sents, a.min_count)
    with gzip.open(a.out, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    size = Path(a.out).stat().st_size / 1e6
    print(f"-> {a.out}  ({len(data['uni'])} kelime, {len(data['bi'])} 2-gram, {len(data['tri'])} 3-gram, {size:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
