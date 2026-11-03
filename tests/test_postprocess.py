from pathlib import Path

import pytest

from app.medical.postprocess import MedicalPostProcessor, normalize_units, tr_lower, tr_upper

ROOT = Path(__file__).resolve().parent.parent
LEX = ROOT / "app" / "medical" / "lexicon_tr.txt"
CORR = ROOT / "app" / "medical" / "corrections_tr.tsv"


@pytest.fixture(scope="module")
def pp():
    return MedicalPostProcessor.from_files([LEX], [CORR])


@pytest.fixture(scope="module")
def pp_noitn():
    return MedicalPostProcessor.from_files([LEX], [CORR], use_itn=False)


def test_turkish_case():
    assert tr_lower("IŞIK İLAÇ") == "ışık ilaç"
    assert tr_upper("ilaç ısı") == "İLAÇ ISI"


@pytest.mark.parametrize("src,expected", [
    ("Hastanın e ka ge çekildi", "Hastanın EKG çekildi"),
    ("Em ar istendi", "MR istendi"),
    ("ce ar pe yüksek", "CRP yüksek"),
    ("Amoksisilin kılavulan at başlandı", "Amoksisilin-klavulanat başlandı"),  # 2. geçiş: ilaç adı birleşir
])
def test_corrections(pp_noitn, src, expected):
    assert pp_noitn(src) == expected


@pytest.mark.parametrize("src,expected", [
    ("Tropolin yüksek", "Troponin yüksek"),          # 1 harf hatası
    ("Pantokrazol verildi", "Pantoprazol verildi"),
    ("intrabenoz uygulandı", "intravenöz uygulandı"),  # 2 harf hatası (uzun kelime)
    ("metforminin dozu", "metforminin dozu"),          # doğru kelime + ek: dokunma
    ("kalp yetmezliği var", "kalp yetmezliği var"),    # ünsüz yumuşaması: dokunma
    ("ultrasonografisinde", "ultrasonografisinde"),    # terim + ek: dokunma
    ("hastaya söylendi", "hastaya söylendi"),          # sıradan kelimeler değişmez
    ("muayenede bulgu yok", "muayenede bulgu yok"),
])
def test_fuzzy(pp_noitn, src, expected):
    assert pp_noitn(src) == expected


def test_casing(pp_noitn):
    assert pp_noitn("Tansiyon Arteriyel normal") == "Tansiyon arteriyel normal"
    assert pp_noitn("hastada parkinson var") == "hastada Parkinson var"
    assert pp_noitn("Levotiroksin başlandı") == "Levotiroksin başlandı"  # cümle başı korunur
    assert pp_noitn("levotiroksin başlandı") == "levotiroksin başlandı"  # parça cümle ortası olabilir


def test_units():
    assert normalize_units("500 miligram") == "500 mg"
    assert normalize_units("100 mikrogram") == "100 mcg"
    assert normalize_units("10 mililitre") == "10 ml"
    assert normalize_units("20 internasyonel ünite") == "20 IU"
    assert normalize_units("500 miligramlık tablet") == "500 mg'lık tablet"
    assert normalize_units("Tansiyon arteriyel 140 90, nabız 92") == "Tansiyon arteriyel 140/90, nabız 92"
    assert normalize_units("1.000 mg") == "1000 mg"


def test_full_pipeline_with_itn(pp):
    out = pp("Amoksisilin bin miligram günde iki kez")
    assert out == "Amoksisilin 1000 mg günde 2 kez"
    out = pp("Tansiyon arteriyel yüz kırk doksan, oksijen satürasyonu yüzde doksan dört")
    assert out == "Tansiyon arteriyel 140/90, oksijen satürasyonu %94"


def test_percent_space(pp_noitn):
    assert pp_noitn("satürasyonu%94") == "satürasyonu %94"


def test_lowercase_apostrophe(pp_noitn):
    assert pp_noitn("meme ultrasonografisi'nde lezyon") == "meme ultrasonografisinde lezyon"
    assert pp_noitn("EKG'de bulgu, Ahmet'in raporu") == "EKG'de bulgu, Ahmet'in raporu"
    assert pp_noitn("Ultrasonografisi'nde nodül") == "Ultrasonografisinde nodül"


def test_rads_corrections(pp_noitn):
    assert pp_noitn("Bıkras dört olarak değerlendirildi") == "BI-RADS dört olarak değerlendirildi"
    assert pp_noitn("tikras üç kategorisinde") == "TI-RADS üç kategorisinde"
