"""mihu Türkçe Zipformer2 (streaming) için alan ince ayarı (fine-tuning).

icefall'ın kendi model / kayıp / ScaledAdam / Eden bileşenlerini kullanır; farkları:
  * Başlangıç: recover_checkpoint.py çıktısı (--init-ckpt). Sözlük (500 BPE) aynı -> decoder/joiner korunur.
  * Veri karıştırma (--train "ad:ağırlık,..."): genel Türkçe + tıbbi/radyoloji. Unutmayı (catastrophic
    forgetting) önlemek için genel veri her zaman karışımda olmalı.
  * Isınma: ONNX'te bulunmayan simple_am_proj/simple_lm_proj (pruned RNN-T yardımcıları) rastgele başlar;
    ilk --warmup-simple-steps adımda yalnızca bunlar eğitilir, gövde dondurulur.
  * Akış: eğitimde icefall varsayılanı gibi rastgele parça boyu (16,32,64,tam) -> çıkarımda 16/128 dışa aktarılır.
  * --loss torchaudio: k2 olmayan ortamlarda (Windows/CPU) tam RNN-T kaybı — YALNIZCA duman testi içindir.
    Gerçek eğitim: Linux + CUDA + k2 ile --loss k2 (pruned RNN-T, varsayılan).

Örnek (GPU sunucusu):
  python finetune.py --init-ckpt exp/mihu-v2/epoch-0.pt --exp-dir exp/rad-ft \\
      --train issai_train:4,commonvoice_train:2,mediaspeech_train:1,fleurs_train:1,medv3_train:2,radsynth_train:3,radreal_train:4 \\
      --valid fleurs_dev,radiology_real_test --max-duration 600 --num-steps 30000 --base-lr 0.002
"""
from __future__ import annotations

import os as _os
import sys as _sys
if _sys.platform == "win32" and not _sys.flags.utf8_mode:  # lhotse dosyaları varsayılan kodlamayla (cp1254) yazar
    import subprocess as _sp
    _sys.exit(_sp.call([_sys.executable, "-X", "utf8", *_sys.argv]))


import argparse
import copy
import logging
import math
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import zcommon  # noqa: E402  (sys.path: k2 shim / icefall / zipformer)

import sentencepiece as spm  # noqa: E402
import torch  # noqa: E402
from lhotse import CutSet  # noqa: E402
from lhotse.dataset import DynamicBucketingSampler, K2SpeechRecognitionDataset, SpecAugment  # noqa: E402
from lhotse.dataset.input_strategies import OnTheFlyFeatures, PrecomputedFeatures  # noqa: E402

import train as T  # noqa: E402  icefall zipformer/train.py
from optim import Eden, ScaledAdam  # noqa: E402

log = logging.getLogger("finetune")
FBANK = HERE / "data" / "fbank"
MAN = HERE / "data" / "manifests"
BPE = HERE.parent / "models" / "tibbi-tr-v2" / "bpe.model"


def load_cuts(name: str) -> tuple[CutSet, bool]:
    """Önce öznitelikli (fbank) manifest, yoksa ham manifest (anında öznitelik)."""
    for d, pre in ((FBANK, True), (MAN, False)):
        f = d / f"{name}.jsonl.gz"
        if f.exists():
            return CutSet.from_file(f), pre
    raise FileNotFoundError(f"manifest yok: {name} ({FBANK} veya {MAN})")


