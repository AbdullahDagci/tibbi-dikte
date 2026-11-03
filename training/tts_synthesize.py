"""Radyoloji cümlelerini TTS ile seslendirip eğitim klasörü (wav + txt) üretir.

LİSANS UYARISI: TTS çıktısıyla model eğitmek, sağlayıcının kullanım şartlarına bağlıdır. Açık kaynak tek Türkçe
Piper sesi (dfki) CC BY-NC-SA'dır -> ticari üründe KULLANILAMAZ. Ticari bir sağlayıcı (ör. Google Cloud TTS
Chirp3-HD — turkmedstt/medv3 bununla üretildi) kullanmadan önce şartlarının eğitim amaçlı kullanıma izin
verdiğini yazılı olarak doğrulayın. Gönderilen metin sentetik şablon cümleleridir; hasta verisi göndermeyin.

Arka uçlar:
  google   google-cloud-texttospeech (GOOGLE_APPLICATION_CREDENTIALS gerekli); birden çok ses, hız çeşitlemesi
  command  herhangi bir komut satırı TTS:  --cmd "mytts --text {text} --out {out}"

  python tts_synthesize.py --sentences data/radsynth_sentences.txt --out data/raw/radsynth --backend google \
      --voices tr-TR-Chirp3-HD-Aoede,tr-TR-Chirp3-HD-Charon,tr-TR-Chirp3-HD-Kore,tr-TR-Chirp3-HD-Orus
  python prepare_data.py dir --src data/raw/radsynth --name radsynth
"""
from __future__ import annotations

import argparse
import random
import shlex
import subprocess
import sys
from pathlib import Path


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sentences", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", choices=["google", "command"], required=True)
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
