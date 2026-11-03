"""YALNIZCA DEĞERLENDİRME (eğitimde kullanmayın — TTS hizmet şartları): tests/sentences_tr.txt cümlelerinden 16 kHz wav üretir (edge-tts)."""
import argparse, asyncio, sys, io, wave
from pathlib import Path
import edge_tts, miniaudio
here = Path(__file__).parent
ap = argparse.ArgumentParser(); ap.add_argument("--sentences", default=str(here/"sentences_tr.txt")); ap.add_argument("--out", default=str(here/"audio"))
A = ap.parse_args()
async def main():
    lines = [l.strip() for l in Path(A.sentences).read_text(encoding="utf-8").splitlines() if l.strip()]
    Path(A.out).mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(lines):
        for voice in ["tr-TR-EmelNeural", "tr-TR-AhmetNeural"]:
            out = Path(A.out)/f"{i:02d}_{voice.split('-')[2][:4]}.wav"
            if out.exists(): continue
            buf = b""
            async for c in edge_tts.Communicate(text, voice).stream():
                if c["type"] == "audio": buf += c["data"]
            dec = miniaudio.decode(buf, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=16000)
            with wave.open(str(out), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(dec.samples.tobytes())
asyncio.run(main())
