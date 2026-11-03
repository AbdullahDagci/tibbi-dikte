"""Bağlamsal düzeltme mekanizması (küçük, elle yazılmış rapor benzeri derlemle)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from build_context_lm import count, sentences  # noqa: E402

from app.medical.context import ContextCorrector, ContextLM  # noqa: E402

CORPUS = [
    "Sol bacağa yayılan ağrı ve uyuşma, siyatik şüphesi.",
    "Sağ bacağa yayılan ağrı mevcut.",
    "Sol bacağa yayılan ağrı nedeniyle tetkik edildi.",
    "Bel ağrısı ve sol bacağa yayılan uyuşma.",
    "Sol L5 sinir kökü belirgin bası altındadır.",
    "Sağ L5 sinir kökü bası altındadır.",
    "Sol S1 sinir kökü belirgin bası altındadır.",
    "Lomber lordoz düzleşmiştir.",
    "Lomber lordoz korunmuştur.",
    "Lomber lordoz düzleşmiştir, korpus köşe sivrileşmeleri izlenmiştir.",
    "Hastanın bacağı ödemlidir.",
] * 3


@pytest.fixture(scope="module")
def cc():
    return ContextCorrector(ContextLM(count(sentences(CORPUS), 2)), threshold=4.0)


@pytest.mark.parametrize("src,expected", [
    ("sol bacağı yayılan ağrı ve uyuşma", "sol bacağa yayılan ağrı ve uyuşma"),
    ("Sol bacağı yayılan ağrı", "Sol bacağa yayılan ağrı"),
    ("lomber lordoz düzleşmiştir", "lomber lordoz düzleşmiştir"),          # doğruya dokunma
    ("hastanın bacağı ödemlidir", "hastanın bacağı ödemlidir"),             # bağlamda doğru olan "bacağı"
    ("EKG normal", "EKG normal"),                                           # kısaltma
])
def test_context(cc, src, expected):
    assert cc(src) == expected
