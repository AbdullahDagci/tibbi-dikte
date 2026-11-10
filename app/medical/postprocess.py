"""Tıbbi metin sonişleme.

Sıra:
  1. Kesin düzeltmeler (corrections_tr.tsv + kullanıcı dosyası): "e ka ge" -> "EKG"
  2. ITN (damga): "beş yüz" -> "500", "yüzde on" -> "%10"
  3. Birimler: "500 miligram" -> "500 mg"

Yalnızca kesin kurallar uygulanır. Benzerliğe göre tahmin yapılmaz: "pankreatik"i "pankreatit"e, "menenjiom"u
"menenjitm"e çevirip klinik anlamı değiştiriyordu. Yanlış duyulan bir söyleniş corrections listesine eklenir.
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

# ------------------------------------------------------------------ Türkçe harf işlemleri
log = logging.getLogger(__name__)

_LOWER_MAP = str.maketrans({"I": "ı", "İ": "i"})
_UPPER_MAP = str.maketrans({"i": "İ", "ı": "I"})


def tr_lower(s: str) -> str:
    return s.translate(_LOWER_MAP).lower()


def tr_upper(s: str) -> str:
    return s.translate(_UPPER_MAP).upper()


def tr_capitalize(s: str) -> str:
    return tr_upper(s[:1]) + s[1:] if s else s


# ------------------------------------------------------------------ dosya okuma
def read_lexicon(path: Path) -> list[str]:
    if not path.is_file():
        return []
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def read_corrections(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    pairs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "\t" not in line:
            continue
        wrong, right = line.split("\t", 1)
        if wrong.strip() and right.strip():
            pairs.append((wrong.strip(), right.strip()))
    return pairs


# ------------------------------------------------------------------ birimler
_UNITS = [
    (r"mili\s*gram", "mg"), (r"mikro\s*gram", "mcg"), (r"nano\s*gram", "ng"),
    (r"kilo\s*gram", "kg"), (r"gram", "g"),
    (r"mili\s*litre", "ml"), (r"desi\s*litre", "dl"), (r"litre", "L"),
    (r"mili\s*metre\s+c[ıi]va", "mmHg"), (r"santi\s*metre", "cm"), (r"mili\s*metre", "mm"),
    (r"mili\s*ekivalan", "mEq"), (r"mili\s*mol", "mmol"),
    (r"internasyonel\s+[üu]nite", "IU"), (r"[üu]nite", "IU"),
]
_UNIT_RES = [(re.compile(r"(?P<num>\d+(?:[.,]\d+)?)\s+" + pat + r"(?P<rest>(?:l[ıiuü]k|d[ae]n?|t[ae]n?|l[ae]r)?)\b",
                         re.IGNORECASE), abbr) for pat, abbr in _UNITS]
_DOSE_THOUSANDS_RE = re.compile(r"\b(\d{1,3})\.(\d{3})(?=\s*(?:mg|mcg|ng|g|kg|ml|dl|L|IU|mEq|mmol)\b)")
# "tansiyon arteriyel 140 90" -> "tansiyon arteriyel 140/90"
_BP_RE = re.compile(r"(?i)\b(tansiyon(?:\s+arteriyel)?|TA|kan\s+basıncı)(\s*:?\s*)(\d{2,3})\s*(?:,|ile|üzeri|bölü|/)?\s+(\d{2,3})\b")


def normalize_units(text: str) -> str:
    for rx, abbr in _UNIT_RES:
        def repl(m: re.Match, abbr=abbr) -> str:
            rest = m.group("rest")
            return f"{m.group('num')} {abbr}" + (f"'{rest.lower()}" if rest else "")
        text = rx.sub(repl, text)
    # Dozlarda binlik ayırıcı kullanılmaz: "1.000 mg" -> "1000 mg"
    text = _DOSE_THOUSANDS_RE.sub(r"\1\2", text)
    text = _BP_RE.sub(lambda m: f"{m.group(1)}{m.group(2) or ' '}{m.group(3)}/{m.group(4)}", text)
    return text


# ------------------------------------------------------------------ sayı sanılan kelimeler
# damga (ITN) şunları sayıya çeviriyor: "ön çapraz bağ" -> "10 çapraz bağ", "cilt altı" -> "cilt 6",
# "yüz felci" -> "100 felci". "ön" hiçbir zaman sayı değildir; "altı"/"yüz" yalnızca açık sayı bağlamında sayıdır.
_NUMBER_WORDS = {"sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz", "on", "yirmi", "otuz",
                 "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan", "yüz", "bin", "milyon", "milyar", "buçuk",
                 "virgül"}
_COUNT_WORDS = {"miligram", "mikrogram", "gram", "kilogram", "mililitre", "litre", "santimetre", "milimetre", "metre",
                "mg", "mcg", "g", "kg", "ml", "cm", "mm", "saniye", "dakika", "saat", "gün", "hafta", "ay", "yıl",
                "yaşında", "yaşındaki", "yaş", "kez", "defa", "kere", "adet", "tane", "kat", "seans", "doz", "derece",
                "ünite", "kür", "seviye", "seviyede", "düzey", "düzeyinde", "hafta", "aylık", "günlük", "yıllık"}
_ALWAYS_WORD = {"ön"}
_AMBIGUOUS = {"altı", "yüz"}
_PH = "{}"  # özel kullanım alanı karakterleri: ITN'den dokunulmadan geçer
_TOKEN_RE = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]+|\d+")


def protect_number_words(text: str) -> tuple[str, list[str]]:
    toks = list(_TOKEN_RE.finditer(text))
    low = [tr_lower(m.group(0)) for m in toks]
    saved: list[str] = []
    out, pos = [], 0
    for i, m in enumerate(toks):
        w = low[i]
        protect = w in _ALWAYS_WORD or (w == "iki" and i > 0 and low[i - 1] == "her")  # "Her 2 akciğer" yazılmaz
        if w in _AMBIGUOUS:
            prev_ = low[i - 1] if i else ""
            next_ = low[i + 1] if i + 1 < len(low) else ""
            numeric = (prev_ in _NUMBER_WORDS or prev_.isdigit() or next_ in _NUMBER_WORDS
                       or next_ in _COUNT_WORDS or next_.isdigit())
            protect = not numeric
        if protect:
            out.append(text[pos:m.start()])
            out.append(_PH.format(len(saved)))
            saved.append(m.group(0))
            pos = m.end()
    out.append(text[pos:])
    return "".join(out), saved


_BACK_VOWELS, _FRONT_VOWELS = set("aıou"), set("eiöü")


def _harmonic_suffix(root: str, suffix: str) -> bool:
    """Türkçe ekler kökün son ünlüsüyle kalın/ince uyumludur ("odakla|ndı", "milimetre|dir"). Uymayan kalan ek
    değil, başka bir kelimenin devamıdır: radiology_known'daki "intra" parçası "intra|venez"i doğru sanıyordu."""
    rv = [c for c in root if c in _BACK_VOWELS or c in _FRONT_VOWELS]
    sv = [c for c in suffix if c in _BACK_VOWELS or c in _FRONT_VOWELS]
    if not rv or not sv:
        return True
    back = rv[-1] in _BACK_VOWELS
    return all((c in _BACK_VOWELS) == back for c in sv)


