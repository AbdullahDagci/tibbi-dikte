"""Gerçek kullanıcı denemesi (lomber MR): model çıktısı -> sonişleme, referansa yakınsamalı."""
from pathlib import Path

import pytest

from app.medical.postprocess import MedicalPostProcessor

M = Path(__file__).resolve().parent.parent / "app" / "medical"


@pytest.fixture(scope="module")
def pp():
    return MedicalPostProcessor.from_files(
        [M / "lexicon_tr.txt", M / "radiology_terms_tr.txt"], [M / "corrections_tr.tsv"],
        fuzzy_files=[M / "lexicon_tr.txt", M / "radiology_fuzzy_tr.txt"],
        protected_files=[M / "radiology_known_tr.txt"], use_itn=False)


@pytest.mark.parametrize("src,expected", [
    ("Bulgular lomber lordos düzleşmiştir.", "Bulgular lomber lordoz düzleşmiştir."),
    ("L4 L5 disk sinyal inten sitesi T2 sekanslar da dejenerasyona sekonder azalmıştır.",
     "L4-L5 disk sinyal intensitesi T2 sekanslarda dejenerasyona sekonder azalmıştır."),
    ("L4 L5 seviyesinde sol para santralin ekstride her niyet disk mevcuttur.",
     "L4-L5 seviyesinde sol parasantralin ekstrüde hernie disk mevcuttur."),
    ("Son L5 sinir kökü belirgin bası altındadır", "Sol L5 sinir kökü belirgin bası altındadır"),
    ("spinal kanal genişliği ve nöral noramenler normal", "spinal kanal genişliği ve nöral foramenler normal"),
    # yanlış birleştirme yapılmamalı
    ("pulmoner arter dallarında dolum defekti", "pulmoner arter dallarında dolum defekti"),
    ("son kontrol tetkiki", "son kontrol tetkiki"),
])
def test_spine_report(pp, src, expected):
    assert pp(src) == expected


def test_voice_commands(pp):
    assert pp("Bulgular yeni satır lomber lordoz düzleşmiştir") == "Bulgular\nlomber lordoz düzleşmiştir"
    assert pp("yeni madde Diğer disk aralıkları normal") == "\n• Diğer disk aralıkları normal"
    assert pp("Sonuç yeni paragraf Siyatik şüphesi") == "Sonuç\n\nSiyatik şüphesi"


@pytest.mark.parametrize("src,expected", [
    ("C3 C4 düzeyinde", "C3-C4 düzeyinde"),
    ("G4 C5 intervertebral", "C4-C5 intervertebral"),
    ("C5G 6 düzeyinde", "C5-C6 düzeyinde"),
    ("C5J6 düzeyinde", "C5-C6 düzeyinde"),
    ("4C5 ve C5 T6 düzeylerinde", "C4-C5 ve C5-C6 düzeylerinde"),
    ("C6-C7 düzeyinde", "C6-C7 düzeyinde"),
    ("C7 T1 düzeyinde", "C7-T1 düzeyinde"),
    ("L5 S1 seviyesinde", "L5-S1 seviyesinde"),
    ("T1 T2 ağırlıklı serilerde", "T1 T2 ağırlıklı serilerde"),  # MR sekansı: dokunma
    ("T2 sekanslarda hiperintens", "T2 sekanslarda hiperintens"),
    ("T11 T12 disk aralığında", "T11-T12 disk aralığında"),
])
def test_spine_levels(src, expected):
    from app.medical.postprocess import normalize_spine_levels
    assert normalize_spine_levels(src) == expected
