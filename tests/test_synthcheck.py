"""Sentetik (TTS) eğitim klibi kalite kapısı: kaçan / kesilen / anlamsız klipler eğitime girmesin."""
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from synthcheck import accept, pick_refs, shard, word_error_rate  # noqa: E402

S09 = "Safra kesesi lümeninde en büyüğü on sekiz milimetre çaplı akustik gölge veren taşlar izlendi."


def test_normal_clip_accepted():
    ok, why = accept(S09, 8.5, hyp="Safra kesesi rümeninde en büyüğü on sekiz milimetre çaplı akustik gölge veren taşlar izlendi")
    assert ok, why


def test_runaway_clip_rejected_by_duration():
    # Chatterbox varsayılan sesiyle bu cümle 31,8 sn'lik anlamsız ses üretti
    ok, why = accept(S09, 31.8)
    assert not ok and "süre" in why


def test_truncated_clip_rejected_by_duration():
    ok, why = accept(S09, 1.5)
    assert not ok and "süre" in why


def test_garbage_clip_rejected_by_asr():
    ok, why = accept(S09, 8.0, hyp="evet tamam olur")
    assert not ok and "WER" in why


def test_cut_off_ending_rejected():
    # "forcing EOS" uyarısıyla erken kesilen klip: süre makul görünse de son kelimeler yok
    ok, why = accept(S09, 6.0, hyp="Safra kesesi lümeninde en büyüğü on sekiz milimetre çaplı akustik gölge")
    assert not ok and "son" in why


def test_term_errors_do_not_reject():
    # modelin henüz bilmediği terimleri yanlış duyması reddetme sebebi değil: öğretilecek olan tam da bu
    ok, why = accept("Her iki akciğerde buzlu cam dansiteleri izlenmekte olup viral pnömoni açısından klinik korelasyon önerilir.",
                     6.2, hyp="Her iki akciğer de buzlu camdan siteleri izlenmekte olup biralpi numuni açısından klinik korelasyon önerilir.")
    assert ok, why
    # gerçek Chatterbox klibi (sağlam ses): terim yoğun kısa cümlede WER %62
    ok, why = accept("Mediastinal ve hiler patolojik boyutta lenf nodu saptanmadı.", 4.2,
                     hyp="Medyasinal ve Hilal patolojik boyutta lef Nod'u saptanmadı.")
    assert ok, why


def test_wer_ignores_case_and_punctuation():
    assert word_error_rate("Kalp boyutları normal, efüzyon İzlenmedi.", "kalp boyutları normal efüzyon izlenmedi") == 0
    assert word_error_rate("bir iki üç dört", "bir iki beş dört") == pytest.approx(0.25)


def test_shards_partition_items():
    items = list("abcdefg")
    parts = [shard(items, f"{i}/3") for i in range(3)]
    flat = sorted(i for p in parts for i, _ in p)
    assert flat == list(range(7))  # her öğe tam bir parçada, orijinal sırasıyla
    assert parts[1] == [(1, "b"), (4, "e")]
    assert shard(items, "") == list(enumerate(items))


def test_pick_refs_respects_duration_and_count():
    cands = [(f"w{i}.wav", d) for i, d in enumerate([3.0, 7.0, 8.0, 15.0, 9.0, 6.5, 11.0])]
    got = pick_refs(cands, 3, lo=6.0, hi=12.0, seed=1)
    assert len(got) == 3 and len(set(got)) == 3
    assert all(dict(cands)[g] >= 6.0 and dict(cands)[g] <= 12.0 for g in got)
    assert pick_refs(cands, 3, lo=6.0, hi=12.0, seed=1) == got  # tekrarlanabilir


# ------------------------------------------------------------------ kapılı üretim döngüsü (sahte TTS ile)
from tts_synthesize import synthesize_gated  # noqa: E402

SR = 16000


class FakeTTS:
    """İlk `bad` denemede kaçan (40 sn) ses, sonra cümle uzunluğuna uygun ses üretir."""
    def __init__(self, bad: int):
        self.bad, self.calls = bad, []

    def __call__(self, text, ref, seed):
        self.calls.append((text, ref, seed))
        sec = 40.0 if len(self.calls) <= self.bad else len(text) / 13
        return np.zeros(int(sec * SR), dtype=np.float32)


def test_gated_retries_until_good_clip(tmp_path):
    tts = FakeTTS(bad=1)
    st = synthesize_gated([(0, S09)], tmp_path, tts, ["r0.wav", "r1.wav"], check=lambda a: S09, retries=2)
    assert len(tts.calls) == 2 and st["ok"] == 1 and st["rejected"] == 0
    assert (tmp_path / "000000_0.txt").read_text(encoding="utf-8") == S09
    with wave.open(str(tmp_path / "000000_0.wav")) as w:
        assert w.getframerate() == SR and w.getsampwidth() == 2
    assert tts.calls[0][2] != tts.calls[1][2]  # her deneme farklı tohum


def test_gated_rejects_after_retries_and_resume_skips(tmp_path):
    tts = FakeTTS(bad=99)
    st = synthesize_gated([(3, S09)], tmp_path, tts, ["r0.wav"], retries=2)
    assert len(tts.calls) == 3 and st["rejected"] == 1
    assert not list(tmp_path.glob("*.wav"))
    tts2 = FakeTTS(bad=0)
    synthesize_gated([(3, S09)], tmp_path, tts2, ["r0.wav"], retries=2)
    assert tts2.calls == []  # reddedilen cümle yeniden denenmez


def test_gated_skips_existing(tmp_path):
    tts = FakeTTS(bad=0)
    synthesize_gated([(0, S09), (1, S09)], tmp_path, tts, ["r0.wav"])
    tts2 = FakeTTS(bad=0)
    st = synthesize_gated([(0, S09), (1, S09), (2, S09)], tmp_path, tts2, ["r0.wav"])
    assert len(tts2.calls) == 1 and st["ok"] == 1


def test_gated_stops_when_asked_and_resumes(tmp_path):
    """Bellek sınırı aşılınca döngü temiz durur; yeniden başlatılan süreç kalan cümlelerle devam eder."""
    tts = FakeTTS(bad=0)
    items = [(i, S09) for i in range(5)]
    st = synthesize_gated(items, tmp_path, tts, ["r0.wav"], stop=lambda: "bellek" if len(tts.calls) >= 2 else None)
    assert st["ok"] == 2 and st["stopped"] == "bellek"
    tts2 = FakeTTS(bad=0)
    st2 = synthesize_gated(items, tmp_path, tts2, ["r0.wav"], stop=lambda: None)
    assert len(tts2.calls) == 3 and st2["ok"] == 3 and st2["stopped"] is None


def test_word_errors_counts_for_corpus_wer():
    from synthcheck import word_errors
    assert word_errors("bir iki üç dört", "bir iki beş dört") == (1, 4)
    assert word_errors("Kalp normal.", "kalp normal") == (0, 2)
    assert word_errors("", "fazla kelime") == (2, 0)
