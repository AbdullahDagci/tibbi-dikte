"""MedicalPostProcessor.annotate: Test ekranındaki canlı editörde kelimeleri renklendirmek için
hangi kelimelerin düzeltildiğini ("corrected") ve hangilerinin kuşkulu kaldığını ("suspect")
işaretler. __call__ ile aynı metni üretmesi (parçaları birleştirince) garanti edilmelidir.
"""
from pathlib import Path

import pytest

from app.medical.postprocess import MedicalPostProcessor

M = Path(__file__).resolve().parent.parent / "app" / "medical"


@pytest.fixture(scope="module")
def pp() -> MedicalPostProcessor:
    return MedicalPostProcessor.from_files(
        [M / "lexicon_tr.txt", M / "radiology_terms_tr.txt"], [M / "corrections_tr.tsv"],
        fuzzy_files=[M / "lexicon_tr.txt", M / "radiology_fuzzy_tr.txt"],
        protected_files=[M / "radiology_known_tr.txt"], general_files=[M / "general_tr_words.txt"], use_itn=True)


def joined(spans: list[tuple[str, str]]) -> str:
    return "".join(t for t, _ in spans)


@pytest.mark.parametrize("text", [
    "hasta e ka ge çekildi",
    "sol böbrekte beş milimetrelik basit kist izlendi",
    "metformın kullanan hastada",
    "yeni satıra geç sonraki paragraf başı devam",
    "tansiyon yüz kırk doksan ölçüldü",
])
def test_annotate_matches_call(pp: MedicalPostProcessor, text: str) -> None:
    assert joined(pp.annotate(text)) == pp(text)


def test_exact_correction_marked_corrected(pp: MedicalPostProcessor) -> None:
    spans = pp.annotate("hasta e ka ge çekildi")
    assert any(status == "corrected" and "EKG" in t for t, status in spans)


def test_fuzzy_correction_marked_corrected(pp: MedicalPostProcessor) -> None:
    spans = pp.annotate("metformın kullanan hastada")
    assert any(status == "corrected" and tr == "metformin" for tr, status in
               [(t.lower(), s) for t, s in spans])


def test_unmatched_long_word_marked_suspect(pp: MedicalPostProcessor) -> None:
    spans = pp.annotate("hastada zzqqwwttxxrr saptanmadı")
    assert any(status == "suspect" and "zzqqwwttxxrr" in t.lower() for t, status in spans)


def test_known_words_stay_normal(pp: MedicalPostProcessor) -> None:
    spans = pp.annotate("hasta ayaktan değerlendirildi")
    assert all(status == "normal" for _, status in spans)


def test_low_confidence_unchanged_word_marked_corrected(pp: MedicalPostProcessor) -> None:
    """Sözlükte var, pipeline değiştirmiyor, ama decoder çok düşük güvenle duymuş: yine kırmızı."""
    text = "hasta ayaktan değerlendirildi"
    confs = [("hasta", 0.95), ("ayaktan", 0.30), ("değerlendirildi", 0.95)]
    spans = pp.annotate(text, confs)
    assert joined(spans) == pp(text)
    assert any(status == "corrected" and "ayaktan" in t.lower() for t, status in spans)


def test_medium_confidence_unchanged_word_marked_suspect(pp: MedicalPostProcessor) -> None:
    text = "hasta ayaktan değerlendirildi"
    confs = [("hasta", 0.95), ("ayaktan", 0.55), ("değerlendirildi", 0.95)]
    spans = pp.annotate(text, confs)
    assert any(status == "suspect" and "ayaktan" in t.lower() for t, status in spans)


def test_high_confidence_keeps_normal(pp: MedicalPostProcessor) -> None:
    text = "hasta ayaktan değerlendirildi"
    confs = [("hasta", 0.95), ("ayaktan", 0.95), ("değerlendirildi", 0.95)]
    spans = pp.annotate(text, confs)
    assert all(status == "normal" for _, status in spans)


def test_apostrophe_word_keeps_confidences_aligned(pp: MedicalPostProcessor) -> None:
    """Motor "EKG'de"yi tek kelime verir, _WORD_RE iki sayar: cümlenin güvenleri kaybolmamalı."""
    spans = pp.annotate("EKG'de ayaktan değerlendirildi",
                        [("EKG'de", 0.95), ("ayaktan", 0.30), ("değerlendirildi", 0.95)])
    assert any(status == "corrected" and "ayaktan" in t for t, status in spans)


