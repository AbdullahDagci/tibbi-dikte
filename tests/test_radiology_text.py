"""Sentetik radyoloji cümle üreteci: şablon doldurma, şablon denetimi, test seti sızıntı filtresi."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from make_radiology_text import expand, generate, near_test, template_problems  # noqa: E402


def test_expand_alternatives_and_slots():
    rng = random.Random(0)
    seen = {expand("{Sağ|Sol} memede {mm} mm lezyon {izlendi|saptandı}.", rng) for _ in range(200)}
    assert len(seen) > 20
    for s in seen:
        side, rest = s.split(" memede ")
        assert side in ("Sağ", "Sol")
        num, unit, *_ = rest.split()
        assert unit == "mm" and 2 <= int(num) <= 60


def test_expand_cm_and_empty_option():
    rng = random.Random(1)
    outs = {expand("{|belirgin }kalınlaşma {cm} cm.", rng) for _ in range(100)}
    assert any(o.startswith("belirgin kalınlaşma") for o in outs)
    assert any(o.startswith("kalınlaşma") for o in outs)
    assert all("{" not in o for o in outs)


def test_template_problems():
    assert template_problems("{Sağ|Sol} memede {mm} mm kist izlendi.") == []
    assert template_problems("Sağ memede {a|{b|c}} kist izlendi.")  # iç içe
    assert template_problems("Sağ memede {sağ|sol kist izlendi.")  # kapanmamış
    assert template_problems("Sağ memede {boyut} kist izlendi.")  # bilinmeyen yuva
    assert template_problems("Sağ memede kist izlendi")  # nokta yok
    assert template_problems("5. kostada kırık izlendi.")  # rakamla sıra sayısı


TEST = ["Safra kesesi lümeninde en büyüğü on sekiz milimetre çaplı akustik gölge veren taşlar izlendi."]


def test_near_test_catches_same_sentence_with_other_numbers():
    assert near_test("Safra kesesi lümeninde en büyüğü yirmi iki milimetre çaplı akustik gölge veren taşlar izlendi.", TEST)
    assert not near_test("Safra kesesi lümeninde taş izlenmedi.", TEST)


def test_generate_is_unique_normalized_and_leak_free():
    tpls = ["Safra kesesi lümeninde en büyüğü {mm} mm çaplı akustik gölge veren taşlar izlendi.",
            "{Sağ|Sol} böbrekte {mm} mm taş izlendi.", "Batın içi serbest sıvı izlenmedi."]
    out = generate(tpls, 50, test_sentences=TEST, seed=3)
    assert len(out) == len(set(out))
    assert not any(s.startswith("Safra") for s in out)  # test cümlesine çok yakın şablon tümüyle elendi
    assert "Batın içi serbest sıvı izlenmedi." in out
    assert all(not any(c.isdigit() for c in s) for s in out)  # sayılar yazıyla
    assert sum(s.endswith("taş izlendi.") for s in out) >= 40