# ------------------------------------------------------------------ omurga seviyeleri
_SPINE_MAX = {"C": 7, "T": 12, "L": 5, "S": 5}
_SPINE_BRIDGE = {("C", 7, "T", 1), ("T", 12, "L", 1), ("L", 5, "S", 1)}


def _adjacent(a: str, i: int, b: str, j: int) -> bool:
    if a not in _SPINE_MAX or b not in _SPINE_MAX or not (1 <= i <= _SPINE_MAX[a]) or not (1 <= j <= _SPINE_MAX[b]):
        return False
    return (a == b and j == i + 1) or (a, i, b, j) in _SPINE_BRIDGE


_LVL_GARBLED_FIRST = re.compile(r"(?<![\w])([A-ZÇĞİÖŞÜ])\s?(\d{1,2})\s*[- ]\s*([CTLS])\s?(\d{1,2})(?![\d])")
_LVL_GARBLED_SECOND = re.compile(r"(?<![\w])([CLS])\s?(\d)\s*([A-Za-zÇĞİÖŞÜçğıöşü]?)\s*-?\s*(\d)(?![\d\w])")
_LVL_LEADING_DIGIT = re.compile(r"(?<![\w\d])(\d)([CLS])(\d)(?![\d\w])")
_LVL_PAIR = re.compile(r"(?<![\w])([CTLS])\s?(\d{1,2})\s*[- ]?\s*([CTLS])\s?(\d{1,2})(?![\d\w])")
# Çok seviyeli aralık ("C üç yedi" -> ITN "C3 7" -> "C3-C7"): yalnız seviye bağlamında (ardından disk/intervertebral…),
# "C3 7 mm" gibi ölçülere dokunulmaz
_LVL_RANGE = re.compile(r"(?<![\w])([CTLS])\s?(\d{1,2})\s*[- ]\s*(\d{1,2})"
                        r"(?=\s+(?i:intervertebral|disk|seviye|düzey|aralı|vertebra|korpus|segment))")
