"""Checkpoint -> uygulamaya hazır model klasörü (int8 streaming ONNX + model.json).

  python export_model.py --ckpt exp/rad-ft/averaged.pt --name mihu-tr-radyoloji-ft1 \
      --title "mihu Türkçe + radyoloji ince ayar 1"
Çıktı: ../models/<ad>/ {encoder,decoder,joiner}.int8.onnx, tokens.txt, bpe.model, bpe.vocab, model.json, LICENSE
Uygulama bu klasörü otomatik bulur: Ayarlar > Genel > STT modeli.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import torch  # noqa: E402

import zcommon  # noqa: E402

BASE = HERE.parent / "models" / "tibbi-tr-v2"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--out-root", default=str(HERE.parent / "models"))
    ap.add_argument("--lang-dir", help="B yolu: kendi bpe.model/tokens.txt klasörümüz (train_bpe.py çıktısı)")
    ap.add_argument("--independent", action="store_true",
                    help="B yolu: mihu ağırlıklarından bağımsız eğitildi -> mihu atfı/lisansı eklenmez")
    a = ap.parse_args()

    ck = torch.load(a.ckpt, map_location="cpu")
    state = ck["model"]
    lang = Path(a.lang_dir) if a.lang_dir else (Path(ck["bpe_model"]).parent if ck.get("bpe_model") else BASE)
    if a.independent and lang.resolve() == BASE.resolve():
        raise SystemExit("--independent için mihu'nun bpe.model'i kullanılamaz: --lang-dir ile kendi sözlüğünüzü verin")
    vocab = state["joiner.output_linear.weight"].shape[0]
    model = zcommon.build_model(vocab_size=vocab)  # çıkarım yapılandırması: chunk 16, left context 128
    model.load_state_dict(state, strict=True)
    out = Path(a.out_root) / a.name
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        files = zcommon.export_onnx(model, Path(td), quantize=True)
        for k in ("encoder", "decoder", "joiner"):
            shutil.copy(files[f"{k}_int8"], out / f"{k}.int8.onnx")
    for f in ("tokens.txt", "bpe.model", "bpe.vocab"):
        if (lang / f).exists():
            shutil.copy(lang / f, out / f)
    if not (out / "bpe.vocab").exists():  # hotword'ler için gerekli
        import sentencepiece as spm
        sp = spm.SentencePieceProcessor(model_file=str(out / "bpe.model"))
        lines = [f"{sp.id_to_piece(i)}\t{sp.get_score(i)}\n" for i in range(sp.get_piece_size())]
        (out / "bpe.vocab").write_text("".join(lines), encoding="utf-8")
    if not a.independent and (BASE / "LICENSE").exists():
        shutil.copy(BASE / "LICENSE", out / "LICENSE")
    spec = json.loads((BASE / "model.json").read_text(encoding="utf-8"))
    spec.update(name=a.title, encoder="encoder.int8.onnx", decoder="decoder.int8.onnx", joiner="joiner.int8.onnx",
                tokens="tokens.txt", bpe_vocab="bpe.vocab", modeling_unit="bpe", finetuned_from=str(Path(a.ckpt).name))
    if a.independent:  # B yolu: kendi modelimiz
        spec.pop("attribution", None)
        spec.update(base_model="(bağımsız; mihu ağırlıkları kullanılmadı)", license="Ertansa — tescilli")
    else:
        spec.update(base_model="mihuai/turkish-stt-66m-v2",
                # Ince ayarlı model de mihu türevidir: atıf zorunluluğu devam eder (lisans md. 4a, 5b).
                # Yalnızca mihu ağırlıklarından bağımsız (sıfırdan) eğitilmiş bir modelde bu alan kaldırılabilir.
                    attribution="Powered by mihu",
                    license="mihu Community License")
    (out / "model.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"model klasörü: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
