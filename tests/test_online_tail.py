"""Akış motoru, uç nokta (cümle sonu): model son anda kelime düşürdüyse kuyruk sesi yeni akışa yeniden verilir.
05.11 kayıt: kısmi sonuç "…daralmıştır. Ayrıca komşu" iken uç nokta tetiklendi, nihai sonuç "…daralmıştır." ile
bitti ve sıfırlamayla "Ayrıca komşu end-" sesi kayboldu. Normal uç noktada davranış değişmez (her uç noktada
yeniden vermek son kelimenin artığından sahte "A" üretiyordu: A/B'de WER %2,9 -> %12,9)."""
import json

import numpy as np

from app.engines.sherpa_engine import TAIL_MARGIN_SEC, _OnlineSession

SR = 16000


class FakeStream:
    def __init__(self):
        self.fed = []

    def accept_waveform(self, sr, samples):
        assert sr == SR
        self.fed.append(np.asarray(samples, dtype=np.float32))

    @property
    def n(self):
        return sum(len(x) for x in self.fed)


class FakeRec:
    """İlk akışta 2,0 sn ses sonunda uç nokta. Uç noktadan önce kısmi sonuç `before`, uç noktada `final`
    (son kelime segment başına göre 0,5 sn'de, segment akışın 0,5. sn'sinde başlar -> mutlak 1,0 sn)."""
    def __init__(self, before, final="mesafe daralmıştır."):
        self.streams, self.before, self.final, self.resets = [], before, final, 0

    def create_stream(self):
        self.streams.append(FakeStream())
        return self.streams[-1]

    def is_ready(self, s):
        return False

    def decode_stream(self, s):
        pass

    def is_endpoint(self, s):
        return s is self.streams[0] and self.resets == 0 and s.n >= 2 * SR

    def get_result(self, s):
        return self.before if s is self.streams[0] and not self.resets else ""

    def get_result_as_json_string(self, s):
        return json.dumps({"text": self.final, "timestamps": [0.1, 0.5], "start_time": 0.5})

    def reset(self, s):
        self.resets += 1


def _run(rec):
    sess = _OnlineSession(rec, SR)
    audio = np.arange(2 * SR, dtype=np.float32)  # örnek değeri = örnek sırası
    out = []
    for i in range(0, len(audio), SR // 10):
        out += sess.accept(audio[i:i + SR // 10])
    return out


def test_dropped_words_tail_is_refed_into_new_stream():
    rec = FakeRec(before="mesafe daralmıştır. Ayrıca komşu")
    assert _run(rec) == ["mesafe daralmıştır."]
    assert len(rec.streams) == 2 and rec.resets == 0
    refed = np.concatenate(rec.streams[1].fed)
    start = int((1.0 + TAIL_MARGIN_SEC) * SR)
    assert refed[0] == start and len(refed) == 2 * SR - start  # son kelimeden sonrası, eksiksiz ve sırasıyla


def test_normal_endpoint_keeps_old_behaviour():
    rec = FakeRec(before="mesafe daralmıştır.")
    assert _run(rec) == ["mesafe daralmıştır."]
    assert len(rec.streams) == 1 and rec.resets == 1  # sıfırlama, yeniden verme yok


def test_revised_but_not_dropped_words_keep_old_behaviour():
    rec = FakeRec(before="mesafe daralmış")  # son kelime değişti ama kelime düşmedi
    assert _run(rec) == ["mesafe daralmıştır."]
    assert len(rec.streams) == 1 and rec.resets == 1


def test_long_utterance_limit_does_not_cut_fluent_dictation(monkeypatch):
    """05.11 kayıt: akıcı okumada 0,8 sn duraksama olmadı; 20 sn sınırı cümleyi kelime ortasında kesti
    ("daralmı|ştır", "servik|al") ve kelime sonları kayboldu. Sınır 60 sn; kuyruk tamponu sınırdan uzun."""
    from pathlib import Path

    import sherpa_onnx

    from app.engines import sherpa_engine as se
    from app.engines.base import ModelInfo

    seen = {}
    monkeypatch.setattr(sherpa_onnx.OnlineRecognizer, "from_transducer", classmethod(
        lambda cls, **kw: seen.update(kw) or object()))
    se.SherpaOnlineEngine(ModelInfo(dir=Path("."), spec={"type": "transducer", "tokens": "t", "encoder": "e",
                                                         "decoder": "d", "joiner": "j"}))
    assert seen["rule3_min_utterance_length"] >= 60
    assert se._KEEP_SEC > seen["rule3_min_utterance_length"]
