"""ISSAI TSC transkript onarımı: kaynakta "İ" -> "i" + boşluk bölünmesi ve kesme işareti silinince kopan ekler."""
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from textnorm import repair_tsc, tsc_vocab  # noqa: E402

VOCAB = Counter({"iyi": 900, "iktisat": 40, "insan": 700, "en": 5000, "geç": 300, "akşamlar": 80})


@pytest.mark.parametrize("src,expected", [
    # bölünmüş "İ": birleşik kelime sözlükte varsa ya da kalan parça kelime değilse
    ("aynı şekilde i srail yunanistan ilişkilerine bakın", "aynı şekilde İsrail yunanistan ilişkilerine bakın"),
    ("ben teşekkür ederim i yi akşamlar dilerim", "ben teşekkür ederim İyi akşamlar dilerim"),
    ("bu bir i ktisat politikası", "bu bir İktisat politikası"),
    ("i çişleri bakanı hakkında", "İçişleri bakanı hakkında"),
    # tek başına "i" + bilinen kelime: kopmuş belirtme eki
    ("yunanistan i srail i en geç tanıyan", "yunanistan İsrail'i en geç tanıyan"),
    # kopmuş ekler: kesme işaretiyle geri bağlanır, önceki kelime özel isimdir
    ("ankara nın işte nabzı", "Ankara'nın işte nabzı"),
    ("bir karşılığın türkiye den", "bir karşılığın Türkiye'den"),
    ("dünya bankası ndan çıkan bir", "dünya Bankası'ndan çıkan bir"),
    ("yunanistan ın ege deki ve", "Yunanistan'ın Ege'deki ve"),
])
def test_repair(src, expected):
    assert repair_tsc(src, VOCAB) == expected


@pytest.mark.parametrize("src", [
    "almanyada ya da diğer",          # "ya", "da": gerçek kelimeler, belirsiz -> dokunma
    "herhalde hani dediğiniz ya kimi",
    "ahmet de geldi",                  # bağlaç "de"
    "bugün hava çok güzel",
])
def test_ambiguous_or_clean_text_untouched(src):
    assert repair_tsc(src, VOCAB) == src


def test_fragment_after_split_i_is_not_a_known_word():
    # "İmparatorluğu" hep bölündüğü için "mparatorluğunun" sık görünür; bu bir kelime sayılmamalı
    texts = ["osmanlı i mparatorluğunun çöküşü"] * 5 + ["korku i mparatorluğunun karşısına"]
    v = tsc_vocab(texts)
    assert repair_tsc("korku i mparatorluğunun karşısına", v) == "korku İmparatorluğunun karşısına"


def test_vocab_counts_tokens():
    v = tsc_vocab(["iyi akşamlar", "çok iyi"])
    assert v["iyi"] == 2 and v["akşamlar"] == 1
