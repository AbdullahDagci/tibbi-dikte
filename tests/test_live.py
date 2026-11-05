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


def test_words_typed_past_sentence_end_are_carried_not_erased():
    """05.11 kayıt: "…daralmıştır. Ayrıca " yazıldıktan sonra model cümleyi "…daralmıştır." ile bitirdi;
    "Ayrıca" silinmemeli, sonraki cümlenin başı olarak kalmalı (motor kuyruk sesini yeniden çözer)."""
    sc, t = Screen(), [0.0]
    w = LiveWriter(sc.type, sc.erase, clock=lambda: t[0])
    for ts, p in [(0.0, "mesafe daralmıştır. Ayrıca"), (0.5, "mesafe daralmıştır. Ayrıca"),
                  (1.0, "mesafe daralmıştır. Ayrıca komşu"), (1.5, "mesafe daralmıştır. Ayrıca komşu")]:
        t[0] = ts
        w.update_partial(p)
    assert sc.text == "mesafe daralmıştır. Ayrıca "
    w.finalize("mesafe daralmıştır. ")
    assert sc.erased == 0 and sc.text == "mesafe daralmıştır. Ayrıca "
    for ts, p in [(2.0, "Ayrıca komşu"), (2.5, "Ayrıca komşu"), (3.0, "Ayrıca komşu endplatelerde")]:
        t[0] = ts
        w.update_partial(p)
    w.finalize("Ayrıca komşu endplatelerde ")
    assert sc.erased == 0
    assert sc.text == "mesafe daralmıştır. Ayrıca komşu endplatelerde "


def test_carried_words_dropped_by_next_sentence_are_erased():
    sc, t = Screen(), [0.0]
    w = LiveWriter(sc.type, sc.erase, clock=lambda: t[0])
    for ts in (0.0, 0.5, 1.0):
        t[0] = ts
        w.update_partial("tabiidir. Bak")
    w.finalize("tabiidir. ")
    w.finalize("Normal. ")  # sonraki cümle "Bak" ile başlamadı: devredilen kelime düzeltilir
    assert sc.text == "tabiidir. Normal. "


def test_live_typing_applies_postprocessing_so_sentence_end_erases_little():
    """06.11 kullanıcı: anında yazım + tıbbi düzeltme açıkken cümle sonunda cümle silinip yeniden yazılıyordu
    (ham "C üç yedi …" yazılmış, nihai "C3-C7 …" gelmişti). Kelimeler düzeltilmiş hâliyle yazılır; cümle sonunda
    yalnızca yerel düzeltmeler kalır."""
    from pathlib import Path

    from app.medical.postprocess import MedicalPostProcessor
    m = Path(__file__).resolve().parent.parent / "app" / "medical"
    pp = MedicalPostProcessor.from_files(
        [m / "lexicon_tr.txt", m / "radiology_terms_tr.txt"], [m / "corrections_tr.tsv"],
        fuzzy_files=[m / "lexicon_tr.txt", m / "radiology_fuzzy_tr.txt"],
        protected_files=[m / "radiology_known_tr.txt"], general_files=[m / "general_tr_words.txt"])
    full = ("C üç yedi intervertebral disklerde posterior taşma izlenmekte olup anterior subaraknoid mesafe "
            "daralmıştır.")
    words = full.split()
    sc, t = Screen(), [0.0]
    w = LiveWriter(sc.type, sc.erase, clock=lambda: t[0], transform=pp)
    for k in range(1, len(words) + 1):
        for _ in range(3):
            w.update_partial(" ".join(words[:k]))
            t[0] += 0.3
    final = pp(full) + " "
    w.finalize(final)
    assert sc.text == final
    assert sc.erased <= 8  # "C3 " -> "C3-C7 " gibi yerel düzeltmeler; eskiden ~100 karakter