_MR_SEQ_CONTEXT = re.compile(r"^\W*(?:\w+\W+){0,2}?(?:ağırlık|sekans|seri|imaj|görüntü)", re.IGNORECASE)


def normalize_spine_levels(text: str) -> str:
    """Disk seviyelerini onarır ve 'C4-C5' biçimine getirir. Komşu seviyeler anatomik olarak bellidir:
      'G4 C5' -> 'C4-C5' · 'C5G 6' / 'C5J6' / 'C5 T6' -> 'C5-C6' · '4C5' -> 'C4-C5' · 'L4 L5' -> 'L4-L5'.
    T1/T2 aynı zamanda MR sekans adı olduğundan, ardından 'ağırlıklı/sekans/seri' geliyorsa dokunulmaz."""
    def first(m):
        a, i, b, j = m.group(1).upper(), int(m.group(2)), m.group(3), int(m.group(4))
        if a not in _SPINE_MAX and _adjacent(b, i, b, j):
            return f"{b}{i}-{b}{j}"
        return m.group(0)

    def second(m):
        a, i, mid, j = m.group(1), int(m.group(2)), m.group(3).upper(), int(m.group(4))
        if mid and _adjacent(a, i, mid, j):
            return m.group(0)  # zaten geçerli (ör. L5 S1): biçimlendirmeyi son adım yapar
        return f"{a}{i}-{a}{j}" if _adjacent(a, i, a, j) else m.group(0)

    def leading(m):
        i, a, j = int(m.group(1)), m.group(2), int(m.group(3))
        return f"{a}{i}-{a}{j}" if _adjacent(a, i, a, j) else m.group(0)

    def pair(m):
        a, i, b, j = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        if not _adjacent(a, i, b, j):
            return m.group(0)
        if a == "T" and b == "T" and _MR_SEQ_CONTEXT.match(text[m.end():m.end() + 40]):
            return m.group(0)
        return f"{a}{i}-{b}{j}"

    def span(m):
        a, i, j = m.group(1), int(m.group(2)), int(m.group(3))
        return f"{a}{i}-{a}{j}" if i < j <= _SPINE_MAX[a] else m.group(0)

    text = _LVL_GARBLED_FIRST.sub(first, text)
    text = _LVL_GARBLED_SECOND.sub(second, text)
    text = _LVL_LEADING_DIGIT.sub(leading, text)
    text = _LVL_RANGE.sub(span, text)
    return _LVL_PAIR.sub(pair, text)


_SUSPECT_MIN_LEN = 8  # bundan kısa kelimeler "sözlükte yok" diye işaretlenmez


# ------------------------------------------------------------------ ana sınıf
_WORD_RE = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]+")
_SOFTEN = {"k": "ğ", "p": "b", "t": "d", "ç": "c", "g": "ğ"}
# Küçük harfli (cins isim) kelimede kesme işareti yanlıştır: "ultrasonografisi'nde" -> "ultrasonografisinde".
# Özel isim / kısaltma / sayı (EKG'de, Ahmet'in, 2'de) büyük harf veya rakamla başladığı için dokunulmaz.
_LOWER_APOS_RE = re.compile(r"(?<![\wÇĞİÖŞÜçğıöşü'])([a-zçğıöşü]+)['’]([a-zçğıöşü]+)(?![\wÇĞİÖŞÜçğıöşü])")
_CAP_APOS_RE = re.compile(r"(?<![\wÇĞİÖŞÜçğıöşü'])([A-ZÇĞİÖŞÜ][a-zçğıöşü]+)['’]([a-zçğıöşü]+)(?![\wÇĞİÖŞÜçğıöşü])")
_PCT_SPACE_RE = re.compile(r"([A-Za-zÇĞİÖŞÜçğıöşü])%(\d)")  # "Satürasyonu%94" -> "Satürasyonu %94"
_L ="A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû"
_JOIN_RE = re.compile(rf"(?<![{_L}])([{_L}]+) ([a-zçğıöşüâîû]+)(?![{_L}])")
_PARTICLES = {"da", "de", "ta", "te"}
# Rapor kelime listesinde (radiology_known) bulunmayan kısa, sık kelimeler. Birleştirmede "ilk parça gerçek bir
# kelime değil" denetimi bunları bilemiyordu; raporlardaki bitişik yazım hatalarıyla ("heriki", "solmeme",
# "memeüst", "dışkadranda") doğru ayrı yazımları birleştiriyordu.
_COMMON_WORDS = {"her", "bir", "iki", "üç", "sol", "sağ", "üst", "alt", "ön", "arka", "iç", "dış", "orta", "yan",
                 "meme", "ana", "tam", "kat", "çok", "az", "en", "ve", "ile", "bu", "şu"}
