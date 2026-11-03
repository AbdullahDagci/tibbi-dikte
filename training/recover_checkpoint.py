"""mihuai/turkish-stt (v1, fp32 ONNX) -> icefall PyTorch checkpoint.

Yöntem (parmak izi):
  1. Aynı mimaride icefall modeli kurulur, her parametreye *farklı* rastgele değer verilir.
  2. Bu model mihu'nun kullandığı dışa aktarma yolu (icefall export-onnx-streaming, torch 2.4.1) ile ONNX'e
     aktarılır. Anonim başlatıcı adları (onnx::MatMul_12815 …) bu sayede mihu dosyasındakiyle birebir aynıdır.
  3. Bizim ONNX'teki her başlatıcının hangi parametreden hangi dönüşümle (kimlik, transpoz, dilim, yeniden
     şekillendirme) geldiği değerlerden çözülür.
  4. Aynı kural mihu ONNX'ine ters uygulanır -> state_dict.
  5. Joiner yalnızca int8 yayınlandığı için doğrusal olarak geri çevrilir (dequantize).
  Eğitim-dışı kalan simple_am_proj / simple_lm_proj (pruned RNN-T yardımcı kaybı) rastgele kalır; fine-tuning'in
  ilk adımlarında yeniden öğrenilir.

Kullanım (torch 2.4.1 ortamı):
  .venv-export/Scripts/python recover_checkpoint.py --onnx-dir <v1 klasörü> --out exp/mihu-v1/epoch-0.pt
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import onnx  # noqa: E402
import torch  # noqa: E402
from onnx import numpy_helper  # noqa: E402

import zcommon  # noqa: E402


def onnx_tensors(path: Path) -> dict[str, np.ndarray]:
    """Başlatıcılar; int8 (onnxruntime quantize_dynamic) dosyalarda X_quantized/X_scale/X_zero_point -> X (fp32)."""
    m = onnx.load(str(path))
    t = {x.name: numpy_helper.to_array(x) for x in m.graph.initializer}
    for name in [k for k in t if k.endswith("_quantized")]:
        base = name[: -len("_quantized")]
        scale, zp = t.get(base + "_scale"), t.get(base + "_zero_point")
        if scale is None or zp is None:
            continue
        t[base] = ((t.pop(name).astype(np.float32) - zp.astype(np.float32)) * scale.astype(np.float32))
        t.pop(base + "_scale"), t.pop(base + "_zero_point")
    return t


def gemm_transb_inits(path: Path) -> set[str]:
    """Gemm(transB=1) ile kullanılan başlatıcılar (PyTorch nn.Linear'ın 2B girdili dışa aktarımı)."""
    g = onnx.load(str(path)).graph
    out = set()
    for n in g.node:
        if n.op_type == "Gemm" and any(a.name == "transB" and a.i == 1 for a in n.attribute):
            out.add(n.input[1])
    return out


def matmulinteger_inits(path: Path) -> set[str]:
    """int8 dosyada MatMulInteger'a giren ağırlıklar (adın _quantized öncesi kısmı).
    onnxruntime, Gemm(transB=1)'i MatMulInteger'a çevirirken ağırlığı [K, N] olacak şekilde transpoze eder."""
    g = onnx.load(str(path)).graph
    return {i[: -len("_quantized")] for n in g.node if n.op_type == "MatMulInteger"
            for i in n.input if i.endswith("_quantized")}


def first_existing(d: Path, *names: str) -> Path:
    for n in names:
        if (d / n).exists():
            return d / n
    raise FileNotFoundError(f"{d}: {names}")


def fingerprint_rules(model: torch.nn.Module, prefix_map: dict[str, str], exported: dict[str, np.ndarray]):
    """Her ONNX başlatıcısı için (parametre adı, dönüşüm) kuralını değerlerden bulur."""
    params = {}
    for name, p in model.named_parameters():
        params[name] = p.detach().cpu().numpy()

    def onnx_to_param_name(n: str) -> str | None:
        for onnx_prefix, model_prefix in prefix_map.items():
            if n.startswith(onnx_prefix):
                cand = model_prefix + n[len(onnx_prefix):]
                if cand in params:
                    return cand
        return None

    # hızlı arama: ilk birkaç değerin parmak izi -> (parametre, dönüşüm)
    index: dict[tuple, list[tuple[str, str]]] = {}
    def add(key_arr: np.ndarray, pname: str, kind: str):
        flat = key_arr.ravel()
        if flat.size < 2:
            return
        index.setdefault((round(float(flat[0]), 6), round(float(flat[1]), 6)), []).append((pname, kind))
    for pname, arr in params.items():
        add(arr, pname, "id")
        if arr.ndim == 2:
            add(arr.T, pname, "T")
        if arr.ndim >= 2:
            for j in range(arr.shape[0]):
                add(arr[j], pname, f"sub{j}")
        if arr.ndim == 3:
            add(arr[:, 0, :], pname, "squeeze1")
        if pname.endswith("downsample.bias") or pname.endswith("downsample_output.bias"):
            e = np.exp(arr - arr.max())
            add(e / e.sum(), pname, "softmax")  # SimpleDownsample: ONNX'te softmax(bias) sabit olarak katlanır

    def apply(arr: np.ndarray, kind: str) -> np.ndarray:
        if kind == "id":
            return arr
        if kind == "T":
            return arr.T
        if kind.startswith("sub"):
            return arr[int(kind[3:])]
        if kind == "squeeze1":
            return arr[:, 0, :]
        if kind == "softmax":
            e = np.exp(arr - arr.max())
            return e / e.sum()
        raise ValueError(kind)

    rules: dict[str, tuple[str, str]] = {}
    unresolved = []
    for oname, val in exported.items():
        direct = onnx_to_param_name(oname)
        if direct is not None and params[direct].shape == val.shape and np.allclose(params[direct], val):
            rules[oname] = (direct, "id")
            continue
        flat = val.ravel()
        hit = None
        if flat.size >= 2:
            for pname, kind in index.get((round(float(flat[0]), 6), round(float(flat[1]), 6)), []):
                cand = apply(params[pname], kind)
                if cand.size == val.size and np.allclose(cand.reshape(val.shape), val, atol=1e-6):
                    hit = (pname, kind)
                    break
        if hit:
            rules[oname] = hit
        else:
            unresolved.append((oname, val.shape))
    return rules, unresolved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx-dir", required=True, help="encoder.onnx, decoder.onnx, joiner.int8.onnx içeren klasör")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    src = Path(a.onnx_dir)
    torch.manual_seed(0)

    model = zcommon.build_model()
    with torch.no_grad():
        for p in model.parameters():  # her parametreye ayırt edilebilir değer
            p.copy_(torch.randn_like(p) * 0.1 + torch.rand(()) * 0.01)

    with tempfile.TemporaryDirectory() as td:
        files = zcommon.export_onnx(model, Path(td), quantize=False)
        ours = {k: onnx_tensors(files[k]) for k in ("encoder", "decoder", "joiner")}
        gemm_t = {k: gemm_transb_inits(files[k]) for k in ("encoder", "decoder", "joiner")}

    prefix = {
        "encoder": {"encoder_embed.": "encoder_embed.", "encoder_proj.": "joiner.encoder_proj.", "encoder.": "encoder."},
        "decoder": {"decoder_proj.": "joiner.decoder_proj.", "decoder.": "decoder."},
        "joiner": {"output_linear.": "joiner.output_linear."},
    }
    mihu = {
        "encoder": onnx_tensors(first_existing(src, "encoder.onnx", "encoder.int8.onnx")),
        "decoder": onnx_tensors(first_existing(src, "decoder.onnx", "decoder.int8.onnx")),
    }
    # Gemm -> MatMulInteger dönüşümünde transpoze edilmiş ağırlıkları geri çevir (kare matrislerde şekilden anlaşılmaz)
    src_files = {"encoder": first_existing(src, "encoder.onnx", "encoder.int8.onnx"),
                 "decoder": first_existing(src, "decoder.onnx", "decoder.int8.onnx")}
    for part, f in src_files.items():
        for name in gemm_t[part] & matmulinteger_inits(f):
            mihu[part][name] = mihu[part][name].T
    # joiner (int8 ise fp32'ye çevrilmiş gelir; şekli [512,500] olduğundan aşağıda şekle göre yönlenir)
    jq = onnx_tensors(first_existing(src, "joiner.onnx", "joiner.int8.onnx"))
    w = jq["output_linear.weight"]
    mihu["joiner"] = {}
    for oname, val in ours["joiner"].items():
        if oname == "output_linear.bias":
            mihu["joiner"][oname] = jq["output_linear.bias"]
        elif val.shape == w.shape:
            mihu["joiner"][oname] = w
        elif val.shape == w.T.shape:
            mihu["joiner"][oname] = w.T

    state = {k: v.clone() for k, v in model.state_dict().items()}
    filled: dict[str, np.ndarray] = {}
    report = []
    for part in ("encoder", "decoder", "joiner"):
        rules, unresolved = fingerprint_rules(model, prefix[part], ours[part])
        missing_in_mihu = [n for n in ours[part] if n not in mihu[part]]
        report.append(f"{part}: {len(ours[part])} başlatıcı, kural {len(rules)}, çözülemeyen {len(unresolved)}, "
                      f"mihu'da olmayan {len(missing_in_mihu)}")
        if unresolved:
            report.append(f"   çözülemeyen örnek: {unresolved[:5]}")
        for oname, (pname, kind) in rules.items():
            if oname not in mihu[part]:
                continue
            val = mihu[part][oname]
            target = filled.setdefault(pname, state[pname].numpy().copy())
            if kind == "id":
                target[...] = val.reshape(target.shape)
            elif kind == "T":
                target[...] = val.T
            elif kind.startswith("sub"):
                target[int(kind[3:])] = val.reshape(target[int(kind[3:])].shape)
            elif kind == "squeeze1":
                target[:, 0, :] = val
            elif kind == "softmax":
                target[...] = np.log(np.clip(val.reshape(target.shape), 1e-30, None))  # softmax sabit kaymaya duyarsız
    for pname, arr in filled.items():
        state[pname] = torch.from_numpy(arr)
    all_params = [n for n, _ in model.named_parameters()]
    # Çıkarımda kullanılmayan parametreler: Zipformer2EncoderLayer.bypass_scale ("TODO: remove it", icefall)
    # ve pruned RNN-T yardımcı projeksiyonları. Varsayılan/rastgele değerde kalırlar.
    unused = [n for n in all_params if n not in filled and (
        n.endswith("bypass_scale") and ".bypass." not in n and ".bypass_mid." not in n and "out_combiner" not in n
        or n.startswith(("simple_am_proj", "simple_lm_proj")))]
    for n in unused:
        if n.startswith("simple_"):
            continue
        state[n] = torch.full_like(state[n], 0.5)
    not_filled = [n for n in all_params if n not in filled and n not in unused]
    report.append(f"çıkarımda kullanılmayan (varsayılanda bırakıldı): {len(unused)}")
    model.load_state_dict(state)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"model": model.state_dict(), "recovered_from": str(src), "not_recovered": not_filled}, out)
    print("\n".join(report))
    print(f"parametre: {len(all_params)}, kurtarılan {len(filled)}, kurtarılamayan {len(not_filled)}: {not_filled}")
    print(f"kaydedildi: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
