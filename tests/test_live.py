from app.live import LiveWriter


class Screen:
    """İmlecin olduğu metin kutusunu taklit eder."""
    def __init__(self):
        self.text, self.erased = "", 0

    def type(self, s):
        self.text += s

    def erase(self, n):
        self.erased += n
        self.text = self.text[:len(self.text) - n] if n else self.text


def run(steps, final):
    sc, t = Screen(), [0.0]
    w = LiveWriter(sc.type, sc.erase, clock=lambda: t[0])
    seen = []
    for ts, partial in steps:
        t[0] = ts
        w.update_partial(partial)
        seen.append(sc.text)
    w.finalize(final)
    return sc, seen


def test_words_appear_before_sentence_end():
    steps = [(0.0, "sol"), (0.3, "sol bacağa"), (0.6, "sol bacağa yayılan"), (0.9, "sol bacağa yayılan ağrı"),
             (1.2, "sol bacağa yayılan ağrı"), (1.7, "sol bacağa yayılan ağrı")]
    sc, seen = run(steps, "Sol bacağa yayılan ağrı ")
    assert seen[3] == "sol bacağa "          # 0,9 sn'de ilk iki kelime çoktan yazıldı
    assert seen[-1] == "sol bacağa yayılan ağrı "  # duraklamada son kelime de yazıldı
    assert sc.text == "Sol bacağa yayılan ağrı "   # cümle sonu: büyük harf düzeltmesi
    assert sc.erased == len("sol bacağa yayılan ağrı ")  # ilk harf farklı -> tamamı yeniden


def test_postprocessing_replaces_only_the_tail():
    steps = [(0.0, "hastaya beş"), (0.5, "hastaya beş yüz"), (1.0, "hastaya beş yüz miligram"),
             (1.8, "hastaya beş yüz miligram")]
    sc, _ = run(steps, "hastaya 500 mg ")
    assert sc.text == "hastaya 500 mg "
    assert sc.erased == len("beş yüz miligram ")  # "hastaya " korunur


def test_unstable_last_word_not_typed_early():
    steps = [(0.0, "pnömo"), (0.3, "pnömoni"), (0.6, "pnömoni ile")]
    sc, seen = run(steps, "pnömoni ile ")
    assert "pnömo " not in seen  # değişen kelime hiç yazılmadı
    assert sc.text == "pnömoni ile "


def test_model_revises_typed_word():
    steps = [(0.0, "sağ alt"), (0.5, "sağ alt"), (1.0, "sağ alt lob"), (1.1, "sağ alt lop"), (1.6, "sağ alt lop")]
    sc, _ = run(steps, "sağ alt lob ")
    assert sc.text == "sağ alt lob "
