"""Tıbbi metin sonişleme.

Sıra:
  1. Kesin düzeltmeler (corrections_tr.tsv + kullanıcı dosyası): "e ka ge" -> "EKG"
  2. ITN (damga): "beş yüz" -> "500", "yüzde on" -> "%10"
  3. Birimler: "500 miligram" -> "500 mg"
  4. Bulanık terim eşleme (lexicon_tr.txt + kullanıcı dosyası): "metformın" -> "metformin",
     ek korunur: "hipertansiyonnu" -> "hipertansiyonu" değil, kök düzeltilir ek aynen kalır.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import process
from rapidfuzz.distance import Levenshtein

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

    text = _LVL_GARBLED_FIRST.sub(first, text)
    text = _LVL_GARBLED_SECOND.sub(second, text)
    text = _LVL_LEADING_DIGIT.sub(leading, text)
    return _LVL_PAIR.sub(pair, text)


def max_edits(n: int) -> int:
    """Kelime uzunluğuna göre izin verilen düzeltme mesafesi (kısa kelimeler dokunulmaz)."""
    if n < 7:
        return 0
    if n < 10:
        return 1
    return 2  # uzun kelimelerde 3 düzeltme, doğru kelimeleri başka kelimelere çeviriyordu


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
# ITN (damga) öncesi: "ön"ü "on" (10) sanıyor ("Ön çapraz bağ" -> "10 çapraz bağ"); harf+sayı omurga seviyesini
# önceki kelimeyle heceleme sanıyor ("görüntülemede L dört L beş" -> "Gd 5"), rakamlı hâline ("L4 L5") dokunmuyor.
_ON_WORD_RE = re.compile(r"(?<![\wÇĞİÖŞÜçğıöşü])([Öö][Nn])(?![\wÇĞİÖŞÜçğıöşü])")
_SPINE_NUMS = {"bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9,
               "on": 10, "on bir": 11, "on iki": 12}
_SPINE_WORD_RE = re.compile(r"(?<![\wÇĞİÖŞÜçğıöşü])([CTLS])\s+(on iki|on bir|bir|iki|üç|dört|beş|altı|yedi|sekiz|"
                            r"dokuz|on)(?![\wÇĞİÖŞÜçğıöşü])")
# Omurga seviyesinden önce "son" anlamsızdır: sağ/sol hatası raporda en tehlikeli hatadır.
_SIDE_RE = re.compile(r"(?<![\wçğıöşü])([Ss])on(?=\s+[LSCT]\s?(?:\d|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)\b)")
# Sesli biçim komutları (büyük/küçük harf Türkçe kurallarıyla duyarsız; model komutu noktalı cümle gibi verebilir)
_COMMANDS = {
    "yeni satır": "\n", "alt satıra geç": "\n", "satır başı": "\n",
    "yeni paragraf": "\n\n", "paragraf başı": "\n\n",
    "yeni madde": "\n• ",
}


def _tr_ci(phrase: str) -> str:
    """'satır başı' -> '[sS][aA][tT][ıI][rR]\\s+[bB]...' (re.IGNORECASE Türkçe ı/İ'yi doğru eşlemez)."""
    return r"\s+".join("".join(f"[{c}{tr_upper(c)}]" for c in w) for w in phrase.split())


# Komuttan önceki cümle noktası korunur ("normaldir. Alt satıra geç." -> "normaldir.\n"); virgül __call__'da atılır
_COMMAND_RE = re.compile(r"\s*\b((?:" + "|".join(_tr_ci(c) for c in sorted(_COMMANDS, key=len, reverse=True))
                         + r"))\b[\s.,;:]*")


@dataclass
class MedicalPostProcessor:
    lexicon: list[str] = field(default_factory=list)
    fuzzy_lexicon: list[str] | None = None   # None = lexicon'un tamamı bulanık düzeltme hedefi
    protected: list[str] = field(default_factory=list)  # doğru kabul edilen, asla düzeltilmeyen kelimeler
    context: object | None = None  # bağlamsal düzeltici (medical/context.py), rapor dil modeli varsa
    corrections: list[tuple[str, str]] = field(default_factory=list)
    use_itn: bool = True
    fuzzy: bool = True
    min_fuzzy_len: int = 7

    def __post_init__(self) -> None:
        # Uzun ifadeler önce: "e ka ge" "e ka"dan önce eşleşmeli
        self._corr = []
        for wrong, right in sorted(self.corrections, key=lambda p: -len(p[0])):
            if wrong.endswith("*"):  # kök düzeltmesi: "protezyon*" -> protezyonu, protezyonları ... ekler korunur
                rx = re.compile(r"(?<![\wçğıöşüÇĞİÖŞÜ])" + re.escape(tr_lower(wrong[:-1])) + r"(?=[a-zçğıöşü]*(?![\wçğıöşüÇĞİÖŞÜ]))")
            else:
                rx = re.compile(r"(?<![\wçğıöşüÇĞİÖŞÜ])" + re.escape(tr_lower(wrong)) + r"(?![\wçğıöşüÇĞİÖŞÜ])")
            self._corr.append((rx, right))
        # Tek kelimelik, yeterince uzun terimler bulanık eşlemeye girer
        self._fuzzy_terms = {}
        if self.fuzzy:
            targets = self.lexicon if self.fuzzy_lexicon is None else self.fuzzy_lexicon
            self._fuzzy_terms = {tr_lower(t): t for t in targets
                                 if " " not in t and len(t) >= self.min_fuzzy_len}
        self._fuzzy_keys = list(self._fuzzy_terms)
        # Yazım biçimi: sonra gelen dosya (kullanıcı sözlüğü) öncekini ezer — ama yalnızca küçük harfli bir kayıt
        # (raporlardan otomatik üretilen radyoloji listesi tümüyle küçük harflidir) el ile yazılmış "Doppler"i ezmez.
        self._canonical: dict[str, str] = {}
        for t in self.lexicon:
            if " " not in t and (t != tr_lower(t) or tr_lower(t) not in self._canonical):
                self._canonical[tr_lower(t)] = t
        self._protected = {tr_lower(t) for t in self.protected} | set(self._canonical)
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
                   fuzzy_files: list[Path] | None = None, protected_files: list[Path] | None = None,
                   **kw) -> "MedicalPostProcessor":
        """fuzzy_files verilirse bulanık düzeltme yalnızca bu dosyalardaki terimlere yapılır."""
        lex: list[str] = []
        for p in lexicon_files:
            lex += read_lexicon(p)
        if fuzzy_files is not None:
            kw["fuzzy_lexicon"] = [t for p in fuzzy_files for t in read_lexicon(p)]
        if protected_files:
            kw["protected"] = [t for p in protected_files for t in read_lexicon(p)]
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
        if self._itn is None:
            return text
        text = _SPINE_WORD_RE.sub(lambda m: f"{m.group(1)}{_SPINE_NUMS[m.group(2)]}", text)  # "L dört" -> "L4"
        parts = _ON_WORD_RE.split(text)  # "ön" damga'ya hiç gösterilmez; sayı ifadesi "ön"ü aşamaz
        return "".join(p if i % 2 else self._itn_piece(p) for i, p in enumerate(parts))

    def _itn_piece(self, s: str) -> str:
        core = s.strip()
        if not core:
            return s
        try:
            return s[:len(s) - len(s.lstrip())] + self._itn.normalize(core) + s[len(s.rstrip()):]
        except Exception:
            return s

    def _is_known(self, low: str) -> bool:
        """Kelime bir terimle (veya yumuşamış hâliyle) başlıyorsa doğru kabul edilir: terim + ek."""
        for t in self._prefix_index.get(low[:3], ()):
            if low.startswith(t):
                return True
        return False

    def _fuzzy_word(self, word: str) -> str:
        low = tr_lower(word)
        if len(low) < self.min_fuzzy_len or not self._fuzzy_keys or low in self._protected or self._is_known(low):
            return word
        best: tuple[int, int, str] | None = None  # (mesafe, ek uzunluğu, terim)
        # Kelimenin tamamı (k=0) ve son 1-4 harfi ek sayılarak kökü ("metforminin" -> "metformin"+"in")
        for k in range(0, 5):
            stem = low[:len(low) - k]
            limit = max_edits(len(stem))
            if limit == 0:
                break
            res = process.extract(stem, self._fuzzy_keys, scorer=Levenshtein.distance,
                                  score_cutoff=limit, limit=2)
            if not res:
                continue
            term, dist = res[0][0], int(res[0][1])
            if len(res) > 1 and int(res[1][1]) == dist:
                continue  # iki terime eşit uzaklıkta: belirsiz, dokunma
            if best is None or dist < best[0]:
                best = (dist, k, term)
        if best is None:
            return word
        _, k, term = best
        fixed = self._fuzzy_terms[term] + (low[len(low) - k:] if k else "")
        if word.isupper():
            return tr_upper(fixed)
        if word[:1].isupper():
            return tr_capitalize(fixed)
        return fixed

    def apply_fuzzy(self, text: str) -> str:
        if not self._fuzzy_keys:
            return text
        return _WORD_RE.sub(lambda m: self._fuzzy_word(m.group(0)), text)

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
                ok = j in self._protected
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
        if self.context is not None:
            text = self.context(text)  # "sol bacağı yayılan" -> "sol bacağa yayılan"
        text = self.apply_itn(text)
        text = normalize_units(text)
        text = normalize_spine_levels(text)
        text = _SIDE_RE.sub(lambda m: m.group(1) + "ol", text)  # "son L5 sinir kökü" -> "sol L5 ..."
        text = self.apply_fuzzy(text)
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
