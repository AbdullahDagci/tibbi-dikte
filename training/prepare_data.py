"""Veri hazırlama: kaynakları indir/oku -> metni normalize et -> lhotse CutSet -> 80-boyutlu fbank.

Kaynaklar (alt komut):
  mediaspeech   OpenSLR 108 Türkçe (10 sa, CC BY 4.0)               — HF emre/Open_SLR108_Turkish_10_hours
  medv3         turkmedstt sentetik tıbbi (~6-7 sa, CC BY 4.0)       — HF turkmedstt/medv3-turkish-medical-asr
  fleurs        FLEURS tr_tr train/dev/test (CC BY 4.0)               — HF google/fleurs (test yalnızca değerlendirme)
  issai         ISSAI Turkish Speech Corpus (218 sa)                  — HF issai/Turkish_Speech_Corpus (21 GB tar)
  commonvoice   Common Voice TR (CC0) — Mozilla Data Collective'den elle indirilen klasör (--src)
  dir           wav/flac + aynı adlı .txt klasörü (sentetik radyoloji, kendi kayıtlarınız) (--src, --name)
  testset       tools/record_testset.py çıktısı (NN_konuşmacı.wav + sentences.txt)  (--src, --sentences, --name)
  fbank         tüm manifestler için öznitelik çıkarımı

Çıktı: data/manifests/<ad>_<bölüm>.jsonl.gz , data/fbank/<ad>_<bölüm>.jsonl.gz (+ lilcom öznitelikleri)
Örnek:
  python prepare_data.py medv3 && python prepare_data.py mediaspeech && python prepare_data.py fleurs
  python prepare_data.py issai          # sunucuda (21 GB)
  python prepare_data.py fbank --jobs 16
"""
from __future__ import annotations

import os as _os
import sys as _sys
if _sys.platform == "win32" and not _sys.flags.utf8_mode:  # lhotse dosyaları varsayılan kodlamayla (cp1254) yazar
    import subprocess as _sp
    _sys.exit(_sp.call([_sys.executable, "-X", "utf8", *_sys.argv]))


import argparse
import csv
import io
import re
import sys
import tarfile
import zipfile
from pathlib import Path

import sentencepiece as spm
import soundfile as sf
from lhotse import CutSet, Fbank, FbankConfig, LilcomChunkyWriter, Recording, RecordingSet, SupervisionSegment, \
    SupervisionSet

from textnorm import looks_uncased, normalize

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RAW = DATA / "raw"
MAN = DATA / "manifests"
BPE = HERE.parent / "models" / "tibbi-tr-v2" / "bpe.model"
AUDIO_EXT = {".wav", ".flac", ".mp3", ".ogg", ".opus", ".m4a"}


# ------------------------------------------------------------------ ortak
def build_cuts(items: list[tuple[str, Path, str]], name: str, split: str, *, min_dur=0.5, max_dur=20.0,
               max_unk=0.02) -> CutSet:
    """items: (id, ses yolu, ham metin). Metni normalize eder, süre/BPE filtreleri uygular, manifest yazar."""
    sp = spm.SentencePieceProcessor(model_file=str(BPE))
    unk = sp.unk_id()
    uncased = looks_uncased([t for _, _, t in items])
    recs, sups, dropped = [], [], {"süre": 0, "boş": 0, "unk": 0, "okunamadı": 0}
    for uid, path, raw in items:
        text = normalize(raw, restore_case=uncased)
        if not text:
            dropped["boş"] += 1
            continue
        ids = sp.encode(text)
        if ids and sum(i == unk for i in ids) / len(ids) > max_unk:
            dropped["unk"] += 1
            continue
        try:
            rec = Recording.from_file(path, recording_id=f"{name}-{uid}")
        except Exception:
            dropped["okunamadı"] += 1
            continue
        if not (min_dur <= rec.duration <= max_dur):
            dropped["süre"] += 1
            continue
        recs.append(rec)
        sups.append(SupervisionSegment(id=rec.id, recording_id=rec.id, start=0, duration=rec.duration,
                                       channel=0, text=text, language="tr"))
    cuts = CutSet.from_manifests(recordings=RecordingSet.from_recordings(recs),
                                 supervisions=SupervisionSet.from_segments(sups))
    if any(r.sampling_rate != 16000 for r in recs):
        cuts = cuts.resample(16000)
    MAN.mkdir(parents=True, exist_ok=True)
    out = MAN / f"{name}_{split}.jsonl.gz"
    cuts.to_file(out)
    hours = sum(r.duration for r in recs) / 3600
    print(f"{out.name}: {len(recs)} kesit, {hours:.1f} sa, büyük/küçük harf onarımı={uncased}, atılan={dropped}")
    return cuts


def hf_download(repo: str, patterns: list[str]) -> Path:
    from huggingface_hub import snapshot_download
    d = RAW / repo.replace("/", "__")
    snapshot_download(repo, repo_type="dataset", local_dir=d, allow_patterns=patterns)
    return d


def write_audio_bytes(data: bytes, out: Path) -> Path:
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        audio, sr = sf.read(io.BytesIO(data))
        sf.write(out, audio, sr)
    return out


# ------------------------------------------------------------------ kaynaklar
def prep_medv3(_a) -> None:
    import pyarrow.parquet as pq
    d = hf_download("turkmedstt/medv3-turkish-medical-asr", ["data/*.parquet", "*.csv", "README.md"])
    items = []
    for f in sorted((d / "data").glob("*.parquet")):
        t = pq.read_table(f)
        cols = t.column_names
        text_col = next(c for c in ("text", "transcription", "sentence") if c in cols)
        for i, row in enumerate(t.to_pylist()):
            uid = str(row.get("id") or f"{f.stem}-{i}")
            uid = re.sub(r"[^\w\-]", "_", uid)
            audio = row["audio"]
            path = write_audio_bytes(audio["bytes"], d / "wav" / f"{uid}.wav")
            items.append((uid, path, row[text_col]))
    build_cuts(items, "medv3", "train")


