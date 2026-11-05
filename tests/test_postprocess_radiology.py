"""Radyoloji testinde (data/radiology_test) sonişlemenin doğru model çıktısını bozduğu durumlar.

İnce ayarlı model (tibbi-tr-v3) bu cümleleri doğru yazıyordu; sonişleme hatayı %5,0'tan %6,9'a çıkarıyordu.
Uygulamadaki sözlük dosyalarıyla (dictation.py ile aynı yapı) sınanır.
"""
from pathlib import Path

import pytest

from app.medical.postprocess import MedicalPostProcessor

M = Path(__file__).resolve().parent.parent / "app" / "medical"


def _make(use_itn: bool) -> MedicalPostProcessor:
    return MedicalPostProcessor.from_files(
        [M / "lexicon_tr.txt", M / "radiology_terms_tr.txt"], [M / "corrections_tr.tsv"],
        fuzzy_files=[M / "lexicon_tr.txt", M / "radiology_fuzzy_tr.txt"],
        protected_files=[M / "radiology_known_tr.txt"], use_itn=use_itn)


@pytest.fixture(scope="module")
def pp():
    return _make(use_itn=False)


@pytest.fixture(scope="module")
def pp_itn():
    return _make(use_itn=True)


@pytest.mark.parametrize("text", [
    # Birleştirme: raporlarda bitişik yazım HATASI olarak geçen biçimler ("heriki", "solmeme", "kistizlendi")
    # ayrı yazılmış iki doğru kelimeyi birleştirmenin gerekçesi olamaz
    "Her iki akciğerde buzlu cam dansiteleri izlendi.",
    "Sol böbrek üst polde basit kortikal kist izlendi.",  # ("kist", "izlendi") birleştirme çifti olarak denk gelir
    "Meme ultrasonografisinde sol meme saat ikide lezyon izlendi.",
    "Mamografide sağ meme üst dış kadranda gruplaşmış mikrokalsifikasyonlar izlendi.",
    # Bulanık düzeltme doğru yazımlara dokunmamalı ("abdomen"+"al", "milimetrik"+"ir" üretiyordu)
    "Abdominal aortada infrarenal düzeyde anevrizma izlendi.",
    "Kranial bilgisayarlı tomografide akut kanama bulgusu saptanmadı.",
    "Endometrium kalınlığı sekiz milimetredir.",
    # Özel ad yazımı: raporlardan üretilen küçük harfli liste el ile yazılmış "Doppler"i ezmemeli
    "Karotis Doppler ultrasonografide kalsifik plak izlendi.",
])
def test_correct_text_is_left_alone(pp, text):
    assert pp(text) == text


@pytest.mark.parametrize("src,expected", [
    # ITN (damga) "ö"yü "o" sayıyordu: "Ön çapraz bağ" -> "10 çapraz bağ" (raporda yanlış sayı!)
    ("Ön çapraz bağda tam kat yırtık mevcuttur.", "Ön çapraz bağda tam kat yırtık mevcuttur."),
    ("Sol ön inen arterde darlık izlendi.", "Sol ön inen arterde darlık izlendi."),
    ("Sağ ön duvarda on iki milimetre kalınlaşma izlendi.", "Sağ ön duvarda 12 mm kalınlaşma izlendi."),
    # damga harf+sayı dizisini önceki kelimeyle heceleme sanıyordu: "görüntülemede L dört L beş" -> "Gd 5"
    ("Lomber manyetik rezonans görüntülemede L dört L beş seviyesinde disk protrüzyonu izlendi.",
     "Lomber manyetik rezonans görüntülemede L4-L5 seviyesinde disk protrüzyonu izlendi."),
    ("İncelemede C beş C altı seviyesinde osteofit izlendi.", "İncelemede C5-C6 seviyesinde osteofit izlendi."),
    ("Yapılan incelemede L beş S bir seviyesinde ekstrüzyon mevcuttur.",
     "Yapılan incelemede L5-S1 seviyesinde ekstrüzyon mevcuttur."),
])
def test_itn_keeps_words_and_spine_levels(pp_itn, src, expected):
    assert pp_itn(src) == expected
