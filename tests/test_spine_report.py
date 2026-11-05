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
        protected_files=[M / "radiology_known_tr.txt"], general_files=[M / "general_tr_words.txt"], use_itn=False)


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


@pytest.mark.parametrize("src,expected", [
    ("C3 7 intervertebral disklerde", "C3-C7 intervertebral disklerde"),  # çok seviyeli aralık
    ("L2 5 disk aralıklarında", "L2-L5 disk aralıklarında"),
    ("C3 7 mm çaplı", "C3 7 mm çaplı"),           # seviye bağlamı yok: dokunma
    ("C7 3 intervertebral", "C7 3 intervertebral"),  # azalan: aralık değil
])
def test_spine_ranges(src, expected):
    from app.medical.postprocess import normalize_spine_levels
    assert normalize_spine_levels(src) == expected


@pytest.fixture(scope="module")
def pp_itn():
    return MedicalPostProcessor.from_files(
        [M / "lexicon_tr.txt", M / "radiology_terms_tr.txt"], [M / "corrections_tr.tsv"],
        fuzzy_files=[M / "lexicon_tr.txt", M / "radiology_fuzzy_tr.txt"],
        protected_files=[M / "radiology_known_tr.txt"], general_files=[M / "general_tr_words.txt"])


@pytest.mark.parametrize("src,expected", [
    # 06.11 kullanıcı denemesi (servikal MR): model çıktısı -> rapordaki yazım
    ("C üç yedi intervertebral disklerde posterior taşma izlenmekte",
     "C3-C7 intervertebral disklerde posterior taşma izlenmekte"),
    ("C beş altı intervertebral diskte posterosantral annüler fissür",
     "C5-C6 intervertebral diskte posterosantral annüler fissür"),
    ("komşu en platelerde T bir ağırlıklı serilerde hipointens, T iki ağırlıklı serilerde hiperintens",
     "komşu end-platelerde T1 ağırlıklı serilerde hipointens, T2 ağırlıklı serilerde hiperintens"),
    ("Modic tip bir dejenerasyon dikkati çekmektedir.", "Modic tip 1 dejenerasyon dikkati çekmektedir."),
    ("tip iki diyabet öyküsü", "tip 2 diyabet öyküsü"),
    # "bir" sayı bağlamı yoksa sözcük kalır
    ("disklere ait patolojik bir bulgu saptanmamıştır.", "disklere ait patolojik bir bulgu saptanmamıştır."),
])
def test_cervical_report_numbers(pp_itn, src, expected):
    assert pp_itn(src) == expected