def prep_mediaspeech(_a) -> None:
    d = hf_download("emre/Open_SLR108_Turkish_10_hours", ["TR.zip"])
    out = d / "TR"
    if not out.exists():
        with zipfile.ZipFile(d / "TR.zip") as z:
            z.extractall(d)
    items = []
    for audio in sorted(p for p in d.rglob("*") if p.suffix.lower() in AUDIO_EXT):
        txt = audio.with_suffix(".txt")
        if txt.exists():
            items.append((audio.stem, audio, txt.read_text(encoding="utf-8").strip()))
    build_cuts(items, "mediaspeech", "train")


def prep_fleurs(_a) -> None:
    d = hf_download("google/fleurs", ["data/tr_tr/*.tsv", "data/tr_tr/audio/*.tar.gz"])
    base = d / "data" / "tr_tr"
    for split, tsv in (("train", "train.tsv"), ("dev", "dev.tsv"), ("test", "test.tsv")):
        wav_dir = base / "audio" / split
        if not wav_dir.exists():
            with tarfile.open(base / "audio" / f"{split}.tar.gz") as t:
                t.extractall(base / "audio", filter="data")
        files = {p.name: p for p in wav_dir.rglob("*.wav")}
        items = []
        with open(base / tsv, encoding="utf-8") as f:
            for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                # FLEURS tsv: id, dosya, ham metin, normalize metin, ...
                if len(row) > 2 and row[1] in files:
                    items.append((Path(row[1]).stem, files[row[1]], row[2]))
        build_cuts(items, "fleurs", split)


def prep_issai(_a) -> None:
    d = hf_download("issai/Turkish_Speech_Corpus", ["ISSAI_TSC_218.tar.gz", "README.md"])
    root = d / "ISSAI_TSC_218"
    if not root.exists():
        with tarfile.open(d / "ISSAI_TSC_218.tar.gz") as t:
            t.extractall(d, filter="data")
    for split_dir in sorted(p for p in d.iterdir() if p.is_dir() and p.name.startswith("ISSAI")):
        for sub in sorted(p for p in split_dir.iterdir() if p.is_dir()):
            items = collect_dir(sub)
            if items:
                build_cuts(items, "issai", sub.name.lower())


def collect_dir(src: Path) -> list[tuple[str, Path, str]]:
    items = []
    for audio in sorted(p for p in src.rglob("*") if p.suffix.lower() in AUDIO_EXT):
        txt = audio.with_suffix(".txt")
        if txt.exists():
            items.append((audio.stem, audio, txt.read_text(encoding="utf-8").strip()))
    return items


def prep_commonvoice(a) -> None:
    src = Path(a.src)  # cv-corpus-XX/tr
    for split in ("train", "dev", "test"):
        tsv = src / f"{split}.tsv"
        if not tsv.exists():
            continue
        items = []
        with open(tsv, encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                items.append((Path(row["path"]).stem, src / "clips" / row["path"], row["sentence"]))
        build_cuts(items, "commonvoice", split)


def prep_dir(a) -> None:
    build_cuts(collect_dir(Path(a.src)), a.name, a.split)


def prep_testset(a) -> None:
    lines = [l.strip() for l in Path(a.sentences).read_text(encoding="utf-8").splitlines() if l.strip()]
    items = [(w.stem, w, lines[int(w.name[:2])]) for w in sorted(Path(a.src).glob("*.wav"))]
    build_cuts(items, a.name, "test")


def prep_fbank(a) -> None:
    out_dir = DATA / "fbank"
    out_dir.mkdir(parents=True, exist_ok=True)
    extractor = Fbank(FbankConfig(num_mel_bins=80, device="cuda" if a.cuda else "cpu"))
    for man in sorted(MAN.glob("*.jsonl.gz")):
        target = out_dir / man.name
        if target.exists():
            continue
        cuts = CutSet.from_file(man)
        if "_train" in man.name and a.speed_perturb:
            cuts = cuts + cuts.perturb_speed(0.9) + cuts.perturb_speed(1.1)
        cuts = cuts.compute_and_store_features(extractor=extractor, storage_path=out_dir / man.name.replace(".jsonl.gz", ""),
                                               num_jobs=a.jobs, storage_type=LilcomChunkyWriter)
        cuts.to_file(target)
        print(f"fbank: {target.name} ({len(cuts)} kesit)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("medv3", prep_medv3), ("mediaspeech", prep_mediaspeech), ("fleurs", prep_fleurs),
                     ("issai", prep_issai)):
        sub.add_parser(name).set_defaults(fn=fn)
    p = sub.add_parser("commonvoice"); p.add_argument("--src", required=True); p.set_defaults(fn=prep_commonvoice)
    p = sub.add_parser("dir"); p.add_argument("--src", required=True); p.add_argument("--name", required=True)
    p.add_argument("--split", default="train"); p.set_defaults(fn=prep_dir)
    p = sub.add_parser("testset"); p.add_argument("--src", required=True); p.add_argument("--sentences", required=True)
    p.add_argument("--name", default="radiology_real"); p.set_defaults(fn=prep_testset)
    p = sub.add_parser("fbank"); p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--cuda", action="store_true"); p.add_argument("--speed-perturb", action="store_true")
    p.set_defaults(fn=prep_fbank)
    a = ap.parse_args()
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