# Birleştirmede sözlük terimi ikinci parçanın içine en az bu kadar harf uzanmalı: "para|santral" (7), "inten|site"
# (4) gerçek bölünmedir; "kist|i" (1) değildir ("kist izlendi" -> "kistizlendi" yapıyordu).
_MIN_JOIN_OVERLAP = 3
# ITN (damga) öncesi: harf+sayı omurga seviyesini önceki kelimeyle heceleme sanıyor ("görüntülemede L dört L beş"
# -> "Gd 5"), rakamlı hâline ("L4 L5") dokunmuyor. ("ön"/"altı"/"yüz" için bkz. protect_number_words.)
_SPINE_NUMS = {"bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9,
               "on": 10, "on bir": 11, "on iki": 12}
_SPINE_WORD_RE = re.compile(r"(?<![\wÇĞİÖŞÜçğıöşü])([CTLS])\s+(on iki|on bir|bir|iki|üç|dört|beş|altı|yedi|sekiz|"
                            r"dokuz|on)(?![\wÇĞİÖŞÜçğıöşü])")
# Harf adıyla söylenen MR sekansı ve torakal seviye: "te iki" -> "T2". ITN'den önce çevrilmeli, damga "bir ve te iki"yi
# "01 VT 2" yapıyor. Sayı devam ediyorsa ("te on üç") T1-T12 aralığında değildir, dokunulmaz.
_TE_WORD_RE = re.compile(r"(?<![\wÇĞİÖŞÜçğıöşü])[Tt][Ee]\s+(on iki|on bir|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)"
                         r"(?![\wÇĞİÖŞÜçğıöşü])(?!\s+(?:bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz)(?![\wÇĞİÖŞÜçğıöşü]))")
# Sınıflama numarası: "tip/evre/grade/kategori bir" -> 1 (ITN "bir"i "patolojik bir bulgu"daki gibi sözcük sayar)
_TYPE_ONE_RE = re.compile(r"(?<![\wÇĞİÖŞÜçğıöşü])([Tt]ip|[Ee]vre|[Gg]rade|[Kk]ategori)\s+bir(?![\wÇĞİÖŞÜçğıöşü])")
# Omurga seviyesinden önce "son" anlamsızdır: sağ/sol hatası raporda en tehlikeli hatadır.
_SIDE_RE = re.compile(r"(?<![\wçğıöşü])([Ss])on(?=\s+[LSCT]\s?(?:\d|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)\b)")
# Sesli biçim komutları (büyük/küçük harf Türkçe kurallarıyla duyarsız; model komutu noktalı cümle gibi verebilir)
_COMMANDS = {
    "yeni satır": "\n", "alt satıra geç": "\n", "satır başı": "\n", "satırbaşı": "\n",
    "alt satır": "\n", "altsatır": "\n",
    "yeni paragraf": "\n\n", "paragraf başı": "\n\n",
    "yeni madde": "\n• ",
}
COMMAND_PHRASES = tuple(_COMMANDS)  # Ayarlar › Sözlük'te terim önerisi (komuta söyleniş bağlamak için)

