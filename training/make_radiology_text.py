"""Sentetik radyoloji rapor cümleleri üretir (TTS ile seslendirilip eğitim verisi olacak).

Kaynak: data/radiology_templates/*.txt şablonları (biçim: o klasördeki FORMAT.md). Şablonlar sırayla, her turda
her birinden yeni bir cümle alınarak doldurulur; böylece değişkenliği az şablonlar tükenir, çok olanlar daha çok
cümle verir ama hiçbiri listeyi domine etmez. Klasör boşsa aşağıdaki yerleşik şablonlar kullanılır.
Sayılar YAZIYLA üretilir (model çıktı biçimi). Test cümlelerine (data/radiology_test) sayılar dışında çok benzeyen
bir cümle üreten şablon tümüyle elenir: değerlendirme ölçümü eğitim verisine sızmasın.

En iyi kaynak gerçek (anonimleştirilmiş) rapor metinleridir: varsa --reports ile verin, cümlelere bölünüp
şablon cümleleriyle karıştırılır.

  python make_radiology_text.py --n 16000 --out data/radsynth_sentences.txt [--reports raporlar.txt]
"""
from __future__ import annotations

import argparse
import difflib
import random
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from textnorm import _NUMBER_WORDS, int_to_words, normalize

HERE = Path(__file__).resolve().parent
VOCAB = HERE.parent / "data" / "radiology_vocab.tsv"
TEST = HERE.parent / "data" / "radiology_test" / "sentences.txt"
TEMPLATE_DIR = HERE.parent / "data" / "radiology_templates"
TERMS = HERE.parent / "app" / "medical" / "radiology_terms_tr.txt"

# ------------------------------------------------------------------ şablon dosyaları
_BRACE_RE = re.compile(r"\{([^{}]*)\}")
_SLOTS = {
    "mm": lambda r: str(r.choice(list(range(2, 30)) * 3 + list(range(30, 61)))),  # küçük ölçüler daha sık
    "cm": lambda r: (lambda a, b: f"{a},{b}" if b else str(a))(r.randint(1, 15), r.randint(0, 9)),
    "n": lambda r: str(r.randint(1, 12)),
}
_DIGIT_ORDINAL_RE = re.compile(r"\b\d+\.\s+[a-zçğıöşü]")


def expand(tpl: str, rng: random.Random) -> str:
    """{a|b|c} -> biri; {mm} {cm} {n} -> rastgele sayı (rakamla; normalize yazıya çevirir)."""
    def sub(m: re.Match) -> str:
        body = m.group(1)
        return _SLOTS[body](rng) if body in _SLOTS else rng.choice(body.split("|"))
    return _BRACE_RE.sub(sub, tpl)


def template_problems(tpl: str) -> list[str]:
    probs = []
    depth = 0
    for ch in tpl:
        depth += (ch == "{") - (ch == "}")
        if depth > 1:
            probs.append("iç içe süslü parantez")
            break
        if depth < 0:
            probs.append("fazladan '}'")
            break
    if depth > 0:
        probs.append("kapanmamış '{'")
    for body in _BRACE_RE.findall(tpl):
        if "|" not in body and body not in _SLOTS:
            probs.append(f"bilinmeyen yuva {{{body}}}")
    if not tpl.rstrip().endswith("."):
        probs.append("nokta ile bitmiyor")
    if _DIGIT_ORDINAL_RE.search(tpl):
        probs.append("rakamla sıra sayısı")
    return probs


def load_templates(folder: Path = TEMPLATE_DIR) -> tuple[list[str], list[str]]:
    """(geçerli şablonlar, sorun raporu)."""
    good, bad = [], []
    for f in sorted(folder.glob("*.txt")):
        for no, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            probs = template_problems(line)
            if probs:
                bad.append(f"{f.name}:{no}: {', '.join(probs)}: {line}")
            else:
                good.append(line)
    return good, bad


# ------------------------------------------------------------------ test seti sızıntısı
_IGNORE = _NUMBER_WORDS | {"virgül", "yüzde", "çarpı"}


@lru_cache(maxsize=None)
def _key(s: str) -> tuple[str, ...]:
    s = s.replace("İ", "i").replace("I", "ı").lower().replace("'", " ")
    return tuple(w for w in re.findall(r"[\wçğıöşüâîû]+", s) if w not in _IGNORE and not w.isdigit())


