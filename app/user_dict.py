"""Kullanıcı sözlüğü: her terim için doğru yazım + modelin duyabileceği söyleniş varyantları.

Diskte mevcut iki dosya kullanılır (sonişleyici ve hotword üretimi bunları okur):
  kullanici_terimler.txt     her satırda bir doğru yazım (hotword + yazım biçimi)
  kullanici_duzeltmeler.tsv  her satırda  varyant<TAB>doğru yazım   ("kök*" biçimi ekleri korur)

Dışa/içe aktarma dosyası Excel'de açılabilen CSV'dir (UTF-8 BOM, ";" ayraçlı):
  Doğru yazım;Söyleniş varyantları
  BT;bete, pete
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from .medical.postprocess import MedicalPostProcessor, read_corrections, read_lexicon, tr_lower

HEADER = ("Doğru yazım", "Söyleniş varyantları")
_LEX_HEADER = "# Kendi tıbbi terimleriniz — her satıra bir terim (Ayarlar › Sözlük'ten düzenleyin)\n"
_CORR_HEADER = "# söyleniş varyantı<TAB>doğru yazım (Ayarlar › Sözlük'ten düzenleyin)\n"


@dataclass
class Entry:
    term: str
    variants: list[str] = field(default_factory=list)


def parse_variants(text: str, term: str = "") -> list[str]:
    """'bete, pete ,, Bete' -> ['bete', 'pete'] (tekrarsız, terimin kendisi hariç)."""
    seen = {tr_lower(term.strip())} if term.strip() else set()
    out = []
    for v in text.split(","):
        v = " ".join(v.split())
        if v and tr_lower(v) not in seen:
            seen.add(tr_lower(v))
            out.append(v)
    return out


def split_root(variant: str) -> tuple[str, bool]:
    """'protezyon*' -> ('protezyon', True): sondaki * "ekli hâlleri de düzelt" demektir."""
    v = variant.strip()
    return (v[:-1].rstrip(), True) if v.endswith("*") else (v, False)


def join_root(text: str, with_suffixes: bool) -> str:
    text = " ".join(text.replace("*", " ").split())
    return text + "*" if with_suffixes and text else text


def preview(entries: list[Entry], text: str) -> str:
    """Yalnızca sözlüğün etkisi: söylenişler doğru yazıma çevrilir (Ayarlar › Sözlük › Dene kutusu)."""
    pp = MedicalPostProcessor(corrections=[(v, e.term) for e in entries if e.term.strip() for v in e.variants],
                              use_itn=False)
    return pp.apply_corrections(text)


def _add(entries: list[Entry], index: dict[str, Entry], term: str, variants: list[str]) -> tuple[int, int]:
    """Terimi (yoksa) ekler, yeni varyantları ekler. -> (yeni terim sayısı, yeni varyant sayısı)."""
    e = index.get(term)
    new_term = 0
    if e is None:
        e = index[term] = Entry(term, [])
        entries.append(e)
        new_term = 1
    have = {tr_lower(v) for v in e.variants} | {tr_lower(term)}
    added = 0
    for v in variants:
        if tr_lower(v) not in have:
            have.add(tr_lower(v))
            e.variants.append(v)
            added += 1
    return new_term, added


def load(lexicon_path: Path, corrections_path: Path) -> list[Entry]:
    entries: list[Entry] = []
    index: dict[str, Entry] = {}
    for term in read_lexicon(lexicon_path):
        _add(entries, index, term, [])
    for variant, term in read_corrections(corrections_path):
        _add(entries, index, term, [variant])
    return entries


def save(entries: list[Entry], lexicon_path: Path, corrections_path: Path) -> None:
    terms = [e.term.strip() for e in entries if e.term.strip()]
    lexicon_path.write_text(_LEX_HEADER + "".join(t + "\n" for t in terms), encoding="utf-8")
    lines = [f"{v}\t{e.term.strip()}\n" for e in entries if e.term.strip() for v in e.variants]
    corrections_path.write_text(_CORR_HEADER + "".join(lines), encoding="utf-8")


def merge(base: list[Entry], incoming: list[Entry]) -> tuple[list[Entry], int, int]:
    """Mevcut sözlüğü silmeden birleştirir. -> (yeni liste, eklenen terim, eklenen varyant)."""
    merged = [Entry(e.term, list(e.variants)) for e in base]
    index = {e.term: e for e in merged}
    new_terms = new_variants = 0
    for e in incoming:
        t, v = _add(merged, index, e.term, e.variants)
        new_terms += t
        new_variants += v
    return merged, new_terms, new_variants


def rebase(base: list[Entry], disk: list[Entry], current: list[Entry]) -> list[Entry]:
    """Dosyadaki değişikliği (base -> disk) kaydedilmemiş düzenlemelerin (current) üzerine uygular.
    Birleşim almaz: silinmiş terim ve söyleniş geri gelmez, aynı söyleniş iki terime bağlanmaz."""
    def pairs(entries: list[Entry]) -> dict[tuple[str, str], str]:
        return {(e.term, tr_lower(split_root(v)[0])): v for e in entries for v in e.variants}

    def key_of(variant: str) -> str:
        return tr_lower(split_root(variant)[0])

    result = [Entry(e.term, list(e.variants)) for e in current]
    by_term = {e.term: e for e in result}
    old, new = pairs(base), pairs(disk)
    for term, key in old.keys() - new.keys():
        if term in by_term:
            by_term[term].variants = [v for v in by_term[term].variants if key_of(v) != key]
    base_terms = {e.term for e in base}
    dropped = base_terms - {e.term for e in disk}  # dosyadan silinen terim; düzenlenmişse (söylenişi kaldıysa) durur
    result = [e for e in result if not (e.term in dropped and not e.variants)]
    by_term = {e.term: e for e in result}
    for e in disk:
        if e.term not in base_terms and e.term not in by_term:
            by_term[e.term] = Entry(e.term, [])
            result.append(by_term[e.term])
        for v in e.variants:
            key = key_of(v)
            if (e.term, key) in old:
                continue
            for other in result:  # son karar geçerli: söyleniş başka terimdeyse oradan alınır
                if other.term != e.term:
                    other.variants = [x for x in other.variants if key_of(x) != key]
            if e.term not in by_term:
                by_term[e.term] = Entry(e.term, [])
                result.append(by_term[e.term])
            if key not in {key_of(x) for x in by_term[e.term].variants}:
                by_term[e.term].variants.append(v)
    return result


def add_variant(lexicon_path: Path, corrections_path: Path, variant: str, term: str) -> list[str]:
    """Tek varyantı sözlüğe ekleyip kaydeder (editörde "Sözlüğe varyant olarak ekle").
    Varyant başka terime bağlıysa oradan alınır (son karar geçerli). -> varyantın alındığı terimler."""
    variant, term = " ".join(variant.split()), " ".join(term.split())
    entries = load(lexicon_path, corrections_path)
    moved = []
    for e in entries:
        if e.term != term and any(tr_lower(v) == tr_lower(variant) for v in e.variants):
            e.variants = [v for v in e.variants if tr_lower(v) != tr_lower(variant)]
            moved.append(e.term)
    merged, _, _ = merge(entries, [Entry(term, parse_variants(variant, term))])
    save(merged, lexicon_path, corrections_path)
    return moved


def conflicts(entries: list[Entry]) -> list[tuple[str, list[str]]]:
    """Aynı varyant birden çok terime bağlıysa: [(varyant, [terimler])]."""
    by_variant: dict[str, list[str]] = {}
    for e in entries:
        for v in e.variants:
            terms = by_variant.setdefault(tr_lower(v), [])
            if e.term not in terms:
                terms.append(e.term)
    return [(v, t) for v, t in by_variant.items() if len(t) > 1]


def export_file(entries: list[Entry], path: Path) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(HEADER)
    for e in entries:
        w.writerow([e.term, ", ".join(e.variants)])
    path.write_text(buf.getvalue(), encoding="utf-8-sig")


def import_file(path: Path) -> list[Entry]:
    """Dışa aktarılmış CSV'yi (; , veya TAB ayraçlı) ya da düz terim listesini okur."""
    text = path.read_text(encoding="utf-8-sig")
    first = next((line for line in text.splitlines() if line.strip()), "")
    delim = "\t" if "\t" in first else ";" if ";" in first else "," if "," in first else ";"
    entries: list[Entry] = []
    index: dict[str, Entry] = {}
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
            continue
        term = " ".join(row[0].split())
        if tr_lower(term) == tr_lower(HEADER[0]):
            continue
        _add(entries, index, term, parse_variants(row[1], term) if len(row) > 1 else [])
    return entries