# Decoder güven skoru (sherpa_engine._word_confidences, ham/kalibre edilmemiş) ile vurgulama eşiği.
# tools/confidence_calibration.py ile ölçüldü (2026-11, tests/ + radyoloji_sentetik, 1310 kelime, 46 hata):
# <0.45 kelimelerin %1,5'i (%35'i gerçekten hatalı), <0.60 kelimelerin %11,9'u (%17'si hatalı, hataların %59'u).
# Kaba eşikler: 0.70 kelimelerin üçte birini boyuyordu. Referanslı gerçek sesle yeniden ölçülünce güncellenmeli.
CONF_RED = 0.45
CONF_ORANGE = 0.60
_UNIT_ABBRS = "mmHg|mmol|mcg|mEq|mg|ng|kg|ml|dl|cm|mm|IU|g|L"
_GAP_STRIP = " .,;:\n•"
# Yalnız sayı/birimden oluşan çıktı: "2", "140/90", "%10", "4 mm", "5 mm'lik"
_NUMERIC_RE = re.compile(rf"(?:[%\d][\d.,/%-]*\s*(?:(?:{_UNIT_ABBRS})\b)?(?:'[a-zçğıöşü]+)?\s*)+")


@dataclass
class WordScore:
    """Test ekranındaki güven tablosunun bir satırı: duyulan -> yazılan, ham güven ve rengin nedeni."""
    heard: str
    written: str
    confidence: float | None
    status: str  # "normal" | "suspect" | "corrected"
    reason: str = ""


def _expand_confidences(confidences: list[tuple[str, float]] | None) -> list[float] | None:
    """Motorun boşlukla ayrılmış kelimelerini _WORD_RE kelimelerine açar: "EKG'de" iki kelime sayılır."""
    if not confidences:
        return None
    return [c for w, c in confidences for _ in _WORD_RE.findall(w)]


def _tr_ci(phrase: str) -> str:
    """'satır başı' -> '[sS][aA][tT][ıI][rR]\\s+[bB]...' (re.IGNORECASE Türkçe ı/İ'yi doğru eşlemez)."""
    return r"\s+".join("".join(f"[{c}{tr_upper(c)}]" for c in w) for w in phrase.split())


# Komuttan önceki cümle noktası korunur ("normaldir. Alt satıra geç." -> "normaldir.\n"); virgül __call__'da atılır
_COMMAND_RE = re.compile(r"\s*\b((?:" + "|".join(_tr_ci(c) for c in sorted(_COMMANDS, key=len, reverse=True))
                         + r"))\b[\s.,;:]*")