def make_loader(names_weights: list[tuple[str, float]], max_duration: float, train: bool, num_workers: int):
    sets, precomputed = [], []
    for name, _ in names_weights:
        cs, pre = load_cuts(name)
        sets.append(cs.filter(lambda c: 0.5 <= c.duration <= 20.0))
        precomputed.append(pre)
    if len(set(precomputed)) > 1:
        raise ValueError("Tüm eğitim manifestleri ya fbank'li ya ham olmalı (prepare_data.py fbank çalıştırın)")
    if train:
        weights = [w for _, w in names_weights]
        cuts = CutSet.mux(*[s.repeat() for s in sets], weights=weights) if len(sets) > 1 else sets[0].repeat()
    else:
        cuts = sets[0] if len(sets) == 1 else CutSet.from_cuts(c for s in sets for c in s)
    strategy = PrecomputedFeatures() if precomputed[0] else OnTheFlyFeatures(
        __import__("lhotse").Fbank(__import__("lhotse").FbankConfig(num_mel_bins=80)))
    ds = K2SpeechRecognitionDataset(
        input_strategy=strategy, return_cuts=True,
        input_transforms=[SpecAugment(time_warp_factor=80, num_frame_masks=10, features_mask_size=27,
                                      num_feature_masks=2, frames_mask_size=100)] if train else [])
    sampler = DynamicBucketingSampler(cuts, max_duration=max_duration, shuffle=train, num_buckets=20 if train else 5,
                                      buffer_size=20000 if train else 5000, drop_last=train)
    return torch.utils.data.DataLoader(ds, sampler=sampler, batch_size=None, num_workers=num_workers,
                                       persistent_workers=num_workers > 0)


# ------------------------------------------------------------------ kayıplar
def loss_k2(params, model, sp, batch, is_training):
    loss, info = T.compute_loss(params, model, sp, batch, is_training)
    return loss, {"loss": info["loss"], "frames": info["frames"],
                  "simple": info.get("simple_loss", 0.0), "pruned": info.get("pruned_loss", 0.0)}


def loss_torchaudio(params, model, sp, batch, is_training):
    """Tam (budanmamış) RNN-T kaybı — k2 gerektirmez; küçük partilerle CPU duman testi için."""
    import torchaudio.functional as AF
    device = next(model.parameters()).device
    x = batch["inputs"].to(device)
    x_lens = batch["supervisions"]["num_frames"].to(device)
    ys = sp.encode(batch["supervisions"]["text"], out_type=int)
    with torch.set_grad_enabled(is_training):
        enc, enc_lens = model.forward_encoder(x, x_lens)
        U = max(len(y) for y in ys)
        blank = params.blank_id
        sos = torch.full((len(ys), U + 1), blank, dtype=torch.int64, device=device)
        tgt = torch.zeros((len(ys), U), dtype=torch.int32, device=device)
        for i, y in enumerate(ys):
            sos[i, 1:len(y) + 1] = torch.tensor(y)
            tgt[i, :len(y)] = torch.tensor(y, dtype=torch.int32)
        dec = model.decoder(sos)
        logits = model.joiner(model.joiner.encoder_proj(enc).unsqueeze(2),
                              model.joiner.decoder_proj(dec).unsqueeze(1), project_input=False)
        loss = AF.rnnt_loss(logits.float(), tgt, enc_lens.to(torch.int32),
                            torch.tensor([len(y) for y in ys], dtype=torch.int32, device=device),
                            blank=blank, reduction="sum")
    frames = int(enc_lens.sum().item())
    return loss, {"loss": loss.detach().item(), "frames": frames, "simple": 0.0, "pruned": 0.0}


# ------------------------------------------------------------------ ana döngü
def parse_weights(spec: str) -> list[tuple[str, float]]:
    out = []
    for part in spec.split(","):
        name, _, w = part.partition(":")
        out.append((name.strip(), float(w or 1)))
    return out