def near_test(sentence: str, tests, threshold: float = 0.8) -> bool:
    """Sayılar yok sayıldığında bir test cümlesine kelime dizisi olarak çok benziyor mu."""
    k = _key(sentence)
    for t in tests:
        tk = _key(t)
        if min(len(k), len(tk)) / max(len(k), len(tk), 1) < threshold:
            continue
        if difflib.SequenceMatcher(None, k, tk, autojunk=False).ratio() >= threshold:
            return True
    return False


def generate(templates: list[str], n: int, *, test_sentences=(), seed: int = 1) -> list[str]:
    """Şablonlardan en çok n benzersiz, normalize edilmiş cümle (turlar hâlinde, dengeli)."""
    rng = random.Random(seed)
    tests = tuple(test_sentences)
    seen: set[str] = set()
    by_t: dict[int, list[str]] = {i: [] for i in range(len(templates))}
    banned: set[int] = set()
    total = 0
    active = list(range(len(templates)))
    while active and total < n:
        still = []
        for i in active:
            if total >= n:
                break
            for _ in range(5):
                s = normalize(expand(templates[i], rng), restore_case=True)
                if s.lower() not in seen:
                    break
            else:
                continue  # tükendi
            if tests and near_test(s, tests):
                banned.add(i)
                total -= len(by_t[i])
                continue
            seen.add(s.lower())
            by_t[i].append(s)
            total += 1
            still.append(i)
        active = still
    out = [s for i, ss in by_t.items() if i not in banned for s in ss]
    rng.shuffle(out)
    return out


def term_coverage(sentences: list[str], terms: list[str], min_count: int = 3) -> tuple[int, int, list[str]]:
    """(en az min_count kez geçen terim sayısı, toplam terim, hiç geçmeyenler)."""
    c = Counter(w for s in sentences for w in _key(s))
    terms = [t.lower() for t in terms]
    return sum(c[t] >= min_count for t in terms), len(terms), [t for t in terms if c[t] == 0]

SIDE = ["sağ", "sol"]
BREAST_QUAD = ["üst dış kadranda", "üst iç kadranda", "alt dış kadranda", "alt iç kadranda", "retroareolar bölgede",
               "aksiller kuyrukta", "santral bölgede"]
CLOCK = [f"saat {int_to_words(h)} hizasında" for h in range(1, 13)]
DENSITY = ["yağlı", "dağınık fibroglandüler", "heterojen dens", "belirgin dens"]
BIRADS = ["bir", "iki", "üç", "dört a", "dört b", "dört c", "beş", "altı", "sıfır"]
SHAPE = ["oval", "yuvarlak", "lobüle", "düzensiz"]
MARGIN = ["düzgün sınırlı", "mikrolobüle konturlu", "belirsiz sınırlı", "spiküler konturlu", "kısmen silik konturlu"]
ECHO = ["hipoekoik", "izoekoik", "hiperekoik", "anekoik", "heterojen ekojenitede", "kompleks kistik-solid"]
ORGAN_ABD = ["karaciğer", "dalak", "pankreas", "sağ böbrek", "sol böbrek", "safra kesesi", "mesane", "prostat", "uterus"]
LIVER_SEG = [f"segment {w}" for w in ["bir", "iki", "üç", "dört a", "dört b", "beş", "altı", "yedi", "sekiz"]]
LUNG_LOBE = ["sağ akciğer üst lob", "sağ akciğer orta lob", "sağ akciğer alt lob", "sol akciğer üst lob",
             "sol akciğer alt lob", "lingula"]
LUNG_FIND = ["buzlu cam dansitesi", "konsolidasyon alanı", "nodüler dansite", "subplevral nodül", "atelektazi",
             "fibrotik bant", "bronşiektazi", "amfizematöz değişiklik"]
BRAIN = ["sağ frontal lobda", "sol frontal lobda", "sağ parietal lobda", "sol temporal lobda", "sol oksipital lobda",
         "periventriküler beyaz cevherde", "bazal ganglionlarda", "sağ serebellar hemisferde", "pons düzeyinde"]
MR_SIGNAL = ["T iki ağırlıklı serilerde hiperintens", "T bir ağırlıklı serilerde hipointens", "FLAIR serilerde hiperintens",
             "difüzyon kısıtlaması gösteren", "kontrast tutulumu göstermeyen", "periferik kontrast tutan"]
SPINE_LEVEL = [f"{a} {b} {c} {d}" for a, b, c, d in [("L", "dört", "L", "beş"), ("L", "beş", "S", "bir"),
               ("L", "üç", "L", "dört"), ("C", "beş", "C", "altı"), ("C", "altı", "C", "yedi")]]
