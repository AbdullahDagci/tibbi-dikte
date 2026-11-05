"""Sentetik (TTS) eğitim kliplerinin kalite kapısı.

TTS bazen kaçar (kısa cümleye 30 sn anlamsız ses), bazen erken keser ya da anlamsız ses üretir; bunlar eğitime
yanlış etiket olarak girer. Kapı yalnızca bariz bozukları eler: modelin henüz bilmediği tıbbi terimleri yanlış
duyması ret sebebi değildir (öğretilecek olan tam da odur), bu yüzden WER eşiği gevşektir.
"""
from __future__ import annotations

import random
import re

# Ölçülen Chatterbox Türkçe konuşma hızı: 10–19,5 karakter/sn (boşluk dahil); kaçan klip 2,9
MIN_CPS, MAX_CPS = 7.0, 24.0
# Sağlam ama terim yoğun klipte mevcut model %62'ye çıkıyor; anlamsız ses %90+. Kesilme ve kaçma ayrıca denetlenir.
MAX_WER = 0.75


def _tokens(s: str) -> list[str]:
    s = s.replace("İ", "i").replace("I", "ı").lower().replace("'", " ").replace("’", " ")
    return re.findall(r"[\wçğıöşüâîû%]+", s)


def word_errors(ref: str, hyp: str) -> tuple[int, int]:
    """(kelime düzeyinde düzenleme uzaklığı, referans kelime sayısı) — derlem WER'i için toplanır."""
    r, h = _tokens(ref), _tokens(hyp)
    prev = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
        prev = cur
    return prev[-1], len(r)


def word_error_rate(ref: str, hyp: str) -> float:
    e, n = word_errors(ref, hyp)
    return e / max(1, n)


def _ending_present(ref: str, hyp: str) -> bool:
    """Referansın son kelimesi hipotezin son üç kelimesinden birinde (ilk 4 harf) var mı."""
    r, h = _tokens(ref), _tokens(hyp)
    if not r:
        return True
    last = r[-1][:4]
    return any(t[:4] == last for t in h[-3:])


def accept(text: str, seconds: float, hyp: str | None = None, *, max_wer: float = MAX_WER) -> tuple[bool, str]:
    """(kabul, sebep). hyp: mevcut modelin klip transkripti (yoksa yalnızca süre denetlenir)."""
    cps = len(text) / max(seconds, 1e-3)
    if not MIN_CPS <= cps <= MAX_CPS:
        return False, f"süre {seconds:.1f} sn ({cps:.1f} karakter/sn)"
    if hyp is not None:
        w = word_error_rate(text, hyp)
        if w > max_wer:
            return False, f"WER {w:.0%}"
        if not _ending_present(text, hyp):
            return False, "son kelimeler eksik"
    return True, "tamam"


def shard(items: list, spec: str) -> list[tuple[int, object]]:
    """"i/n": paralel süreçlerden i'ncisinin payı (orijinal indeksleriyle). Boş: hepsi."""
    if not spec:
        return list(enumerate(items))
    i, n = (int(x) for x in spec.split("/"))
    return [(k, it) for k, it in enumerate(items) if k % n == i]


def pick_refs(candidates: list[tuple[str, float]], n: int, *, lo: float = 6.0, hi: float = 12.0,
              seed: int = 0) -> list[str]:
    """Ses klonlama referansları: süresi [lo, hi] olan adaylardan tekrarlanabilir rastgele n tane."""
    ok = sorted(p for p, d in candidates if lo <= d <= hi)
    random.Random(seed).shuffle(ok)
    return ok[:n]
