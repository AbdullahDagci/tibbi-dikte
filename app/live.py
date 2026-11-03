"""Anlık yazım: kelimeler konuşurken yazılır, cümle sonunda düzeltilmiş metinle yalnızca farklı kısım güncellenir.

Akış modeli o an söylenen kelimeleri kısmi sonuç olarak verir; son kelime(ler) birkaç yüz ms boyunca değişebilir.
Bu yüzden yalnızca STABLE_SEC boyunca değişmeden kalan kelimeler yazılır (en son kelime için LAST_WORD_SEC).
Cümle bittiğinde (uç nokta) tıbbi sonişlemeden geçmiş metin gelir; yazılmış metinle ortak başlangıç korunur,
geri kalan silinip (Backspace) doğrusu yazılır: "beş yüz miligram " -> "500 mg ".
"""
from __future__ import annotations

import os
import time
from typing import Callable

STABLE_SEC = 0.45
LAST_WORD_SEC = 0.7
HISTORY_SEC = 3.0


class LiveWriter:
    def __init__(self, typer: Callable[[str], None], eraser: Callable[[int], None],
                 clock: Callable[[], float] = time.monotonic):
        self.typer, self.eraser, self.clock = typer, eraser, clock
        self.typed = ""   # bu cümle için imlece yazılmış metin
        self._hist: list[tuple[float, list[str]]] = []

    def _sync(self, target: str) -> None:
        common = os.path.commonprefix([self.typed, target])
        self.eraser(len(self.typed) - len(common))
        if len(target) > len(common):
            self.typer(target[len(common):])
        self.typed = target

    def _snapshot_before(self, t: float) -> list[str] | None:
        old = None
        for ts, words in self._hist:
            if ts <= t:
                old = words
            else:
                break
        return old

    @staticmethod
    def _common(a: list[str], b: list[str]) -> int:
        n = 0
        for x, y in zip(a, b):
            if x != y:
                break
            n += 1
        return n

    def update_partial(self, partial: str) -> None:
        now = self.clock()
        words = partial.split()
        self._hist.append((now, words))
        self._hist = [h for h in self._hist if h[0] >= now - HISTORY_SEC]
        old = self._snapshot_before(now - STABLE_SEC)
        if old is None:
            return
        n = self._common(old, words)
        if n == len(words) and n:  # en son kelime: daha uzun süre sabit kalmalı (hâlâ söyleniyor olabilir)
            older = self._snapshot_before(now - LAST_WORD_SEC)
            if older is None or self._common(older, words) < n:
                n -= 1
        target = " ".join(words[:n]) + (" " if n else "")
        if target.startswith(self.typed):
            if len(target) > len(self.typed):
                self._sync(target)
        elif not self.typed.startswith(target):
            self._sync(target)  # yazılmış bir kelime değişti: düzelt
        # target, typed'ın öneki ise (model kelime geri aldı) bekle; cümle sonunda düzeltilir

    def finalize(self, text: str) -> None:
        """Cümle sonu: yazılmış metni sonişlenmiş nihai metne çevir."""
        self._sync(text)
        self.typed = ""
        self._hist = []
