"""sherpa-onnx motoru.

model.json alanları:
  "mode": "online"  -> akış (streaming) modeli; uç nokta (sessizlik) algılanınca metin kesinleşir
  "mode": "offline" -> akışsız model; Silero VAD konuşmayı böler, her parça ayrı çözülür
  "type": transducer | paraformer | zipformer2_ctc (online)
          transducer | nemo_ctc | whisper | paraformer | sense_voice (offline)
Dosya alanları: tokens, encoder, decoder, joiner, model, bpe_vocab, vad (offline için)
"""
from __future__ import annotations

import json
import logging

import numpy as np
import sherpa_onnx

from ..paths import resource_dir
from .base import DictationSession, ModelInfo, SttEngine

log = logging.getLogger(__name__)


def _clean(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------- online (akış)
# Kelime düşürülen uç noktada son kelimenin zaman damgasından bu kadar sonrası yeni akışa yeniden verilir
TAIL_MARGIN_SEC = 0.3
_KEEP_SEC = 90.0  # yeniden verme için tutulan son ses (rule3 sınırından uzun olmalı)


class _OnlineSession(DictationSession):
    """Uç nokta (cümle sonu): sonuç alınır, akış sıfırlanır. Model son anda kelime düşürdüyse (kısmi sonuç
    "…daralmıştır. Ayrıca komşu", nihai "…daralmıştır.") sıfırlama o kelimelerin sesini atardı (05.11 kayıt):
    bu durumda yeni akış açılır ve son kelimeden sonraki ses ona yeniden verilir. Normal uç noktada davranış
    aynıdır (her uç noktada yeniden vermek son kelimenin artığından sahte "A" üretiyordu)."""

    def __init__(self, rec: "sherpa_onnx.OnlineRecognizer", sr: int):
        self.rec = rec
        self.sr = sr
        self._new_stream()

    def _new_stream(self, audio: np.ndarray | None = None) -> None:
        self.stream = self.rec.create_stream()
        self._audio: list[np.ndarray] = []  # akışa verilen sesin son _KEEP_SEC'i
        self._base = 0                       # _audio'daki ilk örneğin akış başına göre sırası
        self._n = 0                          # akışa verilen toplam örnek
        self._last = ""                      # uç noktadan önceki son kısmi sonuç
        if audio is not None and len(audio):
            self._feed(audio)

    def _feed(self, samples: np.ndarray) -> None:
        s = np.asarray(samples, dtype=np.float32)
        self._audio.append(s)
        self._n += len(s)
        keep = int(_KEEP_SEC * self.sr)
        while len(self._audio) > 1 and self._n - self._base - len(self._audio[0]) >= keep:
            self._base += len(self._audio.pop(0))
        self.stream.accept_waveform(self.sr, s)
        self._decode()

    def _decode(self) -> None:
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)

    def accept(self, samples: np.ndarray) -> list[str]:
        self._feed(samples)
        if not self.rec.is_endpoint(self.stream):
            self._last = self.rec.get_result(self.stream)
            return []
        r = json.loads(self.rec.get_result_as_json_string(self.stream))
        text = _clean(r.get("text", ""))
        ts = r.get("timestamps") or []
        prev, cur = _clean(self._last).split(), text.split()
        if ts and len(prev) > len(cur) and prev[:len(cur)] == cur:
            # zaman damgaları segment başına göre; segment akışın start_time anında başlar
            start = int((float(r.get("start_time", 0.0)) + ts[-1] + TAIL_MARGIN_SEC) * self.sr) - self._base
            tail = np.concatenate(self._audio)[max(0, start):]
            log.info("uç nokta kelime düşürdü (%d kelime): %.1f sn ses yeniden çözülüyor",
                     len(prev) - len(cur), len(tail) / self.sr)
            self._new_stream(tail)
        else:
            self.rec.reset(self.stream)
            self._last = ""
        return [text] if text else []

    def partial(self) -> str:
        return _clean(self.rec.get_result(self.stream))

    def flush(self) -> list[str]:
        # Son kelimelerin çözülmesi için kısa sessizlik ekle.
        self.stream.accept_waveform(self.sr, np.zeros(int(self.sr * 0.6), dtype=np.float32))
        self.stream.input_finished()
        self._decode()
        text = _clean(self.rec.get_result(self.stream))
        self._new_stream()
        return [text] if text else []


class SherpaOnlineEngine(SttEngine):
    def __init__(self, model: ModelInfo, **kw):
        super().__init__(model, **kw)
        m, sp = model, model.spec
        common = dict(
            tokens=m.path("tokens"),
            num_threads=self.num_threads,
            sample_rate=m.sample_rate,
            feature_dim=int(sp.get("feature_dim", 80)),
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=float(sp.get("rule1_min_trailing_silence", 2.4)),
            rule2_min_trailing_silence=float(sp.get("rule2_min_trailing_silence", 0.8)),
            # 20 sn akıcı okumayı kelime ortasında kesiyordu (05.11: "daralmı|ştır"); cümle duraksamada biter
            rule3_min_utterance_length=float(sp.get("rule3_min_utterance_length", 60.0)),
            provider="cpu",
        )
        t = sp.get("type", "transducer")
        if t == "transducer":
            kwargs = dict(
                encoder=m.path("encoder"), decoder=m.path("decoder"), joiner=m.path("joiner"),
                decoding_method=sp.get("decoding_method", "modified_beam_search"),
                max_active_paths=int(sp.get("max_active_paths", 4)),
            )
            if self.hotwords_file and m.path("bpe_vocab") and kwargs["decoding_method"] == "modified_beam_search":
                kwargs.update(hotwords_file=self.hotwords_file, hotwords_score=self.hotwords_score,
                              modeling_unit=sp.get("modeling_unit", "bpe"), bpe_vocab=m.path("bpe_vocab"))
            self.rec = sherpa_onnx.OnlineRecognizer.from_transducer(**common, **kwargs)
        elif t == "paraformer":
            self.rec = sherpa_onnx.OnlineRecognizer.from_paraformer(
                encoder=m.path("encoder"), decoder=m.path("decoder"), **common)
        elif t == "zipformer2_ctc":
            self.rec = sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(model=m.path("model"), **common)
        else:
            raise ValueError(f"Desteklenmeyen online model tipi: {t}")

    def new_session(self) -> DictationSession:
        return _OnlineSession(self.rec, self.sample_rate)


