"""Doğruluk ölçümü: WER / CER / tıbbi terim isabeti ve kelime hizalaması (renkli fark gösterimi için).

Karşılaştırmadan önce iki metin de aynı biçime getirilir (küçük harf, noktalamasız, sayılar ve birimler
okunuşuyla): referans "500 mg" yazıp model "beş yüz miligram" dese de hata sayılmaz.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz.distance import Levenshtein

from .medical.postprocess import tr_lower

# Ham güven -> gerçekte doğru çıkma oranı. Ölçüm: Tibbi Türkçe v3 (w07), temperature_scale=2.0 (sherpa varsayılanı),
# 1.468 kelime (1.310'u yapay ses, 158'i gerçek rapor), aralık ortaları: %30-45 %20,0 · %45-60 %80,2 · %60-70 %94,4 ·
# %70-80 %98,1 · %80-90 %99,5 · %90-100 %100. Gerçek kayıtlar çoğaldıkça yeniden ölçülmeli (tools/confidence_calibration.py).
_ACCURACY_CURVE = ((0.0, 0.0), (0.375, 0.20), (0.525, 0.802), (0.65, 0.944), (0.75, 0.981), (0.85, 0.99))


def estimated_accuracy(raw_confidence: float) -> float:
    """Ham çözücü güvenini tahmini doğruluğa çevirir. Üst sınır %99: model hiçbir kelimeden kesin emin olamaz."""
    for (x0, y0), (x1, y1) in zip(_ACCURACY_CURVE, _ACCURACY_CURVE[1:]):
        if raw_confidence <= x1:
            return y0 + (max(raw_confidence, x0) - x0) / (x1 - x0) * (y1 - y0)
    return _ACCURACY_CURVE[-1][1]


_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_UNITS = {"mg": "miligram", "mcg": "mikrogram", "g": "gram", "kg": "kilogram", "ml": "mililitre", "dl": "desilitre",
          "cm": "santimetre", "mm": "milimetre", "mmhg": "milimetre cıva", "iu": "ünite", "meq": "miliekivalan",
          "dk": "dakika", "sn": "saniye"}


def _below_1000(n: int) -> list[str]:
    out = []
    h, r = divmod(n, 100)
    if h:
        out += ["yüz"] if h == 1 else [_ONES[h], "yüz"]
    t, o = divmod(r, 10)
    if t:
        out.append(_TENS[t])
    if o:
        out.append(_ONES[o])
    return out


def int_to_words(n: int) -> str:
    if n == 0:
        return "sıfır"
    words = []
    for value, name in ((10**9, "milyar"), (10**6, "milyon"), (1000, "bin")):
        q, n = divmod(n, value)
        if q:
            words += [name] if (q == 1 and name == "bin") else _below_1000(q) + [name]
    return " ".join(words + _below_1000(n))


def _num(tok: str) -> str:
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", tok):
        return int_to_words(int(tok.replace(".", "")))
    if re.fullmatch(r"\d+[.,]\d+", tok):
        a, b = re.split(r"[.,]", tok)
        return f"{int_to_words(int(a))} virgül {int_to_words(int(b))}"
    return int_to_words(int(tok)) if len(tok) < 13 else tok


_ORD_SOFT = {"dört": "dörd"}


def ordinal(words: str) -> str:
    """'iki' -> 'ikinci', 'dört' -> 'dördüncü', 'on' -> 'onuncu', 'altı' -> 'altıncı' (son kelimeye ek)."""
    parts = words.split()
    last = _ORD_SOFT.get(parts[-1], parts[-1])
    v = [c for c in last if c in "aeıioöuü"][-1]
    suffix = {"a": "ıncı", "ı": "ıncı", "e": "inci", "i": "inci", "o": "uncu", "u": "uncu", "ö": "üncü", "ü": "üncü"}[v]
    if last[-1] in "aeıioöuü":
        suffix = suffix[1:]
    parts[-1] = last + suffix
    return " ".join(parts)


def spoken_tokens(text: str) -> list[str]:
    """Puanlama için ortak biçim: 'TA 140/90, %94' -> ['ta','yüz','kırk','doksan','yüzde','doksan','dört']."""
    t = tr_lower(text).replace("’", "'")
    t = re.sub(r"%\s*(\d)", r"yüzde \1", t)
    t = re.sub(r"(\d)\s*/\s*(\d)", r"\1 \2", t)
    t = re.sub(r"(?<=\d)\s*(mmhg|mcg|meq|mg|kg|ml|dl|cm|mm|iu|dk|sn|g)'?(l[ıiuü]k[a-zçğıöşü]*|'[a-zçğıöşü]+)",
               lambda m: " " + _UNITS[m.group(1)] + m.group(2).lstrip("'"), t)
    t = re.sub(r"(?<=\d)\s*(mmhg|mcg|meq|mg|kg|ml|dl|cm|mm|iu|dk|sn|g)(?![a-zçğıöşü])",
               lambda m: " " + _UNITS[m.group(1)], t)
    # ekli sayı: "3'e" -> "üçe", "2'de" -> "ikide" (okunuşta ek sayıya bitişir)
    t = re.sub(r"(\d+)'([a-zçğıöşü]+)", lambda m: _num(m.group(1)).replace(" ", " ") + m.group(2), t)
    # sıra sayısı: "2. derece" -> "ikinci derece" (ardından küçük harfli kelime gelirse)
    t = re.sub(r"(?<![\d.,])(\d+)\.(?=\s+[a-zçğıöşü])", lambda m: ordinal(_num(m.group(1))), t)
    t = re.sub(r"\d+(?:[.,]\d+)*", lambda m: f" {_num(m.group(0))} ", t)
    t = t.replace("'", "")  # "bakım'a" = "bakıma", "EKG'de" = "ekgde": okunuşta ek kelimeye bitişir
    return re.findall(r"[a-zçğıöşüâîû0-9]+", t)


@dataclass
class AlignedWord:
    op: str          # "ok" | "sub" | "del" (referansta var, çıktıda yok) | "ins" (çıktıda fazladan)
    ref: str = ""
    hyp: str = ""


@dataclass
class Score:
    wer: float
    cer: float
    ref_words: int
    hyp_words: int
    substitutions: int
    deletions: int
    insertions: int
    term_hits: int = 0
    term_total: int = 0
    alignment: list[AlignedWord] = field(default_factory=list)
    missed_terms: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        """Kelime doğruluğu = 1 - WER (alt sınır 0)."""
        return max(0.0, 1.0 - self.wer)

    @property
    def term_accuracy(self) -> float | None:
        return self.term_hits / self.term_total if self.term_total else None


def align(ref: list[str], hyp: list[str]) -> list[AlignedWord]:
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    out: list[AlignedWord] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            out.append(AlignedWord("ok" if ref[i - 1] == hyp[j - 1] else "sub", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            out.append(AlignedWord("del", ref=ref[i - 1]))
            i -= 1
        else:
            out.append(AlignedWord("ins", hyp=hyp[j - 1]))
            j -= 1
    return out[::-1]


def score(reference: str, hypothesis: str, terms: set[str] | None = None) -> Score:
    ref, hyp = spoken_tokens(reference), spoken_tokens(hypothesis)
    al = align(ref, hyp)
    subs = sum(a.op == "sub" for a in al)
    dels = sum(a.op == "del" for a in al)
    ins = sum(a.op == "ins" for a in al)
    wer = (subs + dels + ins) / max(1, len(ref))
    r_chars, h_chars = " ".join(ref), " ".join(hyp)
    cer = Levenshtein.distance(r_chars, h_chars) / max(1, len(r_chars))
    s = Score(wer, cer, len(ref), len(hyp), subs, dels, ins, alignment=al)
    if terms:
        hyp_set = set(hyp)
        for w in ref:
            # terim + ek ("hepatosteatoz", "hepatosteatozu"): sözlükteki bir terimle başlayan referans kelimeleri
            if len(w) >= 6 and any(w.startswith(t) for t in terms if len(t) >= 6 and t[:3] == w[:3]):
                s.term_total += 1
                if w in hyp_set:
                    s.term_hits += 1
                else:
                    s.missed_terms.append(w)
    return s
