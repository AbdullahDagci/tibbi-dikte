"""Doğruluk değerlendirmesi: ham model / hotword / hotword + sonişleme için WER ve terim isabeti.

Kullanım: python tests/eval_wer.py [--model models/tibbi-tr-v2] [--verbose]
Ses: tests/audio/NN_*.wav  — referans: tests/sentences_tr.txt (NN. satır)
Kendi kayıtlarınızı aynı adlandırmayla ekleyebilirsiniz.
"""
import argparse
import re
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engines.base import ModelInfo  # noqa: E402
from app.engines.registry import discover_models, load_engine  # noqa: E402
from app.medical.postprocess import MedicalPostProcessor, read_lexicon, tr_lower  # noqa: E402
from app.dictation import write_hotwords  # noqa: E402

LEX = ROOT / "app" / "medical" / "lexicon_tr.txt"
RAD = ROOT / "app" / "medical" / "radiology_terms_tr.txt"
RADF = ROOT / "app" / "medical" / "radiology_fuzzy_tr.txt"
RADK = ROOT / "app" / "medical" / "radiology_known_tr.txt"
CORR = ROOT / "app" / "medical" / "corrections_tr.tsv"


def norm(s: str) -> list[str]:
    s = tr_lower(s).replace("'", " ").replace("’", " ")
    return re.findall(r"[\wçğıöşü%]+", s)


def wer(ref: list[str], hyp: list[str]) -> float:
    d = np.zeros((len(ref) + 1, len(hyp) + 1), dtype=int)
    d[:, 0] = range(len(ref) + 1)
    d[0, :] = range(len(hyp) + 1)
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]))
    return d[-1, -1] / max(1, len(ref))


def load_wav(p: Path) -> np.ndarray:
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--score", type=float, default=2.0)
    ap.add_argument("--sentences", default=str(ROOT / "tests" / "sentences_tr.txt"))
    ap.add_argument("--audio", default=str(ROOT / "tests" / "audio"))
    ap.add_argument("--no-radiology", action="store_true", help="radyoloji sözlüğünü kullanma (karşılaştırma için)")
    a = ap.parse_args()
    model = ModelInfo.from_dir(Path(a.model)) if a.model else discover_models()[0]
    refs = [l.strip() for l in Path(a.sentences).read_text(encoding="utf-8").splitlines() if l.strip()]
    files = sorted(Path(a.audio).glob("*.wav"))
    lexs = [LEX] if a.no_radiology else [LEX, RAD]
    fuzz = [LEX] if a.no_radiology else [LEX, RADF]
    prot = [] if a.no_radiology else [RADK]
    terms = {tr_lower(t) for t in read_lexicon(LEX) + read_lexicon(RAD) if len(t) >= 6}  # ölçüt sabit

    hw = write_hotwords(lexs, ROOT / "tests" / "_hotwords.txt")
    raw = load_engine(model)
    biased = load_engine(model, hotwords_file=str(hw), hotwords_score=a.score)
    post = MedicalPostProcessor.from_files(lexs, [CORR], fuzzy_files=fuzz, protected_files=prot, general_files=[LEX.parent / 'general_tr_words.txt'])
    post_noitn = MedicalPostProcessor.from_files(lexs, [CORR], fuzzy_files=fuzz, protected_files=prot, general_files=[LEX.parent / 'general_tr_words.txt'], use_itn=False)

    # sonişleme = hotword'süz ham çıktı + sonişleme (model.json "hotwords": false olan modellerde uygulamanın yaptığı)
    systems = {"ham": [], "hotword": [], "hotword+sonişleme": [], "sonişleme": []}
    term_hits = {k: [0, 0] for k in systems}
    for f in files:
        ref = refs[int(f.name[:2])]
        audio = load_wav(f)
        r = raw.transcribe(audio)
        b = biased.transcribe(audio)
        outs = {"ham": r, "hotword": b, "hotword+sonişleme": post(b), "sonişleme": post(r)}
        # WER: ITN rakamları referansla karşılaştırılamaz, bu yüzden yazım karşılaştırması için ITN'siz sonişleme
        cmp = {"ham": r, "hotword": b, "hotword+sonişleme": post_noitn(b), "sonişleme": post_noitn(r)}
        ref_toks = norm(ref)
        ref_terms = [t for t in ref_toks if any(t.startswith(x) for x in terms)]
        for k in systems:
            hyp = norm(cmp[k])
            systems[k].append(wer(ref_toks, hyp))
            term_hits[k][0] += sum(1 for t in ref_terms if t in hyp)
            term_hits[k][1] += len(ref_terms)
        if a.verbose:
            print(f"\n[{f.name}] REF: {ref}")
            for k, v in outs.items():
                print(f"  {k:18s}: {v}")
    app_mode = "hotword+sonişleme" if model.hotwords else "sonişleme"
    print("\nSistem               WER     Tıbbi terim isabeti")
    for k, v in systems.items():
        h, n = term_hits[k]
        mark = "   <- uygulamada" if k == app_mode else ""
        print(f"  {k:18s} {100*np.mean(v):5.1f}%   {h}/{n} ({100*h/max(1,n):.0f}%){mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
