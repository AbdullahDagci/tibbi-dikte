"""Kullanıcı sözlüğü: doğru yazım + söyleniş varyantları; dosyalara kaydetme, dışa/içe aktarma, birleştirme."""
from app.medical.postprocess import MedicalPostProcessor, read_corrections, read_lexicon
from app.user_dict import Entry, add_variant, conflicts, export_file, import_file, load, merge, parse_variants, save


def _files(tmp_path, lex: str, corr: str):
    lp, cp = tmp_path / "terimler.txt", tmp_path / "duzeltmeler.tsv"
    lp.write_text(lex, encoding="utf-8")
    cp.write_text(corr, encoding="utf-8")
    return lp, cp


def test_load_groups_variants_by_term(tmp_path):
    lp, cp = _files(tmp_path, "# yorum\nparankim\n", "# yorum\nbete\tBT\npete\tBT\nem ar\tMR\n")
    assert load(lp, cp) == [Entry("parankim", []), Entry("BT", ["bete", "pete"]), Entry("MR", ["em ar"])]


def test_load_merges_term_present_in_both_files(tmp_path):
    lp, cp = _files(tmp_path, "BT\n", "bete\tBT\n")
    assert load(lp, cp) == [Entry("BT", ["bete"])]


def test_save_roundtrip_and_files_feed_postprocessor(tmp_path):
    lp, cp = tmp_path / "t.txt", tmp_path / "d.tsv"
    entries = [Entry("BT", ["bete", "pete"]), Entry("parankim", []), Entry("protrüzyon", ["protezyon*"])]
    save(entries, lp, cp)
    assert load(lp, cp) == entries
    assert read_lexicon(lp) == ["BT", "parankim", "protrüzyon"]
    assert read_corrections(cp) == [("bete", "BT"), ("pete", "BT"), ("protezyon*", "protrüzyon")]
    pp = MedicalPostProcessor.from_files([lp], [cp], use_itn=False)
    assert pp("Toraks pete incelemesi") == "Toraks BT incelemesi"


def test_parse_variants_trims_dedupes_and_drops_term_itself():
    assert parse_variants(" bete, pete ,, Bete, BT ", term="BT") == ["bete", "pete"]


def test_merge_adds_new_terms_and_new_variants_only():
    base = [Entry("BT", ["bete"]), Entry("MR", [])]
    incoming = [Entry("BT", ["Bete", "pete"]), Entry("FLAIR", ["flor", "fler"])]
    merged, new_terms, new_variants = merge(base, incoming)
    assert merged == [Entry("BT", ["bete", "pete"]), Entry("MR", []), Entry("FLAIR", ["flor", "fler"])]
    assert (new_terms, new_variants) == (1, 3)
    assert base == [Entry("BT", ["bete"]), Entry("MR", [])]  # girdi değişmez


def test_export_import_roundtrip(tmp_path):
    entries = [Entry("BT", ["bete", "pete"]), Entry("Toraks", []), Entry("lenf nodu", ["lenf notu", "lenf nolu"])]
    p = tmp_path / "sozluk.csv"
    export_file(entries, p)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")  # Excel Türkçe karakterleri doğru açsın
    assert import_file(p) == entries


def test_import_accepts_tab_and_comma_files_and_plain_term_lists(tmp_path):
    tab = tmp_path / "a.tsv"
    tab.write_text("Doğru yazım\tSöyleniş varyantları\nBT\tbete, pete\n", encoding="utf-8")
    assert import_file(tab) == [Entry("BT", ["bete", "pete"])]
    comma = tmp_path / "b.csv"
    comma.write_text('Doğru yazım,Söyleniş varyantları\nBT,"bete, pete"\n', encoding="utf-8")
    assert import_file(comma) == [Entry("BT", ["bete", "pete"])]
    plain = tmp_path / "c.txt"
    plain.write_text("parankim\n\nkonsolidasyon\n", encoding="utf-8")
    assert import_file(plain) == [Entry("parankim", []), Entry("konsolidasyon", [])]


def test_add_variant_creates_term_and_appends(tmp_path):
    lp, cp = _files(tmp_path, "", "")
    assert add_variant(lp, cp, "pete", "BT") == []
    assert add_variant(lp, cp, "Bete", "BT") == []
    assert load(lp, cp) == [Entry("BT", ["pete", "Bete"])]


def test_add_variant_moves_variant_bound_to_another_term(tmp_path):
    lp, cp = _files(tmp_path, "", "pete\tPET\npe te\tPET\n")
    assert add_variant(lp, cp, "Pete", "BT") == ["PET"]
    assert load(lp, cp) == [Entry("PET", ["pe te"]), Entry("BT", ["Pete"])]


def test_conflicts_reports_variant_bound_to_two_terms():
    entries = [Entry("BT", ["bete"]), Entry("PET", ["Bete", "pet"]), Entry("MR", ["em ar"])]
    assert conflicts(entries) == [("bete", ["BT", "PET"])]
