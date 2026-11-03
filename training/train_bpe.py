"""Kendi Türkçe BPE sözlüğümüz (B yolu: mihu'dan bağımsız model).

mihu'nun bpe.model'i onların materyalidir; bağımsız modelde kullanılmaz. Bu betik eğitim transkriptlerinden
(data/manifests/*_train) + rapor metinlerinden (isteğe bağlı) icefall uyumlu BPE ve tokens.txt üretir.
Metinler zaten model çıktı biçiminde (büyük/küçük harf, noktalama, sayılar yazıyla) — textnorm.py.

  python train_bpe.py --vocab-size 500 --out lang_tr_bpe500 [--extra-text ../data/reports/metinler.txt]
Çıktı: <out>/bpe.model, bpe.vocab, tokens.txt  (blank=0, <sos/eos>=1, <unk>=2 — icefall/sherpa düzeni)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sentencepiece as spm
from lhotse import CutSet

from textnorm import normalize

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vocab-size", type=int, default=500)
    ap.add_argument("--out", default=str(HERE / "lang_tr_bpe500"))
    ap.add_argument("--manifests", default=str(HERE / "data" / "manifests"))
    ap.add_argument("--extra-text", action="append", default=[], help="ek metin dosyası (satır başına cümle)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    corpus = out / "transcripts.txt"
    n = 0
    with corpus.open("w", encoding="utf-8") as f:
        for man in sorted(Path(a.manifests).glob("*_train.jsonl.gz")):
            for c in CutSet.from_file(man):
                for s in c.supervisions:
                    f.write(s.text + "\n")
                    n += 1
        for extra in a.extra_text:
            for line in Path(extra).read_text(encoding="utf-8").splitlines():
                t = normalize(line.strip(), restore_case=True)
                if t:
                    f.write(t + "\n")
                    n += 1
    print(f"{n} satır -> {corpus}")
    spm.SentencePieceTrainer.train(
        input=str(corpus), model_prefix=str(out / "bpe"), model_type="unigram", vocab_size=a.vocab_size,
        character_coverage=1.0, input_sentence_size=10_000_000, shuffle_input_sentence=True,
        user_defined_symbols=["<blk>", "<sos/eos>"], unk_id=2, bos_id=-1, eos_id=-1)
    sp = spm.SentencePieceProcessor(model_file=str(out / "bpe.model"))
    with (out / "tokens.txt").open("w", encoding="utf-8") as f:
        for i in range(sp.get_piece_size()):
            f.write(f"{sp.id_to_piece(i)} {i}\n")
    assert sp.piece_to_id("<blk>") == 0 and sp.piece_to_id("<sos/eos>") == 1 and sp.unk_id() == 2
    sample = "Sol L5 sinir kökü belirgin bası altındadır."
    print("örnek:", sp.encode(sample, out_type=str))
    print(f"-> {out}/bpe.model, tokens.txt ({sp.get_piece_size()} parça)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
