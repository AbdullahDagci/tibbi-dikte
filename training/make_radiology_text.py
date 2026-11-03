"""Sentetik radyoloji rapor cümleleri üretir (TTS ile seslendirilip eğitim verisi olacak).

Şablonlar mamografi / USG / BT / MR / grafi rapor dilini izler; yuvalar (organ, bulgu, boyut, yer…) rastgele
doldurulur. rad_dict'ten türeyen data/radiology_vocab.tsv varsa, raporlarda sık geçen ifadeler daha sık seçilir.
Sayılar YAZIYLA üretilir (model çıktı biçimi). Test cümleleri (data/radiology_test) eğitim setine sızmasın diye
çıkarılır.

En iyi kaynak gerçek (anonimleştirilmiş) rapor metinleridir: varsa --reports ile verin, cümlelere bölünüp
şablon cümleleriyle karıştırılır.

  python make_radiology_text.py --n 20000 --out data/radsynth_sentences.txt [--reports raporlar.txt]
"""
from __future__ import annotations

import argparse
import random
import re
from pathlib import Path

from textnorm import int_to_words, normalize

HERE = Path(__file__).resolve().parent
VOCAB = HERE.parent / "data" / "radiology_vocab.tsv"
TEST = HERE.parent / "data" / "radiology_test" / "sentences.txt"

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
        lambda: f"Karaciğer {s(LIVER_SEG)} {mm()} milimetre çaplı {s(ECHO)} lezyon izlendi.",
        lambda: f"Safra kesesi lümeninde {mm()} milimetre çaplı akustik gölge veren taş izlendi.",
        lambda: f"{s(SIDE).capitalize()} böbrekte grade {s(['bir', 'iki', 'üç'])} hidronefroz izlendi.",
        lambda: f"{s(SIDE).capitalize()} böbrek {s(['üst pol', 'orta kesim', 'alt pol'])}de {mm()} milimetre çaplı basit kortikal kist izlendi.",
        lambda: f"Dalak boyutu {cm()} santimetre ölçülmüştür.",
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
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--out", default=str(HERE / "data" / "radsynth_sentences.txt"))
    ap.add_argument("--reports", help="anonimleştirilmiş rapor metni (satır/paragraf)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    random.seed(a.seed)
    test = {normalize(l).lower() for l in TEST.read_text(encoding="utf-8").splitlines() if l.strip()} if TEST.exists() else set()
    out: list[str] = []
    if a.reports:
        text = Path(a.reports).read_text(encoding="utf-8")
        for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
            sent = normalize(sent.strip(), restore_case=True)
            if 4 <= len(sent.split()) <= 35:
                out.append(sent)
    tpls = templates()
    while len(out) < a.n:
        sent = normalize(random.choice(tpls)(), restore_case=True)
        out.append(sent)
    uniq = list(dict.fromkeys(s for s in out if s.lower() not in test))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(uniq) + "\n", encoding="utf-8")
    print(f"{len(uniq)} benzersiz cümle -> {a.out}")
    for s_ in random.sample(uniq, 8):
        print("  ", s_)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
