"""Eğitim transkriptlerini mihu modelinin çıktı biçimine getirir.

Model çıktısı: büyük/küçük harfli, noktalamalı, sayılar YAZIYLA ("yüz elli"). Sayıların rakama çevrilmesi
uygulamada damga (ITN) ile yapılır. Bu yüzden eğitim hedefleri de aynı biçimde olmalı; aksi hâlde ince ayar
modelin çıktı stilini bozar (ör. tamamen küçük harf, noktalamasız çıktı).
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_SCALES = [(10**12, "trilyon"), (10**9, "milyar"), (10**6, "milyon"), (1000, "bin")]


def _below_1000(n: int) -> list[str]:
    out = []
    h, r = divmod(n, 100)
    if h:
        out += (["yüz"] if h == 1 else [_ONES[h], "yüz"])
    t, o = divmod(r, 10)
    if t:
        out.append(_TENS[t])
    if o:
        out.append(_ONES[o])
    return out


def int_to_words(n: int) -> str:
    """Türkçe, boşluklu: 1000 -> 'bin', 2024 -> 'iki bin yirmi dört', 150 -> 'yüz elli'."""
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + int_to_words(-n)
    words = []
    for value, name in _SCALES:
        q, n = divmod(n, value)
        if q:
            words += ([name] if (q == 1 and name == "bin") else _below_1000(q) + [name]) if q < 1000 \
                else int_to_words(q).split() + [name]
    words += _below_1000(n)
    return " ".join(words)


def number_to_words(tok: str) -> str:
    """'3,5' / '3.5' -> 'üç virgül beş'; '1.000' (binlik) -> 'bin'; '%10' -> 'yüzde on'."""
    pct = tok.startswith("%")
    tok = tok.lstrip("%")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", tok):  # binlik ayırıcı
        out = int_to_words(int(tok.replace(".", "")))
    elif re.fullmatch(r"\d+[.,]\d+", tok):
        a, b = re.split(r"[.,]", tok)
        frac = " ".join(["sıfır"] * (len(b) - len(b.lstrip("0")))) + (" " if b.lstrip("0") and b.startswith("0") else "")
        out = f"{int_to_words(int(a))} virgül {frac}{int_to_words(int(b)) if b.lstrip('0') else ''}".strip()
    else:
        out = int_to_words(int(tok))
    return f"yüzde {out}" if pct else out


_NUM_RE = re.compile(r"%?\d+(?:[.,]\d+)*")
# Kısaltılmış birimler sesli okunuşa (ses "miligram" der, "mg" değil); ekler korunur: "mg'lık" -> "miligramlık"
_UNITS = {"mg": "miligram", "mcg": "mikrogram", "µg": "mikrogram", "ng": "nanogram", "g": "gram", "kg": "kilogram",
          "ml": "mililitre", "dl": "desilitre", "cm": "santimetre", "mm": "milimetre", "mmHg": "milimetre cıva",
          "IU": "ünite", "mEq": "miliekivalan", "mmol": "milimol"}
# yalnızca bir sayıdan hemen sonra; ek yalnızca kesme işaretiyle ya da -lık/-lik/-luk/-lük
_UNIT_RE = re.compile(r"(?<=\d)\s*(" + "|".join(sorted(map(re.escape, _UNITS), key=len, reverse=True))
                      + r")('[a-zçğıöşü]+|l[ıiuü]k[a-zçğıöşü]*)?(?![\wçğıöşüÇĞİÖŞÜ])")
_SPACE_RE = re.compile(r"\s+")


def tr_capitalize(s: str) -> str:
    if not s:
        return s
    first = {"i": "İ", "ı": "I"}.get(s[0], s[0].upper())
    return first + s[1:]


def normalize(text: str, *, restore_case: bool = False) -> str:
    """Eğitim hedefi metni.
    restore_case: kaynak tamamen küçük harf / noktalamasızsa cümle başını büyüt, sona nokta koy
    (modelin cümle başı büyük harf + son nokta alışkanlığını korumak için)."""
    t = unicodedata.normalize("NFC", text)
    t = t.replace("’", "'").replace("`", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"(\d)\s*/\s*(\d)", r"\1 \2", t)  # "140/90" -> "140 90" (söylendiği gibi)
    t = re.sub(r"(?<=\d)\s*[xX×]\s*(?=\d)", " çarpı ", t)  # "12x8 mm" -> "12 çarpı 8 mm"
    t = re.sub(r"(?<=\d)-(?=\w)|(?<=\w)-(?=[A-Za-z]?\d)", " ", t)  # "L4-L5", "C5-6", "3-4 mm": tire okunmaz
    t = _UNIT_RE.sub(lambda m: " " + _UNITS[m.group(1)] + (m.group(2) or "").replace("'", ""), t)
    t = _NUM_RE.sub(lambda m: f" {number_to_words(m.group(0))} ", t)
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)  # noktalama öncesi boşluk
    t = _SPACE_RE.sub(" ", t).strip()
    if restore_case and t:
        t = tr_capitalize(t)
        if t[-1] not in ".!?":
            t += "."
    return t


# ------------------------------------------------------------------ ISSAI TSC onarımı
# Kaynak metin küçük harfe çevrilirken iki bozulma oluşmuş (satırların ~%4'ü ve ~%7'si):
#   * "İ" -> "i" + boşluk:            "i srail", "i nsan hakları", "i yi akşamlar"
#   * kesme işareti boşluğa dönmüş:    "türkiye nin", "ankara nın", "ege deki"
# Kesme işareti Türkçede yalnızca özel isim/kısaltma/sayıdan sonra gelir -> önceki kelime büyük harfle başlatılır.
# Gerçek kelime de olabilen ekler ("ya", "ye", "da", "de", "a", "e" ...) belirsiz olduğu için dokunulmaz.
_TSC_SUFFIXES = {"nin", "nın", "nun", "nün", "ın", "in", "un", "ün", "dan", "den", "tan", "daki", "deki", "taki",
                 "teki", "nda", "nde", "ndan", "nden", "ndaki", "ndeki", "yi", "yı", "yu", "yü"}
_NUMBER_WORDS = set(_ONES + _TENS) - {""} | {"yüz", "bin", "milyon", "milyar", "trilyon", "sıfır"}
_TR_WORD_RE = re.compile(r"[a-zçğıöşüâîû]+")
_TRAIL_PUNCT_RE = re.compile(r"^(.*?)([.,!?;:]*)$")


def _tr_lower(s: str) -> str:
    """Türkçe küçük harf: str.lower() "İ"yi "i̇" (birleşik nokta) yapar."""
    return s.replace("İ", "i").replace("I", "ı").lower()


def tsc_vocab(texts) -> Counter[str]:
    """Korpustaki bozulmamış kelime sıklıkları (bölünmüş "İ" kararını vermek için). Tek başına "i"den hemen
    sonra gelen parça sayılmaz: hep bölünen kelimelerin parçası ("mparatorluğu") kelime gibi görünmesin."""
    c: Counter[str] = Counter()
    for t in texts:
        prev = ""
        for tok in t.split():
            tok = tok.strip(".,!?;:")
            if prev != "i":
                c[tok] += 1
            prev = tok
    return c


def repair_tsc(text: str, vocab, min_count: int = 3) -> str:
    """Tek başına "i": birleşik hâli ("i"+sonraki) korpusta kelimeyse ya da sonraki parça kelime değilse bölünmüş
    "İ"dir; aksi hâlde kopmuş belirtme ekidir ("İsrail i en geç" -> "İsrail'i en geç")."""
    def known(w: str) -> bool:
        return vocab.get(w, 0) >= min_count

    def attach(prev: str, suffix: str) -> str:
        if prev in _NUMBER_WORDS:
            return prev + suffix  # sayılar yazıyla: "üçün" (kesme işareti yok)
        return tr_capitalize(prev) + "'" + suffix

    toks = text.split()
    out: list[str] = []
    i = 0
    while i < len(toks):
        core, punct = _TRAIL_PUNCT_RE.match(toks[i]).groups()
        prev_ok = bool(out) and "'" not in out[-1] and _TR_WORD_RE.fullmatch(_tr_lower(out[-1])) is not None
        if core == "i" and not punct and i + 1 < len(toks):
            nxt_core, nxt_punct = _TRAIL_PUNCT_RE.match(toks[i + 1]).groups()
            if _TR_WORD_RE.fullmatch(nxt_core) and len(nxt_core) >= 2:
                if known("i" + nxt_core) or not (known(nxt_core) and prev_ok):
                    out.append("İ" + nxt_core + nxt_punct)
                    i += 2
                    continue
                out[-1] = attach(out[-1], "i")
                i += 1
                continue
        if core in _TSC_SUFFIXES and prev_ok:
            out[-1] = attach(out[-1], core) + punct
            i += 1
            continue
        out.append(toks[i])
        i += 1
    return " ".join(out)


def looks_uncased(texts: list[str]) -> bool:
    """Bir veri setinin transkriptleri büyük harf/noktalama içermiyor mu?"""
    sample = texts[:500]
    upper = sum(any(c.isupper() for c in s) for s in sample)
    punct = sum(any(c in ".,?!" for c in s) for s in sample)
    return upper < 0.1 * len(sample) and punct < 0.1 * len(sample)


if __name__ == "__main__":
    for s in ["Hastaya 500 mg verildi", "TA 140/90, nabız 92", "%94 satürasyon", "3,5 cm lezyon", "1.000 mg", "2024 yılında",
              "akciğer grafisi normal"]:
        print(f"{s!r:35} -> {normalize(s, restore_case=True)!r}")
