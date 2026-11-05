"""Eğitim hedefi metni: söylendiği gibi (sayılar yazıyla), mihu çıktı biçiminde."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from textnorm import normalize  # noqa: E402


@pytest.mark.parametrize("src,expected", [
    ("Hastaya 500 mg verildi", "Hastaya beş yüz miligram verildi."),
    ("3,5 cm'lik lezyon", "Üç virgül beş santimetrelik lezyon."),
    ("12 mm'den küçük", "On iki milimetreden küçük."),
    ("%30 darlık", "Yüzde otuz darlık."),
    # radyolog boyutu "çarpı" diye söyler; "x" etikete girerse TTS "iks" okur
    ("12x8 mm boyutlu", "On iki çarpı sekiz milimetre boyutlu."),
    ("12 x 8 x 6 mm", "On iki çarpı sekiz çarpı altı milimetre."),
    # omurga seviyelerinde tire okunmaz
    ("L4-L5 seviyesinde", "L dört L beş seviyesinde."),
    ("C5-6 düzeyinde", "C beş altı düzeyinde."),
    # sayı içermeyen tireli kelimeler korunur
    ("kompleks kistik-solid lezyon", "Kompleks kistik-solid lezyon."),
])
def test_normalize(src, expected):
    assert normalize(src, restore_case=True) == expected
