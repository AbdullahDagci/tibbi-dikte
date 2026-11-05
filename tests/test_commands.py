"""Sesli biçim komutları: "alt satıra geç", "satır başı", "paragraf başı" metin olarak değil biçim olarak uygulanır."""
from pathlib import Path

import pytest

from app.medical.postprocess import MedicalPostProcessor

M = Path(__file__).resolve().parent.parent / "app" / "medical"


@pytest.fixture(scope="module")
def pp():
    return MedicalPostProcessor.from_files([M / "lexicon_tr.txt"], [M / "corrections_tr.tsv"], use_itn=False)


@pytest.mark.parametrize("src,expected", [
    ("Kalp boyutları normaldir alt satıra geç perikardiyal efüzyon yok",
     "Kalp boyutları normaldir\nperikardiyal efüzyon yok"),
    ("Bulgular satır başı trakea açıktır", "Bulgular\ntrakea açıktır"),
    ("Sonuç paragraf başı akut patoloji yok", "Sonuç\n\nakut patoloji yok"),
])
def test_new_commands(pp, src, expected):
    assert pp(src) == expected


def test_command_with_model_punctuation_and_case(pp):
    # akış modeli komutu ayrı bir cümle gibi büyük harf ve noktayla verebilir
    assert pp("Kalp boyutları normaldir. Alt satıra geç. Trakea açıktır.") == \
        "Kalp boyutları normaldir.\nTrakea açıktır."
    assert pp("SATIR BAŞI") == "\n"


def test_command_alone(pp):
    assert pp("Paragraf başı.") == "\n\n"


def test_user_variant_maps_to_command():
    # kullanıcı, modelin yanlış duyduğu komut söylenişini sözlükte asıl komuta bağlayabilir
    pp = MedicalPostProcessor(corrections=[("alt sağa geç", "alt satıra geç")], use_itn=False)
    assert pp("Kalp normal alt sağa geç trakea açık") == "Kalp normal\ntrakea açık"
