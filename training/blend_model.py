"""İnce ayarlı modeli temel modelle ağırlık düzeyinde karıştırır (WiSE-FT): w = a * ince_ayar + (1 - a) * temel.

İnce ayar radyolojiyi öğretirken genel Türkçeden bir şey götürebilir; karıştırma bunu geri getirir. Ara denemede
(04.11, 5 bin radyoloji klibi): FLEURS hata oranı ince ayarlı modelde %11,2, a=0,7 karışımında %7,9 (temel: %9,1);
radyoloji testi %3,6 -> %4,1. Eğitim gerektirmez; iki checkpoint aynı mimaride olmalı.

  python blend_model.py --ft exp/rad-ft1/best.pt --base exp/mihu-v2/epoch-0.pt --alpha 0.7 --out exp/rad-ft1/blend-0.7.pt
"""
from __future__ import annotations

import argparse

import torch


def blend(ft: dict, base: dict, alpha: float) -> dict:
    """Kayan noktalı tensörler karıştırılır (dtype korunur); tamsayı tamponlar ince ayarlı modelden alınır."""
    if ft.keys() != base.keys():
        raise ValueError(f"modeller uyuşmuyor: {sorted(ft.keys() ^ base.keys())[:5]}")
    out = {}
    for k, v in ft.items():
        if v.is_floating_point():
            out[k] = (alpha * v.float() + (1 - alpha) * base[k].float()).to(v.dtype)
        else:
            out[k] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ft", required=True, help="ince ayarlı checkpoint")
    ap.add_argument("--base", required=True, help="temel model checkpoint'i (ince ayarın başladığı)")
    ap.add_argument("--alpha", type=float, required=True, help="ince ayarın payı (1: yalnız ince ayar, 0: temel)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ft = torch.load(a.ft, map_location="cpu", weights_only=False)
    base = torch.load(a.base, map_location="cpu", weights_only=False)
    torch.save({**ft, "model": blend(ft["model"], base["model"], a.alpha), "blend": {"alpha": a.alpha, "base": a.base}},
               a.out)
    print(f"{a.out}: karışım a={a.alpha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
