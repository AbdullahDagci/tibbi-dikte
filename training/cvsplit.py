"""Common Voice eğitim bölümü: train.tsv doğrulanmış verinin yalnızca küçük bir kısmıdır (CV17 TR: 35 bin / 114 bin).
Eğitim = validated − (dev ∪ test); hem klip hem cümle düzeyinde ayrılır (aynı cümlenin başka bir okuması da sızıntıdır).
"""
from __future__ import annotations

import re


def _key(sentence: str) -> str:
    s = sentence.replace("İ", "i").replace("I", "ı").lower()
    return " ".join(re.findall(r"[\wçğıöşüâîû]+", s))


def cv_train_rows(validated: list[dict], dev: list[dict], test: list[dict]) -> list[dict]:
    held = dev + test
    held_paths = {r["path"] for r in held}
    held_sents = {_key(r["sentence"]) for r in held}
    return [r for r in validated if r["path"] not in held_paths and _key(r["sentence"]) not in held_sents]
