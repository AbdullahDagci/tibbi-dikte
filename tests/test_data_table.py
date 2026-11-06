"""Sayfalı, aramalı tablo bileşeni."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from app.medical.postprocess import tr_lower  # noqa: E402
from app.ui.data_table import Column, DataTable, RowAction, page_numbers, paginate  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("total,page,size,number,pages,start,end", [
    (0, 1, 10, 1, 1, 0, 0),         # boş liste
    (42, 1, 10, 1, 5, 0, 10),
    (42, 2, 10, 2, 5, 10, 20),
    (42, 5, 10, 5, 5, 40, 42),      # son sayfa eksik dolu
    (42, 9, 10, 5, 5, 40, 42),      # fazla büyük sayfa son sayfaya iner
    (42, 0, 10, 1, 5, 0, 10),       # sıfır ilk sayfaya çıkar
    (40, 4, 10, 4, 4, 30, 40),      # tam bölünen toplam fazladan sayfa açmaz
    (5, 1, 25, 1, 1, 0, 5),
])
def test_paginate(total, page, size, number, pages, start, end):
    p = paginate(total, page, size)
    assert (p.number, p.pages, p.start, p.end, p.total) == (number, pages, start, end, total)


@pytest.mark.parametrize("current,pages,expected", [
    (1, 1, [1]),
    (2, 5, [1, 2, 3, 4, 5]),
    (1, 20, [1, 2, 3, None, 20]),
    (10, 20, [1, None, 8, 9, 10, 11, 12, None, 20]),
    (20, 20, [1, None, 18, 19, 20]),
    (4, 20, [1, 2, 3, 4, 5, 6, None, 20]),      # tek sayfalık boşluk için üç nokta konmaz
])
def test_page_numbers(current, pages, expected):
    assert page_numbers(current, pages) == expected


def _table(rows, removed=None):
    t = DataTable([Column("Terim", lambda r: r["t"], stretch=True), Column("Söyleniş", lambda r: r["v"])],
                  search_text=lambda r: f'{r["t"]} {r["v"]}', normalize=tr_lower,
                  actions=[RowAction("trash", "Sil", lambda r: removed.append(r) if removed is not None else None)])
    t.set_rows(rows)
    return t


def _rows(n):
    return [{"t": f"terim{i:03d}", "v": f"soy{i:03d}"} for i in range(n)]


def test_first_page_shows_only_page_size_rows_and_summary(qapp):
    t = _table(_rows(42))
    assert t.table.rowCount() == 10
    assert t.table.item(0, 0).text() == "terim000"
    assert t.info.text() == "1-10 / 42 kayıt"


def test_next_and_previous_buttons_move_and_stop_at_the_ends(qapp):
    t = _table(_rows(25))
    assert not t.btn_prev.isEnabled() and t.btn_next.isEnabled()
    t.btn_next.click()
    assert t.table.item(0, 0).text() == "terim010"
    t.btn_next.click()
    assert t.table.rowCount() == 5 and t.info.text() == "21-25 / 25 kayıt"
    assert not t.btn_next.isEnabled() and t.btn_prev.isEnabled()
    t.btn_prev.click()
    assert t.page == 2


def test_clicking_a_page_number_opens_that_page(qapp):
    t = _table(_rows(42))
    buttons = {b.text(): b for b in t.pager.findChildren(QPushButton) if b.text().isdigit()}
    assert sorted(buttons) == ["1", "2", "3", "4", "5"]
    buttons["4"].click()
    assert t.page == 4 and t.table.item(0, 0).text() == "terim030"


def test_page_size_change_returns_to_first_page(qapp):
    t = _table(_rows(60))
    t.set_page(3)
    t.size_box.setCurrentIndex(t.size_box.findData(25))
    assert t.page == 1 and t.table.rowCount() == 25 and t.info.text() == "1-25 / 60 kayıt"


def test_search_filters_on_all_text_and_returns_to_first_page(qapp):
    t = _table(_rows(42))
    t.set_page(4)
    t.search.setText("soy031")
    assert t.page == 1 and t.table.rowCount() == 1 and t.table.item(0, 0).text() == "terim031"
    assert t.info.text() == "1-1 / 1 kayıt"
    t.search.clear()
    assert t.info.text() == "1-10 / 42 kayıt"


@pytest.mark.parametrize("query", ["İBUPROFEN", "ibuprofen", "İbuprofen"])
def test_search_uses_turkish_letter_rules(qapp, query):
    t = _table([{"t": "ibuprofen", "v": ""}, {"t": "kısa", "v": ""}])
    t.search.setText(query)
    assert t.table.rowCount() == 1 and t.table.item(0, 0).text() == "ibuprofen"


def test_empty_result_shows_message_instead_of_table(qapp):
    t = _table(_rows(3))
    t.show()
    t.search.setText("olmayan")
    assert t.table.rowCount() == 0 and t.empty.isVisible() and not t.table.isVisible()
    assert t.info.text() == "0 kayıt"
    t.search.clear()
    assert t.table.isVisible() and not t.empty.isVisible()
    t.hide()
    t.deleteLater()


def test_row_action_receives_its_own_row_on_later_pages(qapp):
    removed = []
    rows = _rows(15)
    t = _table(rows, removed)
    t.set_page(2)
    t.table.cellWidget(2, 2).findChild(QPushButton).click()
    assert removed == [rows[12]]


def test_removing_last_row_of_last_page_moves_to_previous_page(qapp):
    rows = _rows(11)
    t = _table(rows)
    t.set_page(2)
    t.set_rows(rows[:10], keep_page=True)
    assert t.page == 1 and t.table.rowCount() == 10


def test_keep_page_stays_when_page_still_exists(qapp):
    rows = _rows(30)
    t = _table(rows)
    t.set_page(2)
    t.set_rows(rows[:25], keep_page=True)
    assert t.page == 2 and t.table.item(0, 0).text() == "terim010"


def test_table_shows_grid_lines_and_striped_rows(qapp):
    t = _table(_rows(3))
    assert t.table.showGrid() and t.table.alternatingRowColors()


def test_grid_and_stripe_colors_are_defined_in_theme():
    from app import theme
    assert "alternate-background-color" in theme.QSS and "gridline-color" in theme.QSS


def test_emphasized_column_is_bold(qapp):
    t = DataTable([Column("Terim", lambda r: r["t"], bold=True), Column("Söyleniş", lambda r: r["v"])],
                  search_text=lambda r: r["t"])
    t.set_rows(_rows(1))
    assert t.table.item(0, 0).font().bold() and not t.table.item(0, 1).font().bold()


# ------------------------------------------------------------ kolon sıralama
def _click_header(t, column):
    t.table.horizontalHeader().sectionClicked.emit(column)


def _column_text(t, column=0):
    return [t.table.item(r, column).text() for r in range(t.table.rowCount())]


def _sort_table(words):
    t = DataTable([Column("Terim", lambda r: r["t"], stretch=True), Column("Adet", lambda r: str(r["n"]) if r["n"] else "—", sort_key=lambda r: r["n"])],
                  search_text=lambda r: r["t"], normalize=tr_lower,
                  actions=[RowAction("trash", "Sil", lambda r: None)])
    t.set_rows([{"t": w, "n": len(w) % 3} for w in words])
    return t


def test_header_click_sorts_and_second_click_reverses(qapp):
    t = _sort_table(["beta", "alfa", "gama"])
    assert _column_text(t) == ["beta", "alfa", "gama"]    # başlangıçta sırasız
    _click_header(t, 0)
    assert _column_text(t) == ["alfa", "beta", "gama"]
    _click_header(t, 0)
    assert _column_text(t) == ["gama", "beta", "alfa"]


def test_sort_uses_turkish_alphabet(qapp):
    t = _sort_table(["zeytin", "şeker", "sarı", "ılık", "irin", "çene", "cilt", "ödem", "omuz", "ürün", "uç", "ğ", "Girdap", "İlaç", "Işık"])
    _click_header(t, 0)
    t.size_box.setCurrentIndex(t.size_box.findData(25))
    assert _column_text(t) == ["cilt", "çene", "Girdap", "ğ", "ılık", "Işık", "İlaç", "irin", "omuz", "ödem", "sarı", "şeker", "uç", "ürün", "zeytin"]


def test_sort_covers_all_pages_not_only_current_one(qapp):
    words = [f"t{i:02d}" for i in range(30, 0, -1)]
    t = _sort_table(words)
    t.set_page(3)
    _click_header(t, 0)
    assert t.page == 1 and _column_text(t)[0] == "t01"
    t.set_page(3)
    assert _column_text(t)[-1] == "t30"


def test_sort_uses_column_key_for_numbers(qapp):
    t = DataTable([Column("Adet", lambda r: str(r), sort_key=lambda r: r)], search_text=str)
    t.set_rows([10, 9, 100])
    _click_header(t, 0)
    assert _column_text(t) == ["9", "10", "100"]


def test_sort_stays_while_searching_and_paging(qapp):
    t = _sort_table(["bab", "aba", "cab", "dede"])
    _click_header(t, 0)
    t.search.setText("ab")
    assert _column_text(t) == ["aba", "bab", "cab"]


def test_action_column_header_does_not_sort(qapp):
    t = _sort_table(["beta", "alfa"])
    _click_header(t, 2)
    assert t.sort_column is None and _column_text(t) == ["beta", "alfa"]


def test_row_action_gets_correct_row_after_sorting(qapp):
    removed = []
    t = DataTable([Column("Terim", lambda r: r["t"])], search_text=lambda r: r["t"],
                  actions=[RowAction("trash", "Sil", removed.append)])
    b, a = {"t": "b"}, {"t": "a"}
    t.set_rows([b, a])
    _click_header(t, 0)
    t.table.cellWidget(0, 1).findChild(QPushButton).click()
    assert removed == [a]


def test_page_of_follows_sorting(qapp):
    rows = [{"t": f"t{i:02d}", "n": 0} for i in range(25)]
    t = DataTable([Column("Terim", lambda r: r["t"])], search_text=lambda r: r["t"])
    t.set_rows(rows)
    assert t.page_of(rows[24]) == 3
    _click_header(t, 0)
    _click_header(t, 0)
    assert t.page_of(rows[24]) == 1
