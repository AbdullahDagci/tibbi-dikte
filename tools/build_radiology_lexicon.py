"""rad_dict.xlsx (rapor kelime sıklıkları) -> temizlenmiş radyoloji sözlüğü.

Çıktılar:
  app/medical/radiology_terms_tr.txt  alana özgü terimler (hotword + bulanık düzeltme), belge sıklığına göre
  app/medical/radiology_fuzzy_tr.txt  bunun yalnızca alana özgü (genel Türkçede olmayan) alt kümesi: bulanık düzeltme
  data/radiology_vocab.tsv            temizlenmiş tüm kelimeler + sıklıklar (eğitim metni seçimi/ağırlığı için)

Temizlik:
  - birim yapışıkları atılır (cmden, mmlik, mgsi …)
  - baştaki kayıp İ/I düzeltilir (ncelemesinde -> incelemesinde)
  - ASCII yazımlar Türkçe karşılığına birleştirilir (fibroglanduler -> fibroglandüler)
  - yazım hataları, 1 harf uzaklıktaki çok daha sık kelimeye birleştirilir (lzyon -> lezyon)
  - alana özgülük: genel Türkçe sıklık listesine göre (--general, ör. FrequencyWords tr_50k.txt)

Kullanım: python tools/build_radiology_lexicon.py rad_dict.xlsx --general tr_50k.txt [--top 800]
"""
import argparse
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.medical.postprocess import tr_lower  # noqa: E402

VOWELS = set("aeıioöuüâîû")
OK_CLUSTERS = {"tr", "kr", "pr", "bl", "br", "fl", "fr", "gr", "pl", "sp", "st", "sk", "sl", "kl", "gl",
               "ps", "sc", "ch", "th", "ph", "sh", "dr", "sf", "sn", "sm", "kv", "tw", "sv"}
UNIT_GLUE = re.compile(r"^(cm|mm|mg|mrg|ml|usg|bt|mr)[a-zçğıöşü]{1,5}$")
# Genel sözlükte bulunmayan, ASCII yazılmış sık terimlerin doğru biçimi (kök -> doğru kök)
MANUAL_STEMS = {"siniflama": "sınıflama", "konfigurasyon": "konfigürasyon", "fibroglanduler": "fibroglandüler",
                "glanduler": "glandüler", "trabekuler": "trabeküler"}
FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def bad_start(w: str) -> bool:
    return len(w) > 2 and w[0] not in VOWELS and w[1] not in VOWELS and w[:2] not in OK_CLUSTERS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--general", required=True, help="genel Türkçe kelime sıklık listesi: 'kelime sayı' satırları")
    ap.add_argument("--top", type=int, default=800, help="hotword/sözlüğe girecek terim sayısı")
    ap.add_argument("--min-ratio", type=float, default=3000.0, help="rapor/genel sıklık oranı eşiği")
    a = ap.parse_args()

    tf: dict[str, int] = defaultdict(int)
    df: dict[str, int] = defaultdict(int)
    ws = openpyxl.load_workbook(a.xlsx, read_only=True).active
    for w, t, d in ws.iter_rows(min_row=2, values_only=True):
        if isinstance(w, str) and w.strip():
            w = tr_lower(w.strip())
            tf[w] += int(t or 0)
            df[w] = max(df[w], int(d or 0))
    n_raw = len(tf)

    general: dict[str, int] = {}
    for line in Path(a.general).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            general[tr_lower(parts[0])] = int(parts[1])

    def merge(src: str, dst: str) -> None:
        tf[dst] += tf.pop(src)
        df[dst] = max(df.get(dst, 0), df.pop(src))

    # 1) birim yapışıkları
    dropped = [w for w in tf if UNIT_GLUE.match(w)]
    for w in dropped:
        tf.pop(w), df.pop(w)
    # 2) kayıp baş harf (İ/I)
    fixed_start = 0
    for w in [w for w in tf if bad_start(w)]:
        for cand in ("i" + w, "ı" + w):
            if cand in tf or cand in general:
                if cand not in tf:
                    tf[cand], df[cand] = 0, 0
                merge(w, cand)
                fixed_start += 1
                break
    # 3) ASCII / yanlış Türkçe karakterli yazımlar: genel sözlükteki yazım tercih edilir, yoksa en sık olan
    gen_fold: dict[str, str] = {}
    for g in sorted(general, key=lambda x: general[x]):
        gen_fold[g.translate(FOLD)] = g
    groups: dict[str, list[str]] = defaultdict(list)
    for w in tf:
        groups[w.translate(FOLD)].append(w)
    folded = 0
    for key, ws_ in groups.items():
        best = gen_fold.get(key) or max(ws_, key=lambda x: tf[x])
        if best not in tf:
            tf[best], df[best] = 0, 0
        for w in ws_:
            if w != best:
                merge(w, best)
                folded += 1
    for w in list(tf):
        for bad, good in MANUAL_STEMS.items():
            stem = bad if w.startswith(bad) else good if w.startswith(good) else None
            if stem:
                suffix = w[len(stem):]
                last_vowel = [c for c in good if c in VOWELS][-1]
                if last_vowel in "aıou":  # büyük ünlü uyumu: ek ünlüsü kalınlaşır (sınıflamasi -> sınıflaması)
                    suffix = suffix.translate(str.maketrans("ie", "ıa"))
                fixed = good + suffix
                if fixed == w:
                    break
                if fixed not in tf:
                    tf[fixed], df[fixed] = 0, 0
                merge(w, fixed)
                break
    # 4) yazım hataları: 1 harf uzaklıkta ve en az 20 kat sık bir kelime varsa
    words = sorted(tf, key=lambda x: -tf[x])
    typos = 0
    for w in sorted(tf, key=lambda x: tf[x]):
        if w not in tf or len(w) < 5 or w in general:
            continue
        for cand in words:
            if cand == w or cand not in tf or tf[cand] < 20 * tf[w]:
                if cand in tf and tf[cand] < 20 * tf[w]:
                    break
                continue
            # ek ilişkisi (lezyon/lezyonu) yazım hatası değildir: önek olan çiftler atlanır
            if cand.startswith(w) or w.startswith(cand) or cand[:-1] == w[:-1]:
                continue
            if abs(len(cand) - len(w)) <= 1 and Levenshtein.distance(cand, w, score_cutoff=1) <= 1:
                merge(w, cand)
                typos += 1
                break

    # 5) alana özgülük
    tot_r = sum(tf.values())
    tot_g = sum(general.values())
    def ratio(w: str) -> float:
        g = general.get(w, 0)
        return (tf[w] / tot_r) / ((g + 1) / tot_g)
    remaining = sorted(tf, key=lambda x: -df[x])
    domain = [w for w in remaining if len(w) >= 5 and not bad_start(w) and ratio(w) >= a.min_ratio]

    vocab = ROOT / "data" / "radiology_vocab.tsv"
    vocab.parent.mkdir(parents=True, exist_ok=True)
    with vocab.open("w", encoding="utf-8") as f:
        f.write("kelime\tterim_sikligi\tbelge_sikligi\talan_orani\n")
        for w in remaining:
            f.write(f"{w}\t{tf[w]}\t{df[w]}\t{ratio(w):.1f}\n")
    out = ROOT / "app" / "medical" / "radiology_terms_tr.txt"
    top = domain[:a.top]
    out.write_text(
        "# Radyoloji terimleri — rad_dict.xlsx'ten otomatik üretildi (tools/build_radiology_lexicon.py).\n"
        "# Rapor belge sıklığına göre sıralı. Elle düzenlemeyin; kaynak listeyi güncelleyip yeniden üretin.\n"
        + "\n".join(top) + "\n", encoding="utf-8")
    # Bulanık düzeltme hedefleri: genel Türkçe sözlükte HİÇ geçmeyen terimler (doğru bir kelimeyi başka bir
    # doğru kelimeye çevirmemek için: "milimetrelik" -> "milimetrik", "değişiklikler" -> "değişikliklere" gibi)
    gen_set = {g for g in general if len(g) >= 5}
    def has_general_stem(w: str) -> bool:  # "değişikliklere" -> "değişiklik", "hatlarında" -> "hatları"
        return any(w[:k] in gen_set for k in range(max(5, len(w) - 6), len(w) + 1))
    fuzzy = [w for w in top if not has_general_stem(w)]
    # Koruma listesi: raporlarda gerçekten geçen tüm (temizlenmiş) kelimeler doğru kabul edilir, değiştirilmez
    known = [w for w in remaining if tf[w] >= 3 and not bad_start(w)]
    (ROOT / "app" / "medical" / "radiology_known_tr.txt").write_text(
        "# Raporlarda geçen kelimeler — bulanık düzeltme bunları DEĞİŞTİRMEZ (otomatik).\n"
        + "\n".join(known) + "\n", encoding="utf-8")
    print(f"koruma listesi: {len(known)}")
    (ROOT / "app" / "medical" / "radiology_fuzzy_tr.txt").write_text(
        "# Bulanık düzeltme hedefleri — radiology_terms_tr.txt'nin genel Türkçede geçmeyen alt kümesi (otomatik).\n"
        + "\n".join(fuzzy) + "\n", encoding="utf-8")
    print(f"bulanık düzeltme hedefi: {len(fuzzy)}")
    print(f"ham {n_raw} -> temiz {len(tf)} (birim {len(dropped)}, baş harf {fixed_start}, ascii {folded}, "
          f"yazım {typos}); alana özgü {len(domain)}, yazılan {len(top)}")
    print("ilk 40:", ", ".join(top[:40]))
    print("eşik altı sık kelimeler (genel Türkçe sayıldı):",
          ", ".join(w for w in remaining[:60] if w not in domain)[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
