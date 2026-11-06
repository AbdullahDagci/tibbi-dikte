"""Sayfalı ve aramalı tablo: üstte arama ve işlem düğmeleri, altta sayfa boyutu, kayıt özeti ve sayfa numaraları."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import theme
from .icons import icon as make_icon
from .widgets import icon_button

PAGE_SIZES = (10, 25, 50)
_TURKISH_RANK = {letter: i for i, letter in enumerate("abcçdefgğhıijklmnoöprsştuüvyz")}


def text_sort_key(text: str) -> tuple[int, ...]:
    """Türkçe alfabe sırası (c, ç, d ... ı, i ... s, ş, t). Rakam ve işaretler harflerden önce, diğer harfler sonra."""
    def rank(ch: str) -> int:
        if ch in _TURKISH_RANK:
            return _TURKISH_RANK[ch]
        return 1000 + ord(ch) if ch.isalpha() else ord(ch) - 1_000_000
    return tuple(rank(ch) for ch in text)


@dataclass(frozen=True)
class PageInfo:
    number: int
    pages: int
    start: int
    end: int
    total: int


def paginate(total: int, page: int, size: int) -> PageInfo:
    """Sayfa numarası geçerli aralığa çekilir; start/end listedeki dilimdir (end hariç)."""
    pages = max(1, (total + size - 1) // size)
    number = min(max(1, page), pages)
    start = (number - 1) * size
    return PageInfo(number, pages, start, min(start + size, total), total)


def page_numbers(current: int, pages: int, around: int = 2) -> list[int | None]:
    """Gösterilecek sayfa numaraları; None üç nokta demektir. Tek sayfalık boşluk için üç nokta konmaz."""
    keep = {1, pages} | {n for n in range(current - around, current + around + 1) if 1 <= n <= pages}
    out: list[int | None] = []
    last = 0
    for n in sorted(keep):
        if n - last == 2:
            out.append(n - 1)
        elif n - last > 2:
            out.append(None)
        out.append(n)
        last = n
    return out


@dataclass(frozen=True)
class Column:
    title: str
    text: Callable[[Any], str]
    stretch: bool = False
    bold: bool = False
    sort_key: Callable[[Any], Any] | None = None  # verilmezse metne göre Türkçe alfabe sırası
    color: Callable[[Any], str | None] | None = None  # verilirse yazı rengi


@dataclass(frozen=True)
class RowAction:
    icon: str
    tooltip: str
    callback: Callable[[Any], None]
    variant: str = "ghost"


class DataTable(QWidget):
    row_activated = Signal(object)

    def __init__(self, columns: list[Column], search_text: Callable[[Any], str],
                 normalize: Callable[[str], str] = str.casefold, actions: list[RowAction] | None = None,
                 search_placeholder: str = "Ara…", empty_text: str = "Kayıt bulunamadı", parent=None):
        super().__init__(parent)
        self._columns, self._actions = columns, actions or []
        self._search_text, self._normalize = search_text, normalize
        self._rows: list[Any] = []
        self._visible: list[Any] = []
        self.page = 1
        self.sort_column: int | None = None
        self.sort_descending = False

        self.search = QLineEdit()
        self.search.setPlaceholderText(search_placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.addAction(make_icon("search", theme.MUTED), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._search_changed)
        self.toolbar = QHBoxLayout()
        self.toolbar.setSpacing(8)
        self.toolbar.addWidget(self.search, 1)

        count = len(columns) + (1 if self._actions else 0)
        self.table = QTableWidget(0, count)
        self.table.setHorizontalHeaderLabels([c.title for c in columns] + (["İşlem"] if self._actions else []))
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(True)
        self.table.setGridStyle(Qt.SolidLine)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.cellDoubleClicked.connect(self._double_clicked)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setHighlightSections(False)
        header.setSectionsClickable(True)
        header.setCursor(Qt.PointingHandCursor)
        header.sectionClicked.connect(self._header_clicked)
        for i, c in enumerate(columns):
            header.setSectionResizeMode(i, QHeaderView.Stretch if c.stretch else QHeaderView.ResizeToContents)
        if self._actions:
            header.setSectionResizeMode(len(columns), QHeaderView.ResizeToContents)
        self.empty = QLabel(empty_text)
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.body = QStackedWidget()
        self.body.addWidget(self.table)
        self.body.addWidget(self.empty)

        self.size_box = QComboBox()
        for size in PAGE_SIZES:
            self.size_box.addItem(str(size), size)
        self.size_box.currentIndexChanged.connect(self._size_changed)
        self.info = QLabel()
        self.info.setObjectName("muted")
        self.pager = QWidget()
        self._pager_row = QHBoxLayout(self.pager)
        self._pager_row.setContentsMargins(0, 0, 0, 0)
        self._pager_row.setSpacing(4)
        self.btn_prev = self._pager_arrow("chevron-left", "Önceki sayfa")
        self.btn_prev.clicked.connect(self._previous)
        self.btn_next = self._pager_arrow("chevron-right", "Sonraki sayfa")
        self.btn_next.clicked.connect(self._next)
        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addWidget(self.size_box)
        footer.addWidget(self.info)
        footer.addStretch()
        footer.addWidget(self.pager)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addLayout(self.toolbar)
        lay.addWidget(self.body, 1)
        lay.addLayout(footer)
        self.refresh()

    # ------------------------------------------------------------ dışarıya açık
    def add_action(self, widget: QWidget) -> None:
        self.toolbar.addWidget(widget)

    def set_rows(self, rows: list[Any], keep_page: bool = False) -> None:
        self._rows = list(rows)
        if not keep_page:
            self.page = 1
        self.refresh()

    def set_page(self, page: int) -> None:
        self.page = page
        self.refresh()

    def page_size(self) -> int:
        return self.size_box.currentData() or PAGE_SIZES[0]

    def filtered_rows(self) -> list[Any]:
        query = self._normalize(self.search.text().strip())
        rows = list(self._rows) if not query else [
            r for r in self._rows if query in self._normalize(self._search_text(r))]
        if self.sort_column is not None:
            rows.sort(key=self._sort_value, reverse=self.sort_descending)
        return rows

    def page_of(self, row: Any) -> int:
        """Satırın göründüğü sayfa (arama ve sıralama dahil); yoksa 1."""
        for i, candidate in enumerate(self.filtered_rows()):
            if candidate is row:
                return i // self.page_size() + 1
        return 1

    def visible_rows(self) -> list[Any]:
        return list(self._visible)

    def refresh(self) -> None:
        rows = self.filtered_rows()
        info = paginate(len(rows), self.page, self.page_size())
        self.page = info.number
        self._visible = rows[info.start:info.end]
        self._fill_table()
        self.body.setCurrentWidget(self.table if self._visible else self.empty)
        self.info.setText(f"{info.start + 1}-{info.end} / {info.total} kayıt" if info.total else "0 kayıt")
        self._fill_pager(info)

    # ------------------------------------------------------------ iç işler
    def _sort_value(self, row: Any) -> Any:
        column = self._columns[self.sort_column]
        if column.sort_key is not None:
            return column.sort_key(row)
        return text_sort_key(self._normalize(column.text(row)))

    def _header_clicked(self, index: int) -> None:
        if index >= len(self._columns):
            return  # işlem sütunu sıralanmaz
        self.sort_descending = index == self.sort_column and not self.sort_descending
        self.sort_column = index
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(index, Qt.DescendingOrder if self.sort_descending else Qt.AscendingOrder)
        self.set_page(1)

    def _fill_table(self) -> None:
        t = self.table
        t.clearContents()
        t.setRowCount(len(self._visible))
        for r, row in enumerate(self._visible):
            for c, column in enumerate(self._columns):
                item = QTableWidgetItem(column.text(row))
                if column.bold:
                    font = QFont()  # yalnızca kalınlık; boyut ve yazı tipi tablonunkinden gelir
                    font.setBold(True)
                    item.setFont(font)
                color = column.color(row) if column.color else None
                if color:
                    item.setForeground(QColor(color))
                t.setItem(r, c, item)
            if self._actions:
                t.setCellWidget(r, len(self._columns), self._action_cell(r))

    def _action_cell(self, row_index: int) -> QWidget:
        cell = QWidget()
        h = QHBoxLayout(cell)
        h.setContentsMargins(6, 0, 6, 0)
        h.setSpacing(2)
        for i, action in enumerate(self._actions):
            btn = icon_button(action.icon, action.tooltip, action.variant)
            btn.setProperty("row_index", row_index)
            btn.setProperty("action_index", i)
            btn.clicked.connect(self._action_clicked)
            h.addWidget(btn)
        return cell

    def _action_clicked(self) -> None:
        # Kapanış güvenliği: bağlantılar lambda değil metot; hangi satır olduğu düğmenin özelliğinden okunur
        btn = self.sender()
        self._actions[btn.property("action_index")].callback(self._visible[btn.property("row_index")])

    def _double_clicked(self, row: int, _column: int) -> None:
        self.row_activated.emit(self._visible[row])

    def _pager_arrow(self, name: str, tooltip: str) -> QPushButton:
        btn = QPushButton()
        btn.setIcon(make_icon(name, theme.MUTED))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setProperty("pager", True)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _fill_pager(self, info: PageInfo) -> None:
        while self._pager_row.count():
            widget = self._pager_row.takeAt(0).widget()
            if widget is not None and widget not in (self.btn_prev, self.btn_next):
                widget.setParent(None)
                widget.deleteLater()
        self._pager_row.addWidget(self.btn_prev)
        for n in page_numbers(info.number, info.pages):
            self._pager_row.addWidget(self._number_widget(n, info.number))
        self._pager_row.addWidget(self.btn_next)
        self.btn_prev.setEnabled(info.number > 1)
        self.btn_next.setEnabled(info.number < info.pages)

    def _number_widget(self, number: int | None, current: int) -> QWidget:
        if number is None:
            dots = QLabel("…")
            dots.setObjectName("muted")
            return dots
        btn = QPushButton(str(number))
        btn.setProperty("pager", True)
        btn.setProperty("page_number", number)
        btn.setCheckable(True)
        btn.setChecked(number == current)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._number_clicked)
        return btn

    def _number_clicked(self) -> None:
        self.set_page(self.sender().property("page_number"))

    def _previous(self) -> None:
        self.set_page(self.page - 1)

    def _next(self) -> None:
        self.set_page(self.page + 1)

    def _search_changed(self, _text: str) -> None:
        self.set_page(1)

    def _size_changed(self, _index: int) -> None:
        self.set_page(1)
