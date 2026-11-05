"""icefall Zipformer2 (streaming, medium) ortak yardımcıları: model kurma ve ONNX dışa aktarma.

mihuai/turkish-stt ile aynı yapılandırma (ONNX metadata'sından ve ağırlık şekillerinden çıkarıldı):
  num_encoder_layers 2,2,3,4,3,2 · encoder_dim 192,256,384,512,384,256 · feedforward 512,768,1024,1536,1024,768
  num_heads 4,4,4,8,4,4 · query/value/pos head dim 32/12/4 · kernels 31,31,15,15,15,31
  causal, chunk 16 (decode_chunk_len 32), left context 128 · decoder/joiner 512 · vocab 500 BPE · context 2
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZIP = HERE / "icefall" / "egs" / "librispeech" / "ASR" / "zipformer"
# Gerçek k2 kuruluysa (Linux+CUDA) onu kullan; yoksa CPU shim'i
try:
    import k2  # noqa: F401
    if getattr(k2, "__version__", "") == "0.0-shim":
        raise ImportError
except ImportError:
    sys.path.insert(0, str(HERE / "shims"))
for p in (HERE / "icefall", ZIP):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import torch  # noqa: E402
import train as _train  # noqa: E402  (icefall zipformer/train.py)

VOCAB_SIZE = 500
STREAMING = dict(causal=True, chunk_size="16", left_context_frames="128")


def get_params(vocab_size: int = VOCAB_SIZE, **overrides):
    # Tam icefall ayrıştırıcısı: model ayarları + compute_loss'un kullandığı eğitim varsayılanları
    # (prune_range, lm_scale, am_scale, simple_loss_scale …); yalnızca model ayarları eğitimi kırar.
    args = _train.get_parser().parse_args([])
    params = _train.get_params()
    params.update(vars(args))
    params.update(STREAMING)
    params.update(vocab_size=vocab_size, blank_id=0, context_size=2,
                  use_transducer=True, use_ctc=False, use_attention_decoder=False,
                  spec_aug_time_warp_factor=80)  # veri modülü ayarı; compute_loss koşulsuz okur
    params.update(overrides)
    return params


def build_model(vocab_size: int = VOCAB_SIZE, **overrides) -> torch.nn.Module:
    return _train.get_model(get_params(vocab_size, **overrides))


def _load_export_module():
    spec = importlib.util.spec_from_file_location("icefall_export_onnx_streaming", ZIP / "export-onnx-streaming.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def export_onnx(model: torch.nn.Module, out_dir: Path, quantize: bool = True) -> dict[str, Path]:
    """icefall'ın kendi dışa aktarma kodu ile sherpa-onnx uyumlu streaming encoder/decoder/joiner üretir."""
    import copy

    from scaling_converter import convert_scaled_to_non_scaled

    ex = _load_export_module()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    m = copy.deepcopy(model).to("cpu").eval()
    convert_scaled_to_non_scaled(m, inplace=True)

    # torch>=2.9'da varsayılan dynamo dışa aktarıcıdır; icefall TorchScript tabanlı yolu bekler
    orig = torch.onnx.export
    def _export(*a, **k):
        k.setdefault("dynamo", False)
        return orig(*a, **k)
    torch.onnx.export = _export
    try:
        enc = ex.OnnxEncoder(encoder=m.encoder, encoder_embed=m.encoder_embed, encoder_proj=m.joiner.encoder_proj)
        dec = ex.OnnxDecoder(decoder=m.decoder, decoder_proj=m.joiner.decoder_proj)
        joi = ex.OnnxJoiner(output_linear=m.joiner.output_linear)
        files = {k: out_dir / f"{k}.onnx" for k in ("encoder", "decoder", "joiner")}
        ex.export_encoder_model_onnx(enc, str(files["encoder"]), opset_version=13, feature_dim=80,
                                     dynamic_batch=True, use_int32_inputs=False,
                                     use_whisper_features=False, use_external_data=False)
        ex.export_decoder_model_onnx(dec, files["decoder"], opset_version=13, dynamic_batch=True,
                                     use_int32_inputs=False)
        ex.export_joiner_model_onnx(joi, files["joiner"], opset_version=13, dynamic_batch=True)
    finally:
        torch.onnx.export = orig

    if quantize:
        from onnxruntime.quantization import QuantType, quantize_dynamic
        for k in list(files):
            q = out_dir / f"{k}.int8.onnx"
            quantize_dynamic(model_input=str(files[k]), model_output=str(q),
                             op_types_to_quantize=["MatMul"], weight_type=QuantType.QInt8)
            files[f"{k}_int8"] = q
    return files
