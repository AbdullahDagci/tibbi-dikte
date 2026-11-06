import pytest
from app.scoring import score, spoken_tokens, estimated_accuracy


def test_spoken_tokens_numbers_units():
    assert spoken_tokens("TA 140/90, %94") == ["ta", "yüz", "kırk", "doksan", "yüzde", "doksan", "dört"]
    assert spoken_tokens("500 mg'lık") == ["beş", "yüz", "miligramlık"]
    assert spoken_tokens("12 mm") == ["on", "iki", "milimetre"]
    assert spoken_tokens("İnceleme: EKG'de") == ["inceleme", "ekgde"]
    assert spoken_tokens("bakım'a") == spoken_tokens("bakıma")
    assert spoken_tokens("on beş dakika") == spoken_tokens("15 dk")
    assert spoken_tokens("ikinci derece") == spoken_tokens("2. derece")


def test_digits_vs_words_is_not_an_error():
    s = score("Hastaya 500 mg verildi.", "hastaya beş yüz miligram verildi")
    assert s.wer == 0 and s.accuracy == 1


def test_errors_counted():
    s = score("sağ akciğer üst lobda nodül izlendi", "sağ akciğer üstte lobda nodül")
    assert (s.substitutions, s.deletions, s.insertions) == (1, 1, 0)
    assert abs(s.wer - 2 / 6) < 1e-9
    ops = [a.op for a in s.alignment]
    assert ops == ["ok", "ok", "sub", "ok", "ok", "del"]


def test_terms():
    s = score("hepatosteatoz ve kolelitiazis izlendi", "hepatosteatoz ve kole litiazis izlendi",
              terms={"hepatosteatoz", "kolelitiazis"})
    assert (s.term_hits, s.term_total) == (1, 2) and s.missed_terms == ["kolelitiazis"]


@pytest.mark.parametrize("raw,expected", [
    (0.74, 0.977),     # ölçüm: ham %70-80 aralığının %98,1'i doğru
    (0.54, 0.819),     # ham %45-60 aralığının %80,2'si doğru
    (0.32, 0.171),     # ham %30-45 aralığının %20'si doğru
    (0.0, 0.0),
])
def test_estimated_accuracy_follows_measured_curve(raw, expected):
    assert estimated_accuracy(raw) == pytest.approx(expected, abs=0.002)


@pytest.mark.parametrize("raw", [0.9, 0.99, 1.0, 1.5])
def test_estimated_accuracy_never_claims_certainty(raw):
    assert estimated_accuracy(raw) == 0.99


def test_estimated_accuracy_never_decreases_as_score_rises():
    values = [estimated_accuracy(i / 100) for i in range(101)]
    assert values == sorted(values)