# ---------------------------------------------------------------- offline (VAD + toplu)
class _OfflineSession(DictationSession):
    def __init__(self, engine: "SherpaOfflineEngine"):
        self.e = engine
        self.vad = engine.make_vad()
        self.window = engine.vad_window
        self.buf = np.zeros(0, dtype=np.float32)

    def _drain(self) -> list[str]:
        out = []
        while not self.vad.empty():
            seg = np.asarray(self.vad.front.samples, dtype=np.float32)
            self.vad.pop()
            text = self.e.decode(seg)
            if text:
                out.append(text)
        return out

    def accept(self, samples: np.ndarray) -> list[str]:
        self.buf = np.concatenate([self.buf, samples])
        while len(self.buf) >= self.window:
            self.vad.accept_waveform(self.buf[:self.window])
            self.buf = self.buf[self.window:]
        return self._drain()

    def flush(self) -> list[str]:
        if len(self.buf):
            self.vad.accept_waveform(self.buf)
            self.buf = np.zeros(0, dtype=np.float32)
        self.vad.flush()
        out = self._drain()
        self.vad = self.e.make_vad()
        return out


class SherpaOfflineEngine(SttEngine):
    vad_window = 512

    def __init__(self, model: ModelInfo, **kw):
        super().__init__(model, **kw)
        m, sp = model, model.spec
        common = dict(tokens=m.path("tokens"), num_threads=self.num_threads, provider="cpu")
        t = sp.get("type", "transducer")
        if t == "transducer":
            kwargs = dict(
                encoder=m.path("encoder"), decoder=m.path("decoder"), joiner=m.path("joiner"),
                sample_rate=m.sample_rate, feature_dim=int(sp.get("feature_dim", 80)),
                decoding_method=sp.get("decoding_method", "modified_beam_search"),
                max_active_paths=int(sp.get("max_active_paths", 4)),
            )
            if self.hotwords_file and m.path("bpe_vocab") and kwargs["decoding_method"] == "modified_beam_search":
                kwargs.update(hotwords_file=self.hotwords_file, hotwords_score=self.hotwords_score,
                              modeling_unit=sp.get("modeling_unit", "bpe"), bpe_vocab=m.path("bpe_vocab"))
            if sp.get("model_type"):  # ör. "nemo_transducer" (NeMo TDT/RNNT modelleri)
                kwargs["model_type"] = sp["model_type"]
            self.rec = sherpa_onnx.OfflineRecognizer.from_transducer(**common, **kwargs)
        elif t == "nemo_ctc":
            self.rec = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(model=m.path("model"), **common)
        elif t == "whisper":
            self.rec = sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=m.path("encoder"), decoder=m.path("decoder"),
                language=sp.get("language", "tr"), task="transcribe", **common)
        elif t == "paraformer":
            self.rec = sherpa_onnx.OfflineRecognizer.from_paraformer(paraformer=m.path("model"), **common)
        elif t == "sense_voice":
            self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=m.path("model"), language=sp.get("language", "auto"), use_itn=True, **common)
        else:
            raise ValueError(f"Desteklenmeyen offline model tipi: {t}")

        vad_path = m.path("vad") or str(resource_dir() / "silero_vad.onnx")
        self.vad_config = sherpa_onnx.VadModelConfig()
        self.vad_config.silero_vad.model = vad_path
        self.vad_config.silero_vad.min_silence_duration = float(sp.get("vad_min_silence", 0.5))
        self.vad_config.silero_vad.max_speech_duration = float(sp.get("vad_max_speech", 20.0))
        self.vad_config.sample_rate = m.sample_rate

    def make_vad(self):
        return sherpa_onnx.VoiceActivityDetector(self.vad_config, buffer_size_in_seconds=60)

    def decode(self, samples: np.ndarray) -> str:
        gain = float(self.model.spec.get("input_gain", 1.0))  # bazı NeMo dışa aktarımları ister (VAD'a uygulanmaz)
        s = self.rec.create_stream()
        samples = samples * gain if gain != 1.0 else samples
        pad = int(float(self.model.spec.get("pad_sec", 0)) * self.sample_rate)  # VAD parçası çok sıkı kesilmesin
        if pad:
            z = np.zeros(pad, dtype=np.float32)
            samples = np.concatenate([z, samples.astype(np.float32), z])
        s.accept_waveform(self.sample_rate, samples)
        self.rec.decode_stream(s)
        return _clean(s.result.text)

    def new_session(self) -> DictationSession:
        return _OfflineSession(self)
