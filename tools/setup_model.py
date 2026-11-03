"""Varsayılan modeli (mihuai/turkish-stt-66m-v2) indirir, hotword için bpe.vocab üretir,
model.json yazar ve offline modeller için Silero VAD'ı indirir.

Kullanım:  python tools/setup_model.py [--repo mihuai/turkish-stt-66m-v2] [--out models/tibbi-tr-v2]
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent.parent
VAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"


def export_bpe_vocab(bpe_model: Path, out: Path) -> None:
    import sentencepiece as spm
    sp = spm.SentencePieceProcessor(model_file=str(bpe_model))
    with out.open("w", encoding="utf-8") as f:
        for i in range(sp.get_piece_size()):
            f.write(f"{sp.id_to_piece(i)}\t{sp.get_score(i)}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="mihuai/turkish-stt-66m-v2")
    ap.add_argument("--out", default=str(ROOT / "models" / "tibbi-tr-v2"))
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    snapshot_download(a.repo, local_dir=out,
                      allow_patterns=["*.onnx", "tokens.txt", "bpe.model", "config.json", "LICENSE"])
    cfg = json.loads((out / "config.json").read_text(encoding="utf-8"))
    files = cfg["files"]

    spec = {
        "name": "Türkçe Tıbbi Dikte v2",
        "engine": "sherpa-onnx",
        "mode": "online" if cfg.get("streaming", True) else "offline",
        "type": "transducer",
        "tokens": files["tokens"],
        "encoder": files["encoder"],
        "decoder": files["decoder"],
        "joiner": files["joiner"],
        "sample_rate": cfg.get("sample_rate", 16000),
        "feature_dim": cfg.get("feature_dim", 80),
        "decoding_method": cfg.get("decoding_method", "modified_beam_search"),
        "max_active_paths": cfg.get("max_active_paths", 4),
        "rule2_min_trailing_silence": 0.8,
        "license": "mihu Community License",
        "attribution": "Powered by mihu",
    }
    if files.get("bpe_model"):
        export_bpe_vocab(out / files["bpe_model"], out / "bpe.vocab")
        spec.update(modeling_unit="bpe", bpe_vocab="bpe.vocab")
    (out / "model.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    vad = ROOT / "app" / "silero_vad.onnx"
    if not vad.exists():
        urllib.request.urlretrieve(VAD_URL, vad)
    print(f"Model hazır: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
