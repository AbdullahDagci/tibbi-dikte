"""Bağlamsal kelime düzeltme: rapor metinlerinden kurulan kelime 3-gram dil modeliyle.

Ses hatalı olsa bile çevre kelimelere bakarak düzeltir: "sol bacağı yayılan" -> "sol bacağa yayılan".
Yalnızca yazımca çok yakın adaylar arasından seçer (ilk iki harf aynı, en fazla 1-2 harf farkı) ve
ancak aday belirgin biçimde daha olası ise değiştirir — kelime uydurmaz, emin değilse dokunmaz.

Model dosyası: tools/build_context_lm.py ile rapor metinlerinden üretilir (gzip JSON).
"""
from __future__ import annotations

import gzip
import json
import math
import re
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from .postprocess import tr_capitalize, tr_lower, tr_upper

_WORD_RE = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]+")
BOS, EOS = "<s>", "</s>"


class ContextLM:
    """Basit geri çekilmeli (stupid backoff) kelime 3-gram modeli."""

    def __init__(self, data: dict):
        self.uni: dict[str, int] = data["uni"]
        self.bi: dict[str, int] = data["bi"]
        self.tri: dict[str, int] = data["tri"]
        self.total = max(1, sum(self.uni.values()))
        self.vsize = len(self.uni) + 1

    @classmethod
    def load(cls, path: Path) -> "ContextLM":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return cls(json.load(f))

    def logp(self, w: str, u: str, v: str) -> float:
        t = self.tri.get(f"{u} {v} {w}")
        if t:
            return math.log(t / self.bi[f"{u} {v}"])
        b = self.bi.get(f"{v} {w}")
        if b:
            return math.log(0.4) + math.log(b / self.uni.get(v, b))
        return math.log(0.16) + math.log((self.uni.get(w, 0) + 0.5) / (self.total + self.vsize))


class ContextCorrector:
    def __init__(self, lm: ContextLM, *, threshold: float = 5.0, edit_penalty: float = 2.5, min_count: int = 3,
                 protected: set[str] | None = None):
        self.lm = lm
        self.threshold = threshold
        self.edit_penalty = edit_penalty
        self.protected = protected or set()
        self._index: dict[str, list[str]] = {}
        for w, c in lm.uni.items():
            if c >= min_count and len(w) >= 3 and w not in (BOS, EOS):
                self._index.setdefault(w[:2], []).append(w)

    @classmethod
    def from_file(cls, path: Path, **kw) -> "ContextCorrector | None":
        return cls(ContextLM.load(path), **kw) if path.is_file() else None

    def _candidates(self, w: str) -> list[tuple[str, int]]:
        limit = 1 if len(w) <= 6 else 2
        out = [(w, 0)]
        for c in self._index.get(w[:2], ()):
            if c != w and abs(len(c) - len(w)) <= limit:
                d = Levenshtein.distance(w, c, score_cutoff=limit)
                if d <= limit:
                    out.append((c, d))
        return out

    def _score(self, c: str, u: str, v: str, x: str, y: str) -> float:
        lm = self.lm
        return lm.logp(c, u, v) + lm.logp(x, v, c) + lm.logp(y, c, x)

    def __call__(self, text: str) -> str:
        spans = list(_WORD_RE.finditer(text))
        if not spans:
            return text
        words = [tr_lower(m.group(0)) for m in spans]
        fixed = list(words)
        for i, w in enumerate(words):
            orig = spans[i].group(0)
            if len(w) < 3 or w in self.protected or (orig.isupper() and len(orig) > 1):
                continue  # kısa kelime, korunan terim veya kısaltma (EKG, MR)
            u = fixed[i - 2] if i >= 2 else BOS
            v = fixed[i - 1] if i >= 1 else BOS
            x = words[i + 1] if i + 1 < len(words) else EOS
            y = words[i + 2] if i + 2 < len(words) else EOS
            base = self._score(w, u, v, x, y)
            best, best_s = w, base
            for c, d in self._candidates(w):
                if c == w:
                    continue
                s = self._score(c, u, v, x, y) - self.edit_penalty * d
                if s > best_s:
                    best, best_s = c, s
            if best != w and best_s - base >= self.threshold:
                fixed[i] = best
        if fixed == words:
            return text
        out, pos = [], 0
        for m, old, new in zip(spans, words, fixed):
            out.append(text[pos:m.start()])
            o = m.group(0)
            out.append(o if new == old else tr_upper(new) if o.isupper() and len(o) > 1
                       else tr_capitalize(new) if o[:1].isupper() else new)
            pos = m.end()
        out.append(text[pos:])
        return "".join(out)
