"""Radyoloji cümlelerini TTS ile seslendirip eğitim klasörü (wav + txt) üretir.

LİSANS UYARISI: TTS çıktısıyla model eğitmek, sağlayıcının kullanım şartlarına bağlıdır. Açık kaynak tek Türkçe
Piper sesi (dfki) CC BY-NC-SA'dır -> ticari üründe KULLANILAMAZ. Ticari bir sağlayıcı (ör. Google Cloud TTS
Chirp3-HD — turkmedstt/medv3 bununla üretildi) kullanmadan önce şartlarının eğitim amaçlı kullanıma izin
verdiğini yazılı olarak doğrulayın. Gönderilen metin sentetik şablon cümleleridir; hasta verisi göndermeyin.

Arka uçlar:
  chatterbox  Chatterbox Multilingual (MIT), yerel GPU, internetsiz. Her klip --ref-dir'deki gerçek bir
              konuşmacının sesinden klonlanır (konuşmacı çeşitliliği). Ayrı ortamda çalışır: chatterbox-tts,
              "setuptools<81", sherpa-onnx. --check-model verilirse her klip mevcut modelle de denetlenir.
  google      google-cloud-texttospeech (GOOGLE_APPLICATION_CREDENTIALS gerekli); birden çok ses, hız çeşitlemesi
  command     herhangi bir komut satırı TTS:  --cmd "mytts --text {text} --out {out}"

Kaçan / erken kesilen / anlamsız klipler (synthcheck.accept) farklı ses ve tohumla yeniden denenir, olmazsa
_rejected*.tsv'ye yazılıp atlanır. Yarıda kesilen iş aynı komutla kaldığı yerden sürer; --shard i/n ile aynı
GPU'da paralel süreçler çalıştırılabilir.

  python tts_synthesize.py --sentences data/radsynth_sentences.txt --out data/raw/radsynth --backend chatterbox \
      --ref-dir data/voice_refs --check-model ../models/tibbi-tr-v2 --shard 0/2
  python tts_synthesize.py --sentences data/radsynth_sentences.txt --out data/raw/radsynth --backend google \
      --voices tr-TR-Chirp3-HD-Aoede,tr-TR-Chirp3-HD-Charon,tr-TR-Chirp3-HD-Kore,tr-TR-Chirp3-HD-Orus
  python prepare_data.py dir --src data/raw/radsynth --name radsynth
"""
from __future__ import annotations

import argparse
import os
import random
import shlex
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Callable

from synthcheck import accept, shard

EXIT_RESTART = 75  # bellek sınırıyla durdu: dıştaki döngü süreci yeniden başlatsın
ROOT = Path(__file__).resolve().parent.parent
SR = 16000


def synth_google(text: str, voice: str, rate: float, out: Path) -> None:
    from google.cloud import texttospeech as tts
    client = synth_google.client = getattr(synth_google, "client", None) or tts.TextToSpeechClient()
    resp = client.synthesize_speech(
        input=tts.SynthesisInput(text=text),
        voice=tts.VoiceSelectionParams(language_code="tr-TR", name=voice),
        audio_config=tts.AudioConfig(audio_encoding=tts.AudioEncoding.LINEAR16, sample_rate_hertz=16000,
                                     speaking_rate=rate))
    out.write_bytes(resp.audio_content)  # LINEAR16 yanıtı WAV başlığıyla gelir


def synth_command(text: str, voice: str, rate: float, out: Path, cmd: str) -> None:
    args = [a.format(text=text, out=str(out), voice=voice, rate=rate) for a in shlex.split(cmd)]
    subprocess.run(args, check=True)


# ------------------------------------------------------------------ chatterbox (yerel, kapılı)
def write_wav(path: Path, audio) -> None:
    """float [-1, 1] -> 16 kHz PCM16; önce geçici dosya: yarıda kesilen yazım eksik klip bırakmasın."""
    import numpy as np
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    tmp = path.with_suffix(".wav.part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def synthesize_gated(items: list[tuple[int, str]], out: Path, synth: Callable[[str, str, int], object],
                     refs: list[str], *, check: Callable[[object], str] | None = None, retries: int = 2,
                     per_sentence: int = 1, tag: str = "", log_every: int = 0,
                     stop: Callable[[], str | None] | None = None) -> dict:
    """items: (cümle indeksi, metin). synth(metin, referans ses, tohum) -> 16 kHz float dizi.
    check(ses) -> mevcut modelin transkripti (verilmezse yalnızca süre denetlenir).
    stop() bir neden döndürürse (ör. bellek sınırı) döngü cümle arasında temiz biter; st["stopped"] = neden."""
    out.mkdir(parents=True, exist_ok=True)
    rej_files = list(out.glob("_rejected*.tsv"))
    rejected = {ln.split("\t")[0] for f in rej_files for ln in f.read_text(encoding="utf-8").splitlines() if ln}
    rej_log = out / f"_rejected{tag}.tsv"
    meta_log = out / f"_meta{tag}.tsv"
    st = {"ok": 0, "rejected": 0, "retried": 0, "audio_sec": 0.0, "stopped": None}
    t0 = time.time()
    for n, (i, text) in enumerate(items, 1):
        if stop is not None and (why := stop()):
            st["stopped"] = why
            break
        for k in range(per_sentence):
            key = f"{i:06d}_{k}"
            wav = out / f"{key}.wav"
            if wav.exists() or key in rejected:
                continue
            for attempt in range(retries + 1):
                seed = (i * 1000 + k * 10 + attempt) % 2**31
                ref = random.Random(seed).choice(refs)
                audio = synth(text, ref, seed)
                dur = len(audio) / SR
                ok, why = accept(text, dur)
                if ok and check is not None:
                    ok, why = accept(text, dur, check(audio))
                if ok:
                    break
                st["retried"] += attempt < retries
            if ok:
                wav.with_suffix(".txt").write_text(text, encoding="utf-8")
                write_wav(wav, audio)
                with meta_log.open("a", encoding="utf-8") as f:
                    f.write(f"{key}\t{Path(ref).name}\t{seed}\t{dur:.2f}\n")
                st["ok"] += 1
                st["audio_sec"] += dur
            else:
                with rej_log.open("a", encoding="utf-8") as f:
                    f.write(f"{key}\t{why}\t{text}\n")
                st["rejected"] += 1
        if log_every and n % log_every == 0:
            el = time.time() - t0
            print(f"{n}/{len(items)} | kabul {st['ok']} ret {st['rejected']} yeniden {st['retried']} | "
                  f"{st['audio_sec'] / 3600:.2f} sa ses | gerçek zaman oranı {el / max(st['audio_sec'], 1e-3):.2f} | "
                  f"kalan ~{el / n * (len(items) - n) / 3600:.1f} sa | bellek {rss_gb():.1f} GB", flush=True)
    return st