DISC = ["diffüz bulging", "sol paramedian protrüzyon", "sağ paramedian protrüzyon", "santral ekstrüzyon",
        "sol foraminal protrüzyon"]
COMPARE = ["Önceki tetkik ile karşılaştırıldığında belirgin değişiklik izlenmedi.",
           "Önceki tetkike göre lezyon boyutlarında artış izlendi.", "Önceki tetkike göre lezyon boyutlarında azalma izlendi.",
           "Karşılaştırma yapılacak önceki tetkik mevcut değildir."]
CLOSING = ["Klinik ve laboratuvar bulguları ile birlikte değerlendirilmesi önerilir.",
           "Kısa dönem kontrol önerilir.", "Doku örneklemesi önerilir.", "Altı ay sonra kontrol önerilir.",
           "Malignite lehine bulgu saptanmamıştır.", "Patolojik bulgu saptanmamıştır."]


def mm() -> str:
    return int_to_words(random.choice(list(range(2, 30)) + list(range(30, 90, 5))))


def cm() -> str:
    a, b = random.randint(1, 15), random.randint(0, 9)
    return f"{int_to_words(a)} virgül {int_to_words(b)}" if b else int_to_words(a)


def templates() -> list:
    s, c = random.choice, None
    return [
        lambda: f"Her iki memede {s(DENSITY)} meme paterni izlendi.",
        lambda: f"{s(SIDE).capitalize()} meme {s(BREAST_QUAD)} {mm()} milimetre boyutlu {s(SHAPE)} {s(MARGIN)} kitle izlendi.",
        lambda: f"{s(SIDE).capitalize()} meme {s(CLOCK)} {mm()} milimetrelik {s(ECHO)} solid lezyon izlendi.",
        lambda: f"{s(SIDE).capitalize()} meme {s(BREAST_QUAD)} gruplaşmış mikrokalsifikasyonlar izlendi.",
        lambda: f"BI-RADS {s(BIRADS)} olarak değerlendirildi.",
        lambda: f"{s(SIDE).capitalize()} aksiller bölgede {s(['reaktif görünümlü', 'kortikal kalınlaşma gösteren', 'yağlı hilusu korunmuş'])} lenf nodları izlendi.",
        lambda: f"Bilateral memede benign görünümlü kalsifikasyonlar izlendi.",
        lambda: f"Meme parankiminde mimari distorsiyon izlenmedi.",
        lambda: f"{s(ORGAN_ABD).capitalize()} boyutları ve parankim ekojenitesi normaldir.",
        lambda: f"Karaciğer boyutları artmış, parankim ekojenitesi diffüz olarak artmış olup grade {s(['bir', 'iki', 'üç'])} hepatosteatoz ile uyumludur.",
        lambda: f"Karaciğer {s(LIVER_SEG)} düzeyinde {mm()} milimetre çaplı {s(ECHO)} lezyon izlendi.",
        lambda: f"Safra kesesi lümeninde {mm()} milimetre çaplı akustik gölge veren taş izlendi.",
        lambda: f"{s(SIDE).capitalize()} böbrekte grade {s(['bir', 'iki', 'üç'])} hidronefroz izlendi.",
        lambda: f"{s(SIDE).capitalize()} böbrek {s(['üst pol', 'orta kesim', 'alt pol'])}de {mm()} milimetre çaplı basit kortikal kist izlendi.",
        lambda: f"Dalak boyutu {int_to_words(random.randint(8, 15))} santimetre ölçülmüştür.",
        lambda: f"Batın içi serbest sıvı izlenmedi.",
        lambda: f"{s(LUNG_LOBE).capitalize()}da {s(LUNG_FIND)} izlendi.",
        lambda: f"{s(LUNG_LOBE).capitalize()}da {mm()} milimetre çaplı {s(MARGIN)} nodül izlendi.",
        lambda: f"Mediastinal ve hiler patolojik boyutta lenf nodu saptanmadı.",
        lambda: f"{s(['Sağ', 'Sol', 'Bilateral'])} plevral efüzyon izlendi.",
        lambda: f"Kardiyotorasik oran {s(['normal', 'artmış'])} olarak izlendi.",
        lambda: f"Pulmoner arter dallarında dolum defekti saptanmadı.",
        lambda: f"{s(BRAIN).capitalize()} {s(MR_SIGNAL)} {mm()} milimetrelik lezyon izlendi.",
        lambda: f"{s(BRAIN).capitalize()} kronik iskemik gliotik değişiklikler izlendi.",
        lambda: f"Ventriküler sistem ve sulkuslar yaşla uyumlu genişliktedir.",
        lambda: f"Akut intrakranial kanama veya kitle etkisi saptanmadı.",
        lambda: f"Difüzyon ağırlıklı görüntülerde {s(['sol', 'sağ'])} orta serebral arter sulama alanında akut enfarkt ile uyumlu difüzyon kısıtlaması izlendi.",
        lambda: f"{s(SPINE_LEVEL)} seviyesinde {s(DISC)} izlendi.",
        lambda: f"{s(SPINE_LEVEL)} seviyesinde spinal kanal {s(['hafif', 'orta derecede', 'belirgin'])} daralmıştır.",
        lambda: f"Vertebra korpuslarında dejeneratif osteofit oluşumları izlendi.",
        lambda: f"{s(['Medial', 'Lateral'])} menisküs {s(['arka boynuzda', 'ön boynuzda', 'gövdesinde'])} grade {s(['bir', 'iki', 'üç'])} yırtık ile uyumlu sinyal değişikliği izlendi.",
        lambda: f"Ön çapraz bağda {s(['parsiyel', 'tam kat'])} yırtık ile uyumlu bulgular izlendi.",
        lambda: f"Tiroid {s(SIDE)} lobda {mm()} milimetrelik {s(ECHO)} nodül izlendi, TI-RADS {s(['iki', 'üç', 'dört', 'beş'])} kategorisindedir.",
        lambda: f"{s(['Sağ', 'Sol'])} internal karotis arterde yüzde {int_to_words(random.choice(range(20, 90, 10)))} darlık oluşturan plak izlendi.",
        lambda: f"{s(['Sağ', 'Sol'])} {s(['popliteal', 'femoral', 'ana femoral'])} vende derin ven trombozu ile uyumlu trombüs izlendi.",
        lambda: s(COMPARE),
        lambda: s(CLOSING),
    ]