@dataclass
class MedicalPostProcessor:
    lexicon: list[str] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)  # doğru kabul edilen kelimeler (rapor kelime listesi)
    general: list[str] = field(default_factory=list)  # genel Türkçe kelimeler (koruma + bağlaç kontrolü)
    corrections: list[tuple[str, str]] = field(default_factory=list)
    use_itn: bool = True

    def __post_init__(self) -> None:
        # Uzun ifadeler önce: "e ka ge" "e ka"dan önce eşleşmeli
        self._corr = []
        for wrong, right in sorted(self.corrections, key=lambda p: -len(p[0])):
            if wrong.endswith("*"):  # kök düzeltmesi: "protezyon*" -> protezyonu, protezyonları ... ekler korunur
                rx = re.compile(r"(?<![\wçğıöşüÇĞİÖŞÜ])" + re.escape(tr_lower(wrong[:-1])) + r"(?=[a-zçğıöşü]*(?![\wçğıöşüÇĞİÖŞÜ]))")
            else:
                rx = re.compile(r"(?<![\wçğıöşüÇĞİÖŞÜ])" + re.escape(tr_lower(wrong)) + r"(?![\wçğıöşüÇĞİÖŞÜ])")
            self._corr.append((rx, right))
        # Yazım biçimi: sonra gelen dosya (kullanıcı sözlüğü) öncekini ezer — ama yalnızca küçük harfli bir kayıt
        # (raporlardan otomatik üretilen radyoloji listesi tümüyle küçük harflidir) el ile yazılmış "Doppler"i ezmez.
        self._canonical: dict[str, str] = {}
        for t in self.lexicon:
            if " " not in t and (t != tr_lower(t) or tr_lower(t) not in self._canonical):
                self._canonical[tr_lower(t)] = t
        self._general = {tr_lower(t) for t in self.general}
        self._protected = {tr_lower(t) for t in self.protected} | set(self._canonical) | self._general
        self._protected_prefix: dict[str, set[str]] = {}
        for w in self._protected:
            if len(w) >= 5:
                self._protected_prefix.setdefault(w[:3], set()).add(w)
        # Bilinen terim önekleri (yumuşama dahil: ...k -> ...ğ, ...p -> ...b, ...t -> ...d, ...ç -> ...c)
        self._prefix_index: dict[str, set[str]] = {}
        for t in {tr_lower(x) for x in self.lexicon if " " not in x and len(x) >= 4}:
            forms = {t}
            if t[-1] in _SOFTEN:
                forms.add(t[:-1] + _SOFTEN[t[-1]])
            for f in forms:
                self._prefix_index.setdefault(f[:3], set()).add(f)
        self._itn = None
        if self.use_itn:
            try:
                from damga import InverseNormalizer
                self._itn = InverseNormalizer()
                log.info("ITN etkin: %s", self._itn.normalize("beş yüz miligram"))
            except Exception:
                log.exception("ITN (damga) yüklenemedi; sayılar yazıyla kalacak")
                self._itn = None

    @classmethod
    def from_files(cls, lexicon_files: list[Path], correction_files: list[Path],
                   protected_files: list[Path] | None = None, general_files: list[Path] | None = None,
                   **kw) -> "MedicalPostProcessor":
        lex: list[str] = []
        for p in lexicon_files:
            lex += read_lexicon(p)
        if protected_files:
            kw["protected"] = [t for p in protected_files for t in read_lexicon(p)]
        if general_files:
            kw["general"] = [t for p in general_files for t in read_lexicon(p)]
        corr: list[tuple[str, str]] = []
        for p in correction_files:
            corr += read_corrections(p)
        return cls(lexicon=lex, corrections=corr, **kw)

    # -------------------------------------------------- adımlar
    def apply_corrections(self, text: str) -> str:
        """İki geçiş: bir düzeltmenin sonucu başka bir (daha uzun) düzeltmeyi tetikleyebilir
        ("interventerral disiplinde" -> "intervertebral disiplinde" -> "intervertebral diskinde")."""
        return self._corrections_pass(self._corrections_pass(text))

    def _corrections_pass(self, text: str) -> str:
        """Büyük/küçük harf duyarsız (Türkçe kurallarıyla) kesin değiştirme."""
        for rx, right in self._corr:
            low = tr_lower(text)
            out, pos = [], 0
            for m in rx.finditer(low):
                out.append(text[pos:m.start()])
                original = text[m.start():m.end()]
                # Cümle başındaysa ve hedef küçük harfle başlıyorsa büyük harfi koru
                out.append(tr_capitalize(right) if original[:1].isupper() and right[:1].islower() else right)
                pos = m.end()
            out.append(text[pos:])
            text = "".join(out)
        return text

    def apply_itn(self, text: str) -> str:
        """Sayıları rakama çevirir; sayı sanılabilecek kelimeleri önce korur (bkz. protect_number_words)."""
        if self._itn is None:
            return text
        # Omurga seviyesi önce: "C altı" -> "C6" ("altı" aksi hâlde sayı bağlamı görülmeden korunurdu)
        text = _TE_WORD_RE.sub(lambda m: f"T{_SPINE_NUMS[m.group(1)]}", text)
        text = _SPINE_WORD_RE.sub(lambda m: f"{m.group(1)}{_SPINE_NUMS[m.group(2)]}", text)  # "L dört" -> "L4"
        text = _TYPE_ONE_RE.sub(r"\1 1", text)  # "Modic tip bir" -> "tip 1" (ITN "bir"i sözcük sayar)
        protected, saved = protect_number_words(text)
        try:
            out = self._itn.normalize(protected)
        except Exception:
            return text
        for i, word in enumerate(saved):
            out = out.replace(_PH.format(i), word)
        return out

    def _is_known(self, low: str) -> bool:
        """Kelime bir terimle (veya yumuşamış hâliyle) başlıyorsa doğru kabul edilir: terim + ek."""
        for t in self._prefix_index.get(low[:3], ()):
            if low.startswith(t):
                return True
        return False

    def _is_protected(self, low: str) -> bool:
        """Geçerli bir kelime mi? Tam eşleşme ya da geçerli kök + kısa ek ("milimetre"+"dir", "odakla"+"ndı")."""
        if low in self._protected:
            return True
        for w in self._protected_prefix.get(low[:3], ()):
            if (len(low) - len(w) <= 5 and len(w) >= max(5, len(low) - 5) and low.startswith(w)
                    and _harmonic_suffix(w, low[len(w):])):
                return True
        return False

    def apply_casing(self, text: str) -> str:
        """Sözlükteki terimleri sözlükteki yazımına getirir (cümle ortasında "Arteriyel" -> "arteriyel",
        "parkinson" -> "Parkinson"). Cümle başında ilk harfin büyüklüğü korunur (dikte parçası
        cümle ortasından başlayabileceği için zorla büyütülmez)."""
        def repl(m: re.Match) -> str:
            word = m.group(0)
            canon = self._canonical.get(tr_lower(word))
            if canon is None or word.isupper() and len(word) > 1 and not canon.isupper():
                return word
            before = text[:m.start()].rstrip()
            sentence_start = not before or before[-1] in ".!?:"
            if sentence_start and word[:1].isupper():
                return tr_capitalize(canon)
            return canon
        return _WORD_RE.sub(repl, text)

    def _term_span(self, low: str) -> int:
        """low'un başındaki en uzun sözlük teriminin uzunluğu (yoksa 0)."""
        best = 0
        for t in self._prefix_index.get(low[:3], ()):
            if len(t) > best and low.startswith(t):
                best = len(t)
        return best

    def apply_join(self, text: str) -> str:
        """Modelin ikiye böldüğü kelimeleri birleştirir: "para santralin" -> "parasantralin",
        "inten sitesi" -> "intensitesi", "sekanslar da" -> "sekanslarda".
        Birleştirme yalnızca (a) birleşik kelime raporlarda geçiyorsa ya da (b) bir sözlük terimi iki parçanın
        sınırını aşıyorsa yapılır; "pulmoner arter" gibi doğru ayrı yazımlar korunur."""
        def repl(m: re.Match) -> str:
            a, b = m.group(1), m.group(2)
            j = tr_lower(a + b)
            al = tr_lower(a)
            if tr_lower(b) in _PARTICLES:  # bağlaç "da/de" mi, ayrılmış hâl eki mi? yalnızca raporda geçen biçim
                ok = j in self._protected and tr_lower(a) not in self._general
            else:
                ok = self._term_span(j) >= len(a) + _MIN_JOIN_OVERLAP or (
                    j in self._protected and al not in self._protected and al not in _COMMON_WORDS and len(a) >= 3)
            return a + tr_lower(b) if ok else m.group(0)
        return _JOIN_RE.sub(repl, text)

    def _prepare(self, text: str) -> str:
        """Komut ayrıştırmasından önce: boşluk, kesme işareti ve kesin düzeltmeler (kullanıcı varyantı bir
        komuta da bağlanabilsin: "alt sağa geç" -> "alt satıra geç")."""
        text = " ".join(text.split())
        if not text:
            return text
        text = _LOWER_APOS_RE.sub(lambda m: m.group(1) + m.group(2), text)
        # Büyük harfle başlayan ama bir tıbbi terimle başlayan kelime de cins isimdir: "Ultrasonografisi'nde"
        text = _CAP_APOS_RE.sub(lambda m: m.group(1) + m.group(2) if self._is_known(tr_lower(m.group(1))) else m.group(0), text)
        return self.apply_corrections(text)

    def _process(self, text: str) -> str:
        text = " ".join(text.split())
        if not text:
            return text
        text = self.apply_join(text)
        text = self.apply_itn(text)
        text = normalize_units(text)
        text = normalize_spine_levels(text)
        text = _SIDE_RE.sub(lambda m: m.group(1) + "ol", text)  # "son L5 sinir kökü" -> "sol L5 ..."
        text = self.apply_casing(text)
        text = _PCT_SPACE_RE.sub(r"\1 %\2", text)
        return text

    def __call__(self, text: str) -> str:
        """Sesli biçim komutları (_COMMANDS: "alt satıra geç", "paragraf başı", "yeni madde" ...) metni böler;
        parçalar ayrı işlenir."""
        parts = _COMMAND_RE.split(self._prepare(text))
        out = []
        for i, part in enumerate(parts):
            if i % 2:  # komut
                out.append(_COMMANDS[tr_lower(" ".join(part.split()))])
            else:
                piece = self._process(part)
                if out and out[-1].endswith(("\n", "• ")):
                    piece = piece.lstrip(" .,:;")
                if i + 1 < len(parts):  # komuttan önceki parçanın sonundaki boşluk/virgül
                    piece = piece.rstrip(" ,;")
                out.append(piece)
        return "".join(out)

    # -------------------------------------------------- vurgulama (Test ekranı canlı editörü)
    def _is_suspect(self, word: str) -> bool:
        """Uzun ve hiçbir sözlükte ya da genel kelime listesinde geçmeyen kelime: yanlış duyulmuş olabilir.
        Metin değiştirilmez, yalnızca kullanıcının gözden geçirmesi için işaretlenir."""
        low = tr_lower(word)
        return (len(low) >= _SUSPECT_MIN_LEN and bool(self._protected)
                and not self._is_protected(low) and not self._is_known(low))

    def _word_status(self, word: str, c: float | None) -> tuple[str, str]:
        if c is not None and c < CONF_RED:
            return "corrected", "düşük güven"
        if self._is_suspect(word):
            return "suspect", "sözlükte yok"
        if c is not None and c < CONF_ORANGE:
            return "suspect", "orta güven"
        return "normal", ""

    def _analyze(self, text: str, confidences: list[tuple[str, float]] | None
                 ) -> tuple[str, list[tuple[int, int, WordScore]]]:
        """Nihai metin ve her parçanın (başlangıç, bitiş, WordScore) kaydı; kayıtlar çakışmaz ve sıralıdır.
        confidences kelime sayısıyla eşleşmezse yok sayılır (motorun kelime hizalaması garanti değil)."""
        final = self(text)
        heard = _WORD_RE.findall(text)
        confs = _expand_confidences(confidences)
        if confs is not None and len(confs) != len(heard):
            confs = None
        written = list(_WORD_RE.finditer(final))
        sm = difflib.SequenceMatcher(None, [tr_lower(w) for w in heard],
                                     [tr_lower(m.group(0)) for m in written], autojunk=False)
        items: list[tuple[int, int, WordScore]] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for off in range(i2 - i1):
                    m = written[j1 + off]
                    c = confs[i1 + off] if confs else None
                    status, reason = self._word_status(m.group(0), c)
                    items.append((m.start(), m.end(), WordScore(heard[i1 + off], m.group(0), c, status, reason)))
                continue
            # Rakamlar _WORD_RE kelimesi değil: komşu kelimelerin arası alınır ("beş yüz miligram" -> "500 mg")
            gap_start = written[j1 - 1].end() if j1 else 0
            gap_end = written[j2].start() if j2 < len(written) else len(final)
            gap = final[gap_start:gap_end]
            piece = gap.strip(_GAP_STRIP)
            start = gap_start + len(gap) - len(gap.lstrip(_GAP_STRIP))
            c = min(confs[i1:i2]) if confs and i2 > i1 else None
            if not piece:  # ör. sesli komut: boyanacak metin yok
                status, reason = "normal", "sonişleme değiştirdi"
            elif _NUMERIC_RE.fullmatch(piece):  # doğru dönüşüm boyanmaz; yanlış duyulmuş olabilecek ölçü boyanır
                status, reason = self._word_status("", c)
                reason = reason or "sayı/birim dönüşümü"
            else:
                status, reason = "corrected", "sonişleme değiştirdi"
            items.append((start, start + len(piece), WordScore(" ".join(heard[i1:i2]), piece, c, status, reason)))
        return final, items

    def word_scores(self, text: str, confidences: list[tuple[str, float]] | None = None) -> list[WordScore]:
        """annotate() ile aynı kararların kelime kelime dökümü: duyulan, yazılan, güven ve rengin nedeni."""
        return [row for _, _, row in self._analyze(text, confidences)[1]]

    def annotate(self, text: str, confidences: list[tuple[str, float]] | None = None) -> list[tuple[str, str]]:
        """__call__ ile birebir aynı metni (metin, durum) parçaları olarak verir. "corrected" (kırmızı):
        sonişleme değiştirdi (sayı/birim dönüşümleri hariç) ya da decoder güveni CONF_RED altında.
        "suspect" (turuncu): sözlükte yok ya da güveni CONF_ORANGE altında. Karşılaştırma ham metinle
        yapıldığından _prepare() içindeki kesin düzeltmeler de yakalanır."""
        final, items = self._analyze(text, confidences)
        spans: list[tuple[str, str]] = []
        pos = 0
        for start, end, row in items:
            if start > pos:
                spans.append((final[pos:start], "normal"))
            if end > start:
                spans.append((final[start:end], row.status))
            pos = max(pos, end)
        if pos < len(final):
            spans.append((final[pos:], "normal"))
        merged: list[tuple[str, str]] = []
        for t, s in spans:
            if merged and merged[-1][1] == s:
                merged[-1] = (merged[-1][0] + t, s)
            else:
                merged.append((t, s))
        return merged