def evaluate(params, model, sp, loader, loss_fn, max_batches=200):
    model.eval()
    tot, frames = 0.0, 0
    for i, batch in enumerate(loader):
        if i >= max_batches:
            break
        loss, info = loss_fn(params, model, sp, batch, False)
        tot += info["loss"]
        frames += info["frames"]
    model.train()
    return tot / max(frames, 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--init-ckpt", help="başlangıç checkpoint'i (yoksa sıfırdan eğitim — B yolu)")
    ap.add_argument("--init-mode", choices=["full", "encoder"], default="full",
                    help="encoder: yalnızca kodlayıcıyı yükle (farklı sözlüklü modelden başlatma, ör. İngilizce)")
    ap.add_argument("--bpe-model", default=str(BPE), help="B yolu: train_bpe.py ile üretilen kendi bpe.model'imiz")
    ap.add_argument("--scratch", action="store_true",
                    help="sıfırdan/yeni sözlükle eğitim takvimi (ısınma, yüksek lr); --init-ckpt yoksa otomatik")
    ap.add_argument("--exp-dir", required=True)
    ap.add_argument("--train", required=True, help="ad:ağırlık,... (data/fbank veya data/manifests altında)")
    ap.add_argument("--valid", default="fleurs_dev")
    ap.add_argument("--max-duration", type=float, default=600, help="parti başına toplam saniye")
    ap.add_argument("--num-steps", type=int, default=30000)
    ap.add_argument("--base-lr", type=float, default=0.002, help="ince ayar için düşük (sıfırdan eğitim: 0.045)")
    ap.add_argument("--lr-batches", type=float, default=None,
                    help="Eden: ince ayarda 100000 (~sabit lr), sıfırdan eğitimde 7500 (icefall varsayılanı)")
    ap.add_argument("--warmup-simple-steps", type=int, default=300)
    ap.add_argument("--save-every", type=int, default=2000)
    ap.add_argument("--valid-every", type=int, default=1000)
    ap.add_argument("--keep-last", type=int, default=5)
    ap.add_argument("--loss", choices=["k2", "torchaudio"], default="k2")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--amp", choices=["none", "fp16", "bf16"], default="bf16")
    ap.add_argument("--num-workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    exp = Path(a.exp_dir)
    exp.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(exp / "train.log", encoding="utf-8")])
    torch.manual_seed(a.seed)
    device = torch.device(a.device)

    # Eğitim: icefall varsayılan çoklu parça boyları (akış dayanıklılığı); dışa aktarımda 16/128 sabitlenir
    sp = spm.SentencePieceProcessor(model_file=a.bpe_model)
    scratch = a.scratch or not a.init_ckpt
    if a.lr_batches is None:
        a.lr_batches = 7500.0 if scratch else 100000.0
    params = zcommon.get_params(vocab_size=sp.get_piece_size(), chunk_size="16,32,64,-1",
                                left_context_frames="64,128,256,-1")
    params.update(base_lr=a.base_lr, max_duration=a.max_duration, use_cr_ctc=False, use_fp16=a.amp == "fp16")
    model = T.get_model(params)
    if a.init_ckpt:
        state = torch.load(a.init_ckpt, map_location="cpu")["model"]
        if a.init_mode == "encoder":
            state = {k: v for k, v in state.items()
                     if k.startswith(("encoder.", "encoder_embed.", "joiner.encoder_proj."))}
        own = model.state_dict()
        skipped = [k for k, v in state.items() if k in own and own[k].shape != v.shape]
        state = {k: v for k, v in state.items() if k not in skipped}
        missing, unexpected = model.load_state_dict(state, strict=False)
        log.info("başlangıç: %s [%s] (yüklenen %d, eksik %d, şekil uyuşmayan %d)", a.init_ckpt, a.init_mode,
                 len(state), len(missing), len(skipped))
    else:
        log.info("sıfırdan eğitim (rastgele başlatma), sözlük: %s (%d)", a.bpe_model, sp.get_piece_size())
    model.to(device).train()
    loss_fn = loss_k2 if a.loss == "k2" else loss_torchaudio
    if a.loss == "torchaudio" and a.warmup_simple_steps:
        log.info("torchaudio kaybı simple_* projeksiyonlarını kullanmaz: ısınma atlanıyor")
        a.warmup_simple_steps = 0

    # Ön-eğitilmiş modelin eğitim sonu hâlini taklit et: dropout/atlama zamanlamaları son değerlerinde,
    # kayıp ölçekleri ısınma sonrası değerlerinde.
    if scratch:  # icefall'ın normal takvimi: kayıp ölçekleri ve dropout/atlama zamanlamaları adımla ilerler
        params.batch_idx_train = 0
        batch_count_offset = 0.0
        a.warmup_simple_steps = 0
    else:
        params.batch_idx_train = params.warm_step
        batch_count_offset = 200000.0

    optimizer = ScaledAdam(T.get_parameter_groups_with_lrs(model, lr=a.base_lr, include_names=True),
                           lr=a.base_lr, clipping_scale=2.0)
    scheduler = Eden(optimizer, a.lr_batches, 100.0, warmup_batches=500, warmup_start=0.1)

    use_amp = a.amp != "none" and device.type == "cuda"
    amp_dtype = torch.bfloat16 if a.amp == "bf16" else torch.float16
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp and a.amp == "fp16")

    train_dl = make_loader(parse_weights(a.train), a.max_duration, True, a.num_workers)
    valid_dl = make_loader([(n, 1) for n in a.valid.split(",")], a.max_duration, False, 0) if a.valid else None

    def set_trainable(simple_only: bool):
        for n, p in model.named_parameters():
            p.requires_grad = (n.startswith(("simple_am_proj", "simple_lm_proj")) or not simple_only)

    set_trainable(a.warmup_simple_steps > 0)
    step, t0, run_loss, run_frames = 0, time.time(), 0.0, 0
    best_valid = math.inf
    for batch in train_dl:
        if step == a.warmup_simple_steps and a.warmup_simple_steps > 0:
            set_trainable(False)
            log.info("ısınma bitti: tüm model eğitiliyor")
        T.set_batch_count(model, batch_count_offset + step)
        if scratch:
            params.batch_idx_train = step
        with torch.autocast(device_type=device.type, dtype=amp_dtype, enabled=use_amp):
            loss, info = loss_fn(params, model, sp, batch, True)
        scaler.scale(loss).backward()
        scheduler.step_batch(step)
        scaler.step(optimizer)
        scaler.update()
        optimizer.zero_grad(set_to_none=True)
        step += 1
        run_loss += info["loss"]
        run_frames += info["frames"]
        if not math.isfinite(info["loss"]):
            raise RuntimeError(f"kayıp sonlu değil (adım {step})")
        if step % 50 == 0 or step <= 5:
            log.info("adım %d  kayıp/kare %.4f  lr %.2e  %.1f adım/sn", step, run_loss / max(run_frames, 1),
                     scheduler.get_last_lr()[0], step / (time.time() - t0))
            run_loss, run_frames = 0.0, 0
        if valid_dl is not None and step % a.valid_every == 0:
            v = evaluate(params, model, sp, valid_dl, loss_fn)
            log.info("adım %d  DOĞRULAMA kayıp/kare %.4f%s", step, v, "  (en iyi)" if v < best_valid else "")
            if v < best_valid:
                best_valid = v
                torch.save({"model": model.state_dict(), "step": step, "valid": v, "bpe_model": a.bpe_model},
                           exp / "best.pt")
        if step % a.save_every == 0 or step == a.num_steps:
            torch.save({"model": model.state_dict(), "step": step, "bpe_model": a.bpe_model}, exp / f"step-{step}.pt")
            olds = sorted(exp.glob("step-*.pt"), key=lambda p: int(p.stem.split("-")[1]))[:-a.keep_last]
            for o in olds:
                o.unlink()
        if step >= a.num_steps:
            break

    # Son checkpoint'lerin ortalaması (icefall'da olduğu gibi genelde tek checkpoint'ten iyi)
    ckpts = sorted(exp.glob("step-*.pt"), key=lambda p: int(p.stem.split("-")[1]))
    if len(ckpts) > 1:
        avg = None
        for c in ckpts:
            sd = torch.load(c, map_location="cpu")["model"]
            if avg is None:
                avg = {k: v.clone().double() if v.is_floating_point() else v.clone() for k, v in sd.items()}
            else:
                for k, v in sd.items():
                    if v.is_floating_point():
                        avg[k] += v.double()
        avg = {k: (v / len(ckpts)).to(torch.float32) if v.is_floating_point() else v for k, v in avg.items()}
        torch.save({"model": avg, "averaged": [c.name for c in ckpts], "bpe_model": a.bpe_model}, exp / "averaged.pt")
        log.info("ortalama: %s -> averaged.pt", [c.name for c in ckpts])
    log.info("bitti: %d adım", step)
    return 0


if __name__ == "__main__":
    sys.exit(main())
