from app.scoring import score, spoken_tokens


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
