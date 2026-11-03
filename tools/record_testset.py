"""Gerçek test seti kaydı: cümleleri sırayla gösterir, mikrofondan 16 kHz mono wav kaydeder.

Kullanım:
    python tools/record_testset.py --speaker drayse
    python tools/record_testset.py --speaker drayse --sentences data/radiology_test/sentences.txt
Tuşlar: Enter = kaydı başlat/durdur · t = son kaydı tekrarla · a = cümleyi atla · q = çık
Kayıtlar: data/radiology_test/audio/NN_<konuşmacı>.wav  (NN = cümle satır no, 0'dan)
Zaten kaydedilmiş cümleler atlanır, yarıda bırakılıp devam edilebilir.

Not: Konuşmacılardan KVKK kapsamında açık rıza alın; cümleler hasta bilgisi içermez.
"""
import argparse
import queue
import sys
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

ROOT = Path(__file__).resolve().parent.parent
SR = 16000


def record() -> np.ndarray:
    q: "queue.Queue[np.ndarray]" = queue.Queue()
    with sd.InputStream(samplerate=SR, channels=1, dtype="int16", callback=lambda d, *_: q.put(d.copy())):
        input("  ● Kaydediliyor… bitince Enter ")
    chunks = []
    while not q.empty():
        chunks.append(q.get())
    return np.concatenate(chunks)[:, 0] if chunks else np.zeros(0, dtype=np.int16)


def save(path: Path, pcm: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speaker", required=True, help="kısa ad, ör. drayse (dosya adına girer)")
    ap.add_argument("--sentences", default=str(ROOT / "data" / "radiology_test" / "sentences.txt"))
    ap.add_argument("--out", default=str(ROOT / "data" / "radiology_test" / "audio"))
    a = ap.parse_args()
    lines = [l.strip() for l in Path(a.sentences).read_text(encoding="utf-8").splitlines() if l.strip()]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"{len(lines)} cümle. Doğal hızınızda, rapor dikte eder gibi okuyun.\n")
    for i, text in enumerate(lines):
        path = out / f"{i:02d}_{a.speaker}.wav"
        if path.exists():
            continue
        while True:
            print(f"[{i + 1}/{len(lines)}] {text}")
            cmd = input("  Enter = başla, a = atla, q = çık: ").strip().lower()
            if cmd == "q":
                return 0
            if cmd == "a":
                break
            pcm = record()
            dur = len(pcm) / SR
            peak = int(np.abs(pcm).max()) if len(pcm) else 0
            warn = "  ⚠ çok kısık" if peak < 2000 else ("  ⚠ patlama var" if peak > 32000 else "")
            print(f"  {dur:.1f} sn, tepe {peak}{warn}")
            if input("  Kaydet? (Enter = evet, t = tekrar): ").strip().lower() == "t":
                continue
            save(path, pcm)
            break
    print("Bitti.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
