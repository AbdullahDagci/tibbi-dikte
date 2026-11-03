"""Kurtarılan checkpoint'in mihu modeliyle birebir aynı olduğunu doğrular.

  1. Checkpoint -> ONNX (fp32) yeniden dışa aktarılır, tüm başlatıcılar mihu dosyasıyla karşılaştırılır.
  2. Gerçek ses öznitelikleriyle, akış durumu taşınarak birkaç parça boyunca encoder çıktıları karşılaştırılır.
  3. İsteğe bağlı: --wav-dir verilirse sherpa-onnx ile iki modelin transkriptleri karşılaştırılır.

Kullanım: .venv-export/Scripts/python verify_recovery.py --ckpt exp/mihu-v1/epoch-0.pt --onnx-dir <v1> \
            --out exp/mihu-v1/onnx [--wav-dir ../tests/audio]
"""
from __future__ import annotations

import argparse
import sys
import warnings
import wave
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import onnx  # noqa: E402
import onnxruntime as ort  # noqa: E402
import torch  # noqa: E402
from onnx import numpy_helper  # noqa: E402

import zcommon  # noqa: E402
from recover_checkpoint import first_existing, gemm_transb_inits, matmulinteger_inits, onnx_tensors  # noqa: E402


def inits(p: Path) -> dict[str, np.ndarray]:
    return onnx_tensors(p)  # int8 dosyalar fp32'ye çevrilerek okunur


def fbank(wav: Path) -> np.ndarray:
    import kaldi_native_fbank as knf
    with wave.open(str(wav)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    opts = knf.FbankOptions()
    opts.frame_opts.dither = 0
    opts.frame_opts.snip_edges = False
    opts.frame_opts.samp_freq = 16000
    opts.mel_opts.num_bins = 80
    opts.mel_opts.high_freq = -400
    fb = knf.OnlineFbank(opts)
    fb.accept_waveform(16000, pcm.tolist())
    fb.input_finished()
    return np.stack([fb.get_frame(i) for i in range(fb.num_frames_ready)]).astype(np.float32)


def run_stream(sess: ort.InferenceSession, feats: np.ndarray, n_chunks: int) -> list[np.ndarray]:
    meta = sess.get_modelmeta().custom_metadata_map
    T, shift = int(meta["T"]), int(meta["decode_chunk_len"])
    states = {}
    for i in sess.get_inputs()[1:]:
        shape = [1 if not isinstance(d, int) else d for d in i.shape]
        dtype = np.int64 if "int64" in i.type else np.float32
        states[i.name] = np.zeros(shape, dtype=dtype)
    outs = []
    out_names = [o.name for o in sess.get_outputs()]
    for c in range(n_chunks):
        x = feats[c * shift: c * shift + T]
        if len(x) < T:
            x = np.pad(x, ((0, T - len(x)), (0, 0)))
        res = sess.run(None, {"x": x[None], **states})
        outs.append(res[0])
        for name, val in zip(out_names[1:], res[1:]):
            states[name.replace("new_", "", 1)] = val
    return outs


def sherpa_transcripts(model_dir: Path, enc: str, dec: str, joi: str, wavs: list[Path]) -> list[str]:
    import sherpa_onnx
    rec = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(model_dir / "tokens.txt"), encoder=enc, decoder=dec, joiner=joi, num_threads=2,
        decoding_method="greedy_search")
    out = []
    for w in wavs:
        with wave.open(str(w)) as f:
            pcm = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        s = rec.create_stream()
        s.accept_waveform(16000, pcm)
        s.accept_waveform(16000, np.zeros(16000, dtype=np.float32))
        s.input_finished()
        while rec.is_ready(s):
            rec.decode_stream(s)
        out.append(rec.get_result(s).strip())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--onnx-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--wav-dir")
    a = ap.parse_args()
    src, out = Path(a.onnx_dir), Path(a.out)

    model = zcommon.build_model()
    model.load_state_dict(torch.load(a.ckpt, map_location="cpu")["model"])
    files = zcommon.export_onnx(model, out, quantize=True)

    ok = True
    src_enc = first_existing(src, "encoder.onnx", "encoder.int8.onnx")
    src_dec = first_existing(src, "decoder.onnx", "decoder.int8.onnx")
    src_joi = first_existing(src, "joiner.onnx", "joiner.int8.onnx")
    quantized_src = "int8" in src_enc.name
    tol = 1e-5 if not quantized_src else 1e-3  # int8 kaynakta yeniden kuantalama yuvarlaması
    for part, theirs in (("encoder", src_enc), ("decoder", src_dec)):
        A, B = inits(files[part]), inits(theirs)
        for name in gemm_transb_inits(files[part]) & matmulinteger_inits(theirs):
            B[name] = B[name].T  # int8 dosyada Gemm ağırlığı transpoze saklanır
        diffs = [float(np.abs(A[k].astype(np.float64) - B[k].astype(np.float64)).max()) for k in B if k in A]
        missing = [k for k in B if k not in A]
        worst = max(diffs) if diffs else float("nan")
        print(f"[1] {part}: {len(B)} başlatıcı, eksik {len(missing)}, en büyük fark {worst:.2e}")
        ok &= not missing and worst < tol

    wavs = sorted(Path(a.wav_dir).glob("*.wav")) if a.wav_dir else []
    if wavs:
        feats = fbank(wavs[0])
        so = ort.SessionOptions()
        so.log_severity_level = 3
        s1 = ort.InferenceSession(str(files["encoder"]), so, providers=["CPUExecutionProvider"])
        s2 = ort.InferenceSession(str(src_enc), so, providers=["CPUExecutionProvider"])
        if quantized_src:  # int8 kaynakla, bizim int8 dışa aktarımı karşılaştır
            s1 = ort.InferenceSession(str(files["encoder_int8"]), so, providers=["CPUExecutionProvider"])
        n = max(1, (len(feats) - 13) // 32)
        o1, o2 = run_stream(s1, feats, n), run_stream(s2, feats, n)
        d = max(float(np.abs(x - y).max()) for x, y in zip(o1, o2))
        rel = d / max(float(np.abs(np.concatenate(o2)).max()), 1e-9)
        print(f"[2] encoder çıktısı, {n} parça akış ({wavs[0].name}): en büyük fark {d:.2e} (göreli {rel:.2e})")
        ok &= rel < (1e-4 if not quantized_src else 5e-2)

        k = "_int8" if quantized_src else ""
        t_ours = sherpa_transcripts(src, str(files["encoder" + k]), str(files["decoder" + k]), str(files["joiner" + k]), wavs)
        t_ref = sherpa_transcripts(src, str(src_enc), str(src_dec), str(src_joi), wavs)
        same = sum(x == y for x, y in zip(t_ours, t_ref))
        from difflib import SequenceMatcher
        sim = float(np.mean([SequenceMatcher(None, x, y).ratio() for x, y in zip(t_ours, t_ref)]))
        # ağırlık/çıktı eşleşmesi tek başına yeterli değil: transkriptler de neredeyse aynı olmalı
        ok &= sim >= 0.98
        print(f"[3] sherpa-onnx transkript: {same}/{len(wavs)} birebir aynı, ortalama karakter benzerliği {sim:.3f}")
        for x, y, w in zip(t_ours, t_ref, wavs):
            if x != y:
                print(f"    {w.name}\n      biz : {x}\n      mihu: {y}")
    print("SONUÇ:", "DOĞRULANDI" if ok else "FARK VAR")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
