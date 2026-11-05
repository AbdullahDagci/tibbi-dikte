"""Ayarlar › Sözlük düzenleyicisi: solda terimler, sağda seçili terimin söylenişleri (her biri ayrı satır,
"ekli hâlleri de" kutusu "kök*" yazımının yerini alır) ve sözlüğü deneme kutusu."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.lexicon_editor import LexiconEditor  # noqa: E402
from app.user_dict import Entry, join_root, preview, split_root  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _visible_terms(ed):
    return [ed.term_list.item(i).data(Qt.UserRole) for i in range(ed.term_list.count())
            if not ed.term_list.item(i).isHidden()]


def test_root_marker_split_and_join():
    assert split_root("protezyon*") == ("protezyon", True)
    assert split_root("bete") == ("bete", False)
    assert join_root("protezyon", True) == "protezyon*" and join_root("bete", False) == "bete"


def test_preview_applies_only_dictionary_corrections():
    entries = [Entry("BT", ["bete"]), Entry("protrüzyon", ["protezyon*"])]
    assert preview(entries, "Bete çekildi, protezyonu izlendi.") == "BT çekildi, protrüzyonu izlendi."


def test_variants_added_one_per_enter_or_comma_separated(qapp):
    ed = LexiconEditor([])
    ed.add_term("BT")
    ed.variant_input.setText("bete")
    ed.add_variants_from_input()
    ed.variant_input.setText("pete, Pete ,  em ti")
    ed.add_variants_from_input()
    assert ed.entries() == [Entry("BT", ["bete", "pete", "em ti"])]
    assert ed.variant_input.text() == ""


def test_suffix_checkbox_replaces_star_syntax(qapp):
    ed = LexiconEditor([Entry("protrüzyon", ["protezyon*", "protrizyon"])])
    ed.select_term(0)
    t = ed.variant_table
    assert [t.item(r, 0).text() for r in range(t.rowCount())] == ["protezyon", "protrizyon"]
    assert t.item(0, 1).checkState() == Qt.Checked and t.item(1, 1).checkState() == Qt.Unchecked
    t.item(1, 1).setCheckState(Qt.Checked)
    assert ed.entries() == [Entry("protrüzyon", ["protezyon*", "protrizyon*"])]


def test_typed_star_becomes_checkbox(qapp):
    ed = LexiconEditor([])
    ed.add_term("protrüzyon")
    ed.variant_input.setText("protezyon*")
    ed.add_variants_from_input()
    assert ed.variant_table.item(0, 0).text() == "protezyon"
    assert ed.variant_table.item(0, 1).checkState() == Qt.Checked


def test_editing_variant_text_in_table(qapp):
    ed = LexiconEditor([Entry("BT", ["bete"])])
    ed.select_term(0)
    ed.variant_table.item(0, 0).setText("bete ")
    ed.variant_table.item(0, 0).setText("pete")
    assert ed.entries() == [Entry("BT", ["pete"])]


def test_remove_selected_variant_and_term(qapp):
    ed = LexiconEditor([Entry("BT", ["bete", "pete"]), Entry("MR", ["em ar"])])
    ed.select_term(0)
    ed.variant_table.selectRow(0)
    ed.remove_selected_variants()
    assert ed.entries()[0] == Entry("BT", ["pete"])
    ed.remove_current_term()
    assert ed.entries() == [Entry("MR", ["em ar"])]


def test_renaming_term_updates_list(qapp):
    ed = LexiconEditor([Entry("Bt", ["bete"])])
    ed.select_term(0)
    ed.term_edit.setText("BT")
    assert ed.entries() == [Entry("BT", ["bete"])]
    assert ed.term_list.item(0).text().startswith("BT")


def test_search_matches_terms_and_variants(qapp):
    ed = LexiconEditor([Entry("BT", ["bete", "pete"]), Entry("MR", ["em ar"])])
    ed.search.setText("pete")
    assert _visible_terms(ed) == [0]
    ed.search.setText("")
    assert _visible_terms(ed) == [0, 1]


def test_try_box_shows_live_result(qapp):
    ed = LexiconEditor([Entry("BT", ["bete"])])
    ed.try_input.setText("bete çekildi")
    assert "BT çekildi" in ed.try_output.text()
    ed.add_term("MR")
    ed.variant_input.setText("em ar")
    ed.add_variants_from_input()
    ed.try_input.setText("em ar ve bete")
    assert "MR ve BT" in ed.try_output.text()


def test_empty_terms_are_dropped_and_duplicates_merged(qapp):
    ed = LexiconEditor([Entry("BT", ["bete"])])
    ed.add_term("")            # boş bırakılan yeni terim kaydedilmez
    ed.add_term("BT")          # aynı terim ikinci kez: tek kayıtta birleşir
    ed.variant_input.setText("pete")
    ed.add_variants_from_input()
    assert ed.entries() == [Entry("BT", ["bete", "pete"])]


def test_detail_panel_disabled_without_selection(qapp):
    ed = LexiconEditor([])
    assert not ed.detail.isEnabled()
    ed.add_term("BT")
    assert ed.detail.isEnabled()
