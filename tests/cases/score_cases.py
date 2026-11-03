"""tests/cases/*.hyp.txt (gerçek model çıktısı) -> sonişleme -> *.ref.txt ile puan. Önce/sonra karşılaştırma için."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.dictation import (BUILTIN_CORRECTIONS, BUILTIN_LEXICON, RADIOLOGY_FUZZY, RADIOLOGY_KNOWN,  # noqa: E402
                           RADIOLOGY_LEXICON)
from app.medical.postprocess import MedicalPostProcessor, read_lexicon, tr_lower  # noqa: E402
from app.scoring import score  # noqa: E402

pp = MedicalPostProcessor.from_files([BUILTIN_LEXICON, RADIOLOGY_LEXICON], [BUILTIN_CORRECTIONS],
                                     fuzzy_files=[BUILTIN_LEXICON, RADIOLOGY_FUZZY], protected_files=[RADIOLOGY_KNOWN])
terms = {tr_lower(t) for f in (BUILTIN_LEXICON, RADIOLOGY_LEXICON) for t in read_lexicon(f) if " " not in t}
for hyp_f in sorted(Path(__file__).parent.glob("*.hyp.txt")):
    hyp = hyp_f.read_text(encoding="utf-8")
    ref = hyp_f.with_name(hyp_f.name.replace(".hyp.", ".ref.")).read_text(encoding="utf-8")
    out = pp(hyp)
    a, b = score(ref, hyp, terms), score(ref, out, terms)
    print(f"{hyp_f.stem}: ham doğruluk %{a.accuracy*100:.1f} (terim %{(a.term_accuracy or 0)*100:.0f})  ->  "
          f"sonişleme %{b.accuracy*100:.1f} (terim %{(b.term_accuracy or 0)*100:.0f})")
    if "-v" in sys.argv:
        print("   kalan hatalar:", [(x.ref, x.hyp) for x in b.alignment if x.op != "ok"])
        print("   ÇIKTI:", out)