def weighted_terms() -> list[str]:
    if not VOCAB.exists():
        return []
    terms = []
    for line in VOCAB.read_text(encoding="utf-8").splitlines()[1:]:
        w, tf, df, ratio = line.split("\t")
        if float(ratio) >= 3000 and len(w) >= 6:
            terms += [w] * max(1, int(int(df) ** 0.5 / 10))
    return terms


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=16000)
    ap.add_argument("--out", default=str(HERE.parent / "data" / "radsynth_sentences.txt"))
    ap.add_argument("--templates", default=str(TEMPLATE_DIR))
    ap.add_argument("--reports", help="anonimleştirilmiş rapor metni (satır/paragraf)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    random.seed(a.seed)
    test = [ln.strip() for ln in TEST.read_text(encoding="utf-8").splitlines() if ln.strip()] if TEST.exists() else []
    out: list[str] = []
    if a.reports:
        text = Path(a.reports).read_text(encoding="utf-8")
        for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
            sent = normalize(sent.strip(), restore_case=True)
            if 4 <= len(sent.split()) <= 35 and not near_test(sent, test):
                out.append(sent)
    tpls, bad = load_templates(Path(a.templates))
    for b in bad:
        print("ATLANDI", b)
    if tpls:
        out += generate(tpls, max(0, a.n - len(out)), test_sentences=test, seed=a.seed)
    else:  # yerleşik şablonlar
        builtin = templates()
        for _ in range(a.n * 3):
            sent = normalize(random.choice(builtin)(), restore_case=True)
            if not near_test(sent, test):
                out.append(sent)
    uniq = list(dict.fromkeys(out))[:a.n]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(uniq) + "\n", encoding="utf-8")
    chars = sum(map(len, uniq))
    print(f"{len(tpls)} şablon ({len(bad)} atlandı) -> {len(uniq)} benzersiz cümle -> {a.out}")
    print(f"tahmini ses: {chars / 13 / 3600:.1f} saat (13 karakter/sn)")
    if TERMS.exists():
        terms = [t for t in TERMS.read_text(encoding="utf-8").splitlines() if t and not t.startswith("#")]
        ok, tot, missing = term_coverage(uniq, terms)
        print(f"radyoloji terimi kapsamı: {ok}/{tot} terim en az 3 kez geçiyor; hiç geçmeyen {len(missing)}")
    for s_ in random.sample(uniq, min(8, len(uniq))):
        print("  ", s_)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