def rss_gb() -> float:
    """Sürecin fiziksel bellek kullanımı (Linux /proc; başka yerde 0)."""
    try:
        for ln in Path("/proc/self/status").read_text().splitlines():
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1]) / 2**20
    except OSError:
        pass
    return 0.0


def make_chatterbox(device: str = "cuda") -> Callable[[str, str, int], object]:
    import torch
    import torchaudio
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    m = ChatterboxMultilingualTTS.from_pretrained(device=device)

    def synth(text: str, ref: str, seed: int):
        torch.manual_seed(seed)
        r = random.Random(seed)
        wav = m.generate(text, language_id="tr", audio_prompt_path=ref,
                         exaggeration=r.choice([0.4, 0.5, 0.6]), cfg_weight=r.choice([0.4, 0.5]))
        return torchaudio.functional.resample(wav, m.sr, SR).squeeze(0).cpu().numpy()
    return synth


def make_checker(model_dir: str) -> Callable[[object], str]:
    sys.path.insert(0, str(ROOT))
    from app.engines.base import ModelInfo
    from app.engines.registry import load_engine
    eng = load_engine(ModelInfo.from_dir(Path(model_dir)))
    return lambda audio: eng.transcribe(audio, SR)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sentences", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", choices=["chatterbox", "google", "command"], required=True)
    ap.add_argument("--ref-dir", help="chatterbox: ses klonlama referansları (wav, 6-12 sn, farklı konuşmacılar)")
    ap.add_argument("--check-model", help="chatterbox: klipleri bu modelle denetle (ör. ../models/tibbi-tr-v2)")
    ap.add_argument("--shard", default="", help="chatterbox: i/n — paralel süreçlerden i'ncisinin payı")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--max-rss-gb", type=float, default=0,
                    help="chatterbox: bellek bunu aşınca çık (kod 75); dıştaki döngü yeniden başlatır, iş kaldığı yerden sürer")
    ap.add_argument("--voices", default="", help="virgülle ayrılmış ses adları")
    ap.add_argument("--cmd", help="command arka ucu için şablon ({text} {out} {voice} {rate})")
    ap.add_argument("--per-sentence", type=int, default=1, help="her cümle için farklı ses/hızla kaç kayıt")
    ap.add_argument("--rates", default="0.9,1.0,1.1")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    sents = [l.strip() for l in Path(a.sentences).read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.limit:
        sents = sents[:a.limit]
    voices = [v for v in a.voices.split(",") if v] or ["default"]
    rates = [float(r) for r in a.rates.split(",")]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.backend == "chatterbox":
        refs = sorted(str(p) for p in Path(a.ref_dir).glob("*.wav"))
        if not refs:
            ap.error(f"--ref-dir içinde wav yok: {a.ref_dir}")
        check = make_checker(a.check_model) if a.check_model else None
        stop = (lambda: f"bellek {rss_gb():.1f} GB > {a.max_rss_gb} GB" if rss_gb() > a.max_rss_gb else None) \
            if a.max_rss_gb else None
        st = synthesize_gated(shard(sents, a.shard), out, make_chatterbox(), refs, check=check, retries=a.retries,
                              per_sentence=a.per_sentence, tag=a.shard.replace("/", "of"), log_every=25, stop=stop)
        if st["stopped"]:
            print(f"durdu ({st['stopped']}): {st['ok']} kabul — yeniden başlatılmalı", flush=True)
            return EXIT_RESTART
        print(f"bitti: {st['ok']} kabul, {st['rejected']} ret, {st['audio_sec'] / 3600:.2f} sa ses -> {out}")
        return 0
    rnd = random.Random(0)
    done = 0
    for i, text in enumerate(sents):
        for k in range(a.per_sentence):
            voice, rate = rnd.choice(voices), rnd.choice(rates)
            wav = out / f"{i:06d}_{k}.wav"
            if wav.exists():
                continue
            if a.backend == "google":
                synth_google(text, voice, rate, wav)
            else:
                synth_command(text, voice, rate, wav, a.cmd)
            wav.with_suffix(".txt").write_text(text, encoding="utf-8")
            done += 1
        if i % 200 == 0:
            print(f"{i}/{len(sents)}", flush=True)
    print(f"{done} yeni kayıt -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
