"""Kelime bazlı decoder güven skoru: BPE alt-tokenları kelimelere gruplama ve oturumdan toplama."""
import json
import math

import numpy as np

from app.engines.sherpa_engine import _OnlineSession, _word_confidences

SR = 16000


def test_word_confidences_groups_subwords_by_leading_space():
    tokens = [" A", "st", "aya", " gün", "de"]
    ys_probs = [-1.0, -2.0, -0.5, -0.2, -0.4]
    out = _word_confidences(tokens, ys_probs)
    assert [w for w, _ in out] == ["Astaya", "günde"]
    assert out[0][1] == math.exp(np.mean([-1.0, -2.0, -0.5]))
    assert out[1][1] == math.exp(np.mean([-0.2, -0.4]))


def test_word_confidences_empty_input():
    assert _word_confidences([], []) == []


class _FakeStream:
    def accept_waveform(self, sr, samples):
        pass


class _FakeRec:
    """Tek uç noktada sonuç veren sahte tanıyıcı: tokens/ys_probs içeren JSON döndürür."""
    def __init__(self):
        self.streams = []

    def create_stream(self):
        self.streams.append(_FakeStream())
        return self.streams[-1]

    def is_ready(self, s):
        return False

    def decode_stream(self, s):
        pass

    def is_endpoint(self, s):
        return True

    def get_result(self, s):
        return "ekg çekildi"

    def get_result_as_json_string(self, s):
        return json.dumps({
            "text": "ekg çekildi",
            "timestamps": [0.0, 0.2, 0.6],
            "start_time": 0.0,
            "tokens": [" ekg", " çe", "kildi"],
            "ys_probs": [-0.1, -0.3, -0.2],
        })

    def reset(self, s):
        pass


def test_online_session_accumulates_word_confidences_across_endpoint():
    sess = _OnlineSession(_FakeRec(), SR)
    out = sess.accept(np.zeros(SR, dtype=np.float32))
    assert out == ["ekg çekildi"]
    words = sess.word_confidences()
    assert [w for w, _ in words] == ["ekg", "çekildi"]
    assert all(0.0 < c <= 1.0 for _, c in words)


def test_word_confidences_pops_and_clears():
    sess = _OnlineSession(_FakeRec(), SR)
    sess.accept(np.zeros(SR, dtype=np.float32))
    assert sess.word_confidences()
    assert sess.word_confidences() == []