def test_word_scores_explain_each_color(pp: MedicalPostProcessor) -> None:
    rows = pp.word_scores("hasta ayaktan değerlendirildi beş yüz miligram",
                          [("hasta", 0.95), ("ayaktan", 0.30), ("değerlendirildi", 0.55),
                           ("beş", 0.9), ("yüz", 0.8), ("miligram", 0.7)])
    by_heard = {r.heard: r for r in rows}
    assert by_heard["hasta"].status == "normal" and by_heard["hasta"].confidence == 0.95
    assert (by_heard["ayaktan"].status, by_heard["ayaktan"].reason) == ("corrected", "düşük güven")
    assert (by_heard["değerlendirildi"].status, by_heard["değerlendirildi"].reason) == ("suspect", "orta güven")
    unit = by_heard["beş yüz miligram"]
    assert unit.written == "500 mg" and unit.status == "normal" and unit.reason == "sayı/birim dönüşümü"
    assert unit.confidence == 0.7


def test_word_scores_status_matches_annotate(pp: MedicalPostProcessor) -> None:
    text = "metformın ayaktan zzqqwwttxxrr hasta"
    confs = [("metformın", 0.9), ("ayaktan", 0.4), ("zzqqwwttxxrr", 0.9), ("hasta", 0.55)]
    colored = {t.strip(): s for t, s in pp.annotate(text, confs) if s != "normal"}
    scored = {r.written: r.status for r in pp.word_scores(text, confs) if r.status != "normal"}
    assert scored == colored and len(scored) == 4


def test_confident_number_conversion_stays_uncolored(pp: MedicalPostProcessor) -> None:
    text = "yaklaşık dört milimetre çapında"
    spans = pp.annotate(text, [("yaklaşık", 0.9), ("dört", 0.9), ("milimetre", 0.9), ("çapında", 0.9)])
    assert joined(spans) == pp(text) and all(s == "normal" for _, s in spans)


def test_low_confidence_number_is_colored_including_digits(pp: MedicalPostProcessor) -> None:
    """Yanlış duyulmuş ölçü en tehlikeli hatadır: dönüşüm doğru görünse de düşük güvende rakam da boyanır."""
    text = "yaklaşık dört milimetre çapında"
    spans = pp.annotate(text, [("yaklaşık", 0.9), ("dört", 0.3), ("milimetre", 0.9), ("çapında", 0.9)])
    assert joined(spans) == pp(text)
    assert ("4 mm", "corrected") in spans


def test_her_iki_is_not_converted_to_digit(pp: MedicalPostProcessor) -> None:
    assert pp("Her iki akciğer alt lobunda") == "Her iki akciğer alt lobunda"
    assert pp("her iki akciğerde minimal") == "her iki akciğerde minimal"
    assert pp("günde iki kez") == "günde 2 kez"


@pytest.mark.parametrize("word", ["loblarda", "Mediastende", "posterobazal", "kalibrasyondadır"])
def test_thorax_words_are_not_suspect(pp: MedicalPostProcessor, word: str) -> None:
    assert all(status == "normal" for _, status in pp.annotate(f"hasta {word} izlendi"))
    assert word in pp(f"hasta {word} izlendi")


def test_bt_abbreviation_is_uppercased(pp: MedicalPostProcessor) -> None:
    assert pp("toraks Bt raporu") == "toraks BT raporu"
    assert pp("toraks Bt'de izlendi") == "toraks BT'de izlendi"


def test_non_numeric_change_stays_red(pp: MedicalPostProcessor) -> None:
    spans = pp.annotate("hasta e ka ge çekildi", [("hasta", 0.9), ("e", 0.9), ("ka", 0.9), ("ge", 0.9), ("çekildi", 0.9)])
    assert ("EKG", "corrected") in spans


def test_mismatched_confidence_length_is_ignored(pp: MedicalPostProcessor) -> None:
    """Motorun kelime hizalaması garanti değil: sayı uyuşmazsa güven sessizce yok sayılır."""
    text = "hasta ayaktan değerlendirildi"
    confs = [("hasta", 0.10)]  # 1 öğe, ama 3 kelime var
    spans = pp.annotate(text, confs)
    assert joined(spans) == pp(text)
    assert all(status == "normal" for _, status in spans)
