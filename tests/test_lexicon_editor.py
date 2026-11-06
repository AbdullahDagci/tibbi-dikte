"""Sözlük ekranı: sayfalı tablo, terim düzenleme penceresi (her söyleniş ayrı satır, "ekli hâlleri de" kutusu
"kök*" yazımının yerini alır), sözlüğü deneme kutusu ve kendi Kaydet düğmesi."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox  # noqa: E402

from app import user_dict  # noqa: E402
from app.lexicon_editor import LexiconEditor, LexiconPage, TermDialog  # noqa: E402
from app.user_dict import Entry, join_root, preview, split_root  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _shown_terms(ed):
    return [e.term for e in ed.table.visible_rows()]


def test_root_marker_split_and_join():
    assert split_root("protezyon*") == ("protezyon", True)
    assert split_root("bete") == ("bete", False)
    assert join_root("protezyon", True) == "protezyon*" and join_root("bete", False) == "bete"


def test_preview_applies_only_dictionary_corrections():
    entries = [Entry("BT", ["bete"]), Entry("protrüzyon", ["protezyon*"])]
    assert preview(entries, "Bete çekildi, protezyonu izlendi.") == "BT çekildi, protrüzyonu izlendi."


# ------------------------------------------------------------ terim penceresi
def test_variants_added_one_per_enter_or_comma_separated(qapp):
    d = TermDialog(Entry("BT", []))
    d.variant_input.setText("bete")
    d.add_variants_from_input()
    d.variant_input.setText("pete, Pete ,  em ti")
    d.add_variants_from_input()
    assert d.entry() == Entry("BT", ["bete", "pete", "em ti"])
    assert d.variant_input.text() == ""


def test_suffix_checkbox_replaces_star_syntax(qapp):
    d = TermDialog(Entry("protrüzyon", ["protezyon*", "protrizyon"]))
    t = d.variant_table
    assert [t.item(r, 0).text() for r in range(t.rowCount())] == ["protezyon", "protrizyon"]
    assert t.item(0, 1).checkState() == Qt.Checked and t.item(1, 1).checkState() == Qt.Unchecked
    t.item(1, 1).setCheckState(Qt.Checked)
    assert d.entry() == Entry("protrüzyon", ["protezyon*", "protrizyon*"])


def test_typed_star_becomes_checkbox(qapp):
    d = TermDialog(Entry("protrüzyon", []))
    d.variant_input.setText("protezyon*")
    d.add_variants_from_input()
    assert d.variant_table.item(0, 0).text() == "protezyon"
    assert d.variant_table.item(0, 1).checkState() == Qt.Checked


def test_same_variant_only_upgrades_to_suffix_form(qapp):
    d = TermDialog(Entry("BT", ["bete"]))
    d.variant_input.setText("Bete*")
    d.add_variants_from_input()
    assert d.entry() == Entry("BT", ["bete*"])


def test_editing_variant_text_in_table(qapp):
    d = TermDialog(Entry("BT", ["bete"]))
    d.variant_table.item(0, 0).setText("pete")
    assert d.entry() == Entry("BT", ["pete"])


def test_remove_selected_variant(qapp):
    d = TermDialog(Entry("BT", ["bete", "pete"]))
    d.variant_table.selectRow(0)
    d.remove_selected_variants()
    assert d.entry() == Entry("BT", ["pete"])


def test_dialog_cannot_be_accepted_without_a_term(qapp):
    d = TermDialog(Entry("", []))
    ok = d.buttons.button(QDialogButtonBox.Save)
    assert not ok.isEnabled()
    d.term_edit.setText("BT")
    assert ok.isEnabled()
    d.term_edit.setText("   ")
    assert not ok.isEnabled()


def test_editing_dialog_does_not_change_the_original_until_returned(qapp):
    original = Entry("BT", ["bete"])
    d = TermDialog(original)
    d.term_edit.setText("MR")
    d.variant_input.setText("em ar")
    d.add_variants_from_input()
    assert original == Entry("BT", ["bete"])


# ------------------------------------------------------------ tablo
def test_table_shows_term_variants_and_suffix_answer(qapp):
    ed = LexiconEditor([Entry("protrüzyon", ["protezyon*", "protrizyon"]), Entry("BT", ["bete"]), Entry("MR", [])])
    t = ed.table.table
    assert t.item(0, 0).text() == "protrüzyon"
    assert t.item(0, 1).text() == "protezyon, protrizyon"
    assert t.item(0, 2).text() == "Evet"      # söylenişlerden biri ekli hâlleri de düzeltiyor
    assert t.item(1, 2).text() == "Hayır"     # söyleniş var, ekli hâl yok
    assert t.item(2, 1).text() == "—" and t.item(2, 2).text() == "—"    # değer yok


def test_suffix_column_sorts_by_its_text(qapp):
    ed = LexiconEditor([Entry("a", ["x"]), Entry("b", []), Entry("c", ["y*"])])
    ed.table._header_clicked(2)
    t = ed.table.table
    assert [t.item(r, 2).text() for r in range(3)] == ["—", "Evet", "Hayır"]


def test_large_dictionary_is_paginated(qapp):
    ed = LexiconEditor([Entry(f"terim{i:03d}", []) for i in range(500)])
    assert ed.table.table.rowCount() == 10
    assert ed.table.info.text() == "1-10 / 500 kayıt"
    assert len(ed.entries()) == 500


def test_search_matches_terms_and_variants(qapp):
    ed = LexiconEditor([Entry("BT", ["bete", "pete"]), Entry("MR", ["em ar"])])
    ed.search.setText("pete")
    assert _shown_terms(ed) == ["BT"]
    ed.search.setText("")
    assert _shown_terms(ed) == ["BT", "MR"]


def test_remove_entry_keeps_others(qapp):
    bt, mr = Entry("BT", ["bete"]), Entry("MR", ["em ar"])
    ed = LexiconEditor([bt, mr])
    ed.remove_entry(ed.table.visible_rows()[0])
    assert ed.entries() == [mr]


def test_delete_button_in_row_removes_that_row(qapp):
    from PySide6.QtWidgets import QPushButton
    ed = LexiconEditor([Entry("BT", []), Entry("MR", [])])
    buttons = ed.table.table.cellWidget(1, 3).findChildren(QPushButton)
    assert len(buttons) == 2
    buttons[1].click()
    assert [e.term for e in ed.entries()] == ["BT"]


def test_edit_button_opens_dialog_and_applies_result(qapp, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    ed = LexiconEditor([Entry("Bt", ["bete"])])
    seen = []

    def answer(entry, title):
        seen.append(entry)
        return Entry("BT", ["bete", "pete"])
    monkeypatch.setattr(ed, "_ask_entry", answer)
    ed.table.table.cellWidget(0, 3).findChildren(QPushButton)[0].click()
    assert seen == [Entry("Bt", ["bete"])]
    assert ed.entries() == [Entry("BT", ["bete", "pete"])]
    assert ed.table.table.item(0, 0).text() == "BT"


def test_cancelled_dialog_changes_nothing(qapp, monkeypatch):
    ed = LexiconEditor([Entry("BT", ["bete"])])
    monkeypatch.setattr(ed, "_ask_entry", lambda entry, title: None)
    ed.edit_entry(ed.table.visible_rows()[0])
    ed.new_entry()
    assert ed.entries() == [Entry("BT", ["bete"])]
    assert not ed.is_dirty()


def test_new_entry_is_added_and_shown_even_on_a_later_page(qapp, monkeypatch):
    ed = LexiconEditor([Entry(f"t{i:02d}", []) for i in range(12)])
    monkeypatch.setattr(ed, "_ask_entry", lambda entry, title: Entry("yeni", ["yeniy"]))
    ed.new_entry()
    assert ed.table.page == 2 and "yeni" in _shown_terms(ed)


def test_adding_existing_term_merges_variants(qapp):
    ed = LexiconEditor([Entry("BT", ["bete"])])
    ed.add_entry(Entry("BT", ["pete"]))
    assert ed.entries() == [Entry("BT", ["bete", "pete"])]


def test_renaming_onto_existing_term_merges_into_single_row(qapp):
    a, b = Entry("BT", ["bete"]), Entry("Bt", ["pete"])
    ed = LexiconEditor([a, b])
    ed.update_entry(ed.table.visible_rows()[1], Entry("BT", ["pete"]))
    assert ed.entries() == [Entry("BT", ["bete", "pete"])]


def test_empty_terms_are_dropped_and_duplicates_merged_on_read(qapp):
    ed = LexiconEditor([Entry("BT", ["bete"]), Entry("  ", ["x"]), Entry("BT", ["pete"])])
    assert ed.entries() == [Entry("BT", ["bete", "pete"])]


def test_try_box_shows_live_result_and_follows_changes(qapp):
    ed = LexiconEditor([Entry("BT", ["bete"])])
    ed.try_input.setText("bete çekildi")
    assert "BT çekildi" in ed.try_output.text()
    ed.add_entry(Entry("MR", ["em ar"]))
    ed.try_input.setText("em ar ve bete")
    assert "MR ve BT" in ed.try_output.text()
    ed.add_entry(Entry("Kontrast", ["kontras"]))
    ed.try_input.setText("kontras")
    assert "Kontrast" in ed.try_output.text()


def test_dirty_flag_follows_changes_and_reverts(qapp):
    ed = LexiconEditor([Entry("BT", ["bete"])])
    seen = []
    ed.dirty_changed.connect(seen.append)
    assert not ed.is_dirty()
    ed.add_entry(Entry("MR", []))
    assert ed.is_dirty() and seen == [True]
    ed.remove_entry(ed.table.visible_rows()[1])
    assert not ed.is_dirty() and seen == [True, False]


# ------------------------------------------------------------ sayfa: her değişiklik anında kaydedilir
@pytest.fixture
def page(qapp, tmp_path):
    lex, corr = tmp_path / "terimler.txt", tmp_path / "duzeltmeler.tsv"
    user_dict.save([Entry("BT", ["bete"])], lex, corr)
    p = LexiconPage(lex, corr)
    yield p
    p.deleteLater()


def _on_disk(page):
    return user_dict.load(page.lexicon_path, page.corrections_path)


def test_new_term_is_saved_and_reported_immediately(page):
    fired = []
    page.saved.connect(lambda: fired.append(True))
    page.editor.add_entry(Entry("MR", ["em ar"]))
    assert fired == [True]
    assert _on_disk(page) == [Entry("BT", ["bete"]), Entry("MR", ["em ar"])]
    assert not page.editor.is_dirty() and not page.dirty_badge.isVisibleTo(page)


def test_applying_new_term_dialog_saves_without_another_button(page, monkeypatch):
    monkeypatch.setattr(page.editor, "_ask_entry", lambda entry, title: Entry("ahmet", ["ömer"]))
    page.editor.new_entry()
    assert Entry("ahmet", ["ömer"]) in _on_disk(page)


def test_editing_term_is_saved_immediately(page, monkeypatch):
    monkeypatch.setattr(page.editor, "_ask_entry", lambda entry, title: Entry("BT", ["bete", "pete"]))
    page.editor.edit_entry(page.editor.table.visible_rows()[0])
    assert _on_disk(page) == [Entry("BT", ["bete", "pete"])]


def test_deleting_term_is_saved_immediately(page):
    page.editor.remove_entry(page.editor.table.visible_rows()[0])
    assert _on_disk(page) == []


def test_cancelled_dialog_does_not_save(page, monkeypatch):
    fired = []
    page.saved.connect(lambda: fired.append(True))
    monkeypatch.setattr(page.editor, "_ask_entry", lambda entry, title: None)
    page.editor.new_entry()
    assert fired == []


def test_page_has_no_separate_save_button(page):
    from PySide6.QtWidgets import QPushButton
    assert not [b for b in page.findChildren(QPushButton) if b.text() == "Kaydet"]


def test_import_is_saved_immediately(page, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    source = tmp_path / "gelen.csv"
    user_dict.export_file([Entry("MR", ["em ar"])], source)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(source), "")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    page._import()
    assert Entry("MR", ["em ar"]) in _on_disk(page)


def _make_conflict(page, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    page.editor.add_entry(Entry("MR", ["bete"]))     # "bete" zaten BT'ye bağlı
    return warned


def test_conflicting_variant_is_not_written_and_warns(page, monkeypatch):
    warned = _make_conflict(page, monkeypatch)
    assert warned and "bete" in warned[0]
    assert _on_disk(page) == [Entry("BT", ["bete"])]
    assert page.editor.is_dirty() and page.dirty_badge.isVisibleTo(page)


def test_fixing_conflict_saves_automatically(page, monkeypatch):
    _make_conflict(page, monkeypatch)
    page.editor.update_entry(page.editor.table.visible_rows()[1], Entry("MR", ["em ar"]))
    assert _on_disk(page) == [Entry("BT", ["bete"]), Entry("MR", ["em ar"])]
    assert not page.editor.is_dirty() and not page.dirty_badge.isVisibleTo(page)


def test_reload_shows_disk_changes(page):
    user_dict.add_variant(page.lexicon_path, page.corrections_path, "pete", "BT")
    page.reload_from_disk()
    assert page.editor.entries() == [Entry("BT", ["bete", "pete"])]
    assert not page.editor.is_dirty()


def test_reload_keeps_unwritten_conflict_and_adds_disk_change(page, monkeypatch):
    _make_conflict(page, monkeypatch)
    user_dict.add_variant(page.lexicon_path, page.corrections_path, "pete", "BT")
    page.reload_from_disk()
    assert page.editor.entries() == [Entry("BT", ["bete", "pete"]), Entry("MR", ["bete"])]
    assert page.editor.is_dirty()


def test_change_does_not_overwrite_hand_edits_made_while_page_is_open(page):
    user_dict.save([Entry("BT", ["bete"]), Entry("Doppler", [])], page.lexicon_path, page.corrections_path)
    page.editor.add_entry(Entry("MR", ["em ar"]))
    assert sorted(e.term for e in _on_disk(page)) == ["BT", "Doppler", "MR"]


def test_enter_in_variant_box_adds_and_keeps_dialog_open(qapp):
    from PySide6.QtTest import QTest
    d = TermDialog(Entry("BT", []))
    d.show()
    d.variant_input.setText("bete")
    QTest.keyClick(d.variant_input, Qt.Key_Return)
    d.variant_input.setText("pete")
    QTest.keyClick(d.variant_input, Qt.Key_Return)
    assert d.isVisible() and d.entry() == Entry("BT", ["bete", "pete"])
    d.reject()
    d.deleteLater()


# ------------------------------------------------------------ dosya değişikliğini bekleyen düzenlemeye uygulama
def test_rebase_keeps_pending_term_deletion():
    base = [Entry("BT", ["bete"]), Entry("MR", ["em ar"])]
    disk = [Entry("BT", ["bete", "pete"]), Entry("MR", ["em ar"])]
    assert user_dict.rebase(base, disk, [Entry("BT", ["bete"])]) == [Entry("BT", ["bete", "pete"])]


def test_rebase_keeps_pending_variant_removal():
    base = [Entry("BT", ["bete", "pete"])]
    disk = [Entry("BT", ["bete", "pete", "be te"])]
    assert user_dict.rebase(base, disk, [Entry("BT", ["pete"])]) == [Entry("BT", ["pete", "be te"])]


def test_rebase_does_not_duplicate_variant_with_pending_suffix_change():
    base = [Entry("BT", ["bete"])]
    disk = [Entry("BT", ["bete", "pete"])]
    assert user_dict.rebase(base, disk, [Entry("BT", ["bete*"])]) == [Entry("BT", ["bete*", "pete"])]


def test_rebase_moves_variant_like_the_file_did():
    base = [Entry("BT", ["bete"]), Entry("MR", ["em ar"])]
    disk = [Entry("BT", []), Entry("MR", ["em ar", "bete"])]
    current = [Entry("BT", ["bete"]), Entry("MR", ["em ar"]), Entry("Doppler", [])]
    moved = user_dict.rebase(base, disk, current)
    assert user_dict.conflicts(moved) == []
    assert moved == [Entry("BT", []), Entry("MR", ["em ar", "bete"]), Entry("Doppler", [])]


def test_rebase_adds_term_created_on_disk():
    base = [Entry("BT", [])]
    disk = [Entry("BT", []), Entry("MR", ["em ar"])]
    current = [Entry("BT", []), Entry("Doppler", [])]
    assert user_dict.rebase(base, disk, current) == [Entry("BT", []), Entry("Doppler", []), Entry("MR", ["em ar"])]


def test_rebase_removes_term_deleted_on_disk_unless_it_still_has_edits():
    base = [Entry("BT", ["bete"]), Entry("MR", ["em ar"])]
    disk = [Entry("MR", ["em ar"])]
    assert user_dict.rebase(base, disk, [Entry("BT", ["bete"]), Entry("MR", ["em ar"])]) == [Entry("MR", ["em ar"])]
    kept = user_dict.rebase(base, disk, [Entry("BT", ["bete", "pete"]), Entry("MR", ["em ar"])])
    assert kept == [Entry("BT", ["pete"]), Entry("MR", ["em ar"])]


def test_dictionary_term_column_stands_out(qapp):
    ed = LexiconEditor([Entry("BT", ["bete"])])
    assert ed.table.table.item(0, 0).font().bold()
    assert ed.table.table.showGrid() and ed.table.table.alternatingRowColors()


def test_finished_dialog_does_not_stay_in_memory(qapp, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    monkeypatch.setattr(TermDialog, "exec", lambda self: QDialog.Accepted)
    ed = LexiconEditor([Entry("BT", [])])
    assert ed._ask_entry(Entry("MR", ["em ar"]), "Yeni terim") == Entry("MR", ["em ar"])
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert ed.findChildren(TermDialog) == []


def test_opening_page_picks_up_hand_edited_file(qapp, tmp_path):
    lex, corr = tmp_path / "t.txt", tmp_path / "d.tsv"
    user_dict.save([Entry("BT", ["bete"])], lex, corr)
    p = LexiconPage(lex, corr)
    user_dict.save([Entry("BT", ["bete"]), Entry("MR", ["em ar"])], lex, corr)
    p.show()
    assert p.editor.entries() == [Entry("BT", ["bete"]), Entry("MR", ["em ar"])]
    assert not p.editor.is_dirty()
    p.hide()
    p.deleteLater()


def test_opening_page_keeps_table_position_when_file_is_unchanged(qapp, tmp_path):
    lex, corr = tmp_path / "t.txt", tmp_path / "d.tsv"
    user_dict.save([Entry(f"t{i:02d}", []) for i in range(25)], lex, corr)
    p = LexiconPage(lex, corr)
    p.show()
    p.editor.table.set_page(2)
    p.hide()
    p.show()
    assert p.editor.table.page == 2
    p.hide()
    p.deleteLater()


def test_new_entry_is_shown_on_its_sorted_page(qapp, monkeypatch):
    ed = LexiconEditor([Entry(f"t{i:02d}", []) for i in range(25)])
    ed.table._header_clicked(0)
    ed.add_entry(Entry("a", []))
    assert ed.table.page == 1 and "a" in _shown_terms(ed)
