"""Ayarlar › Sözlük düzenleyicisi.

Solda terimler (ara / yeni / sil), sağda seçili terimin doğru yazımı ve söylenişleri: her söyleniş ayrı satır,
"Ekli hâlleri de" kutusu dosyadaki "kök*" yazımının karşılığıdır (kullanıcı * yazmak zorunda kalmaz).
Altta "Dene" kutusu sözlüğün bir cümleye etkisini anında gösterir.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCompleter, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .medical.postprocess import COMMAND_PHRASES, tr_lower
from .user_dict import Entry, join_root, parse_variants, preview, split_root

_HINT = ("<b>Ekli hâlleri de</b> işaretliyse <i>protezyonu, protezyonlar, protezyonda</i> gibi hâller de "
         "düzeltilir, ek korunur. Birden çok söylenişi virgülle ayırıp tek seferde de ekleyebilirsiniz.")


class LexiconEditor(QWidget):
    def __init__(self, entries: list[Entry], parent=None):
        super().__init__(parent)
        self._entries: list[Entry] = []
        self._current = -1
        self._loading = False

        # --- sol: terim listesi
        self.search = QLineEdit()
        self.search.setPlaceholderText("Terim ya da söyleniş ara…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.term_list = QListWidget()
        self.term_list.currentRowChanged.connect(self._load_current)
        add_term = QPushButton("+ Yeni terim")
        # lambda değil metot: lambda self'i tutar, widget kapanışta QApplication'dan sonra silinip çöker
        add_term.clicked.connect(self._new_term_clicked)
        del_term = QPushButton("Terimi sil")
        del_term.clicked.connect(self.remove_current_term)
        left = QVBoxLayout()
        left.addWidget(self.search)
        left.addWidget(self.term_list, 1)
        row = QHBoxLayout()
        row.addWidget(add_term)
        row.addWidget(del_term)
        left.addLayout(row)

        # --- sağ: seçili terim
        self.detail = QWidget()
        d = QVBoxLayout(self.detail)
        d.setContentsMargins(0, 0, 0, 0)
        d.addWidget(QLabel("<b>Doğru yazım</b> — metinde böyle yazılsın:"))
        self.term_edit = QLineEdit()
        self.term_edit.setPlaceholderText("örn. protrüzyon, BT, Doppler — ya da bir komut: alt satıra geç")
        completer = QCompleter(list(COMMAND_PHRASES), self.term_edit)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.term_edit.setCompleter(completer)
        self.term_edit.textChanged.connect(self._term_changed)
        d.addWidget(self.term_edit)
        d.addWidget(QLabel("<b>Söylenişler</b> — model bu terimi yanlış yazınca nasıl yazıyor? Her satır bir "
                           "söyleniş:"))
        self.variant_table = QTableWidget(0, 2)
        self.variant_table.setHorizontalHeaderLabels(["Model böyle yazıyor", "Ekli hâlleri de"])
        hh = self.variant_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.variant_table.verticalHeader().setVisible(False)
        self.variant_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.variant_table.itemChanged.connect(self._variants_changed)
        d.addWidget(self.variant_table, 1)
        row = QHBoxLayout()
        self.variant_input = QLineEdit()
        self.variant_input.setPlaceholderText("Yeni söyleniş yazıp Enter'a basın (örn. protezyon)")
        self.variant_input.returnPressed.connect(self.add_variants_from_input)
        add_var = QPushButton("Ekle")
        add_var.clicked.connect(self.add_variants_from_input)
        del_var = QPushButton("Seçiliyi sil")
        del_var.clicked.connect(self.remove_selected_variants)
        row.addWidget(self.variant_input, 1)
        row.addWidget(add_var)
        row.addWidget(del_var)
        d.addLayout(row)
        hint = QLabel(_HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        d.addWidget(hint)

        top = QHBoxLayout()
        top.addLayout(left, 2)
        top.addWidget(self.detail, 3)

        # --- alt: deneme
        self.try_input = QLineEdit()
        self.try_input.setPlaceholderText("Modelin yazacağı bir cümle yazın — örn. bete çekildi, protezyonu izlendi")
        self.try_input.setClearButtonEnabled(True)
        self.try_input.textChanged.connect(self._refresh_try)
        self.try_output = QLabel()
        self.try_output.setTextFormat(Qt.PlainText)
        self.try_output.setWordWrap(True)
        self.try_output.setTextInteractionFlags(Qt.TextSelectableByMouse)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("<b>Dene:</b>"))
        trow.addWidget(self.try_input, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top, 1)
        lay.addLayout(trow)
        lay.addWidget(self.try_output)

        self.set_entries(entries)

    # ------------------------------------------------------------ veri
    def set_entries(self, entries: list[Entry]) -> None:
        self._entries = [Entry(e.term, list(e.variants)) for e in entries]
        self._rebuild_list(0 if self._entries else -1)

    def entries(self) -> list[Entry]:
        """Kaydedilecek sözlük: boş terim/söyleniş atılır, aynı terim tek kayıtta birleşir."""
        out: list[Entry] = []
        index: dict[str, Entry] = {}
        for e in self._entries:
            term = " ".join(e.term.split())
            if not term:
                continue
            variants = parse_variants(", ".join(v for v in e.variants if v.strip()), term)
            if term in index:
                index[term].variants += [v for v in variants if v not in index[term].variants]
            else:
                index[term] = Entry(term, variants)
                out.append(index[term])
        return out

    # ------------------------------------------------------------ terimler
    def add_term(self, term: str = "") -> None:
        term = " ".join(term.split())
        for i, e in enumerate(self._entries):
            if term and " ".join(e.term.split()) == term:  # zaten var: onu aç
                self.search.clear()
                self.select_term(i)
                return
        self._entries.append(Entry(term, []))
        self.search.clear()
        self._rebuild_list(len(self._entries) - 1)
        (self.variant_input if term else self.term_edit).setFocus()

    def _new_term_clicked(self) -> None:  # clicked(bool) terim yerine geçmesin
        self.add_term()

    def remove_current_term(self) -> None:
        if self._current < 0:
            return
        del self._entries[self._current]
        self._rebuild_list(min(self._current, len(self._entries) - 1))

    def select_term(self, i: int) -> None:
        self.term_list.setCurrentRow(i)

    def _rebuild_list(self, select: int) -> None:
        self.term_list.blockSignals(True)
        self.term_list.clear()
        for i, e in enumerate(self._entries):
            item = QListWidgetItem(self._label(e))
            item.setData(Qt.UserRole, i)
            self.term_list.addItem(item)
        self.term_list.blockSignals(False)
        self._filter(self.search.text())
        self.term_list.setCurrentRow(select)
        self._load_current(select)

    @staticmethod
    def _label(e: Entry) -> str:
        term = " ".join(e.term.split()) or "(yeni terim)"
        shown = [split_root(v)[0] for v in e.variants if v.strip()]
        return f"{term}   ← {', '.join(shown)}" if shown else term

    def _filter(self, text: str) -> None:
        q = tr_lower(text.strip())
        for i in range(self.term_list.count()):
            item = self.term_list.item(i)
            e = self._entries[item.data(Qt.UserRole)]
            hay = tr_lower(" ".join([e.term, *e.variants]))
            item.setHidden(bool(q) and q not in hay)

    def _load_current(self, row: int) -> None:
        self._current = row if 0 <= row < len(self._entries) else -1
        self._loading = True
        try:
            e = self._entries[self._current] if self._current >= 0 else Entry("", [])
            self.term_edit.setText(e.term)
            self._fill_variants(e.variants)
            self.variant_input.clear()
        finally:
            self._loading = False
        self.detail.setEnabled(self._current >= 0)
        self._refresh_try()

    def _term_changed(self, text: str) -> None:
        if self._loading or self._current < 0:
            return
        self._entries[self._current].term = text
        self._update_label()
        self._refresh_try()

    def _update_label(self) -> None:
        item = self.term_list.item(self._current)
        if item is not None:
            item.setText(self._label(self._entries[self._current]))

    # ------------------------------------------------------------ söylenişler
    def _fill_variants(self, variants: list[str]) -> None:
        t = self.variant_table
        t.blockSignals(True)
        t.setRowCount(0)
        for v in variants:
            text, roots = split_root(v)
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, QTableWidgetItem(text))
            box = QTableWidgetItem()
            box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            box.setCheckState(Qt.Checked if roots else Qt.Unchecked)
            t.setItem(r, 1, box)
        t.blockSignals(False)

    def _variants_changed(self, _item=None) -> None:
        if self._loading or self._current < 0:
            return
        t = self.variant_table
        self._entries[self._current].variants = [
            join_root((t.item(r, 0) or QTableWidgetItem()).text(),
                      (t.item(r, 1) or QTableWidgetItem()).checkState() == Qt.Checked)
            for r in range(t.rowCount())]
        self._update_label()
        self._refresh_try()

    def add_variants_from_input(self) -> None:
        if self._current < 0:
            return
        e = self._entries[self._current]
        for v in parse_variants(self.variant_input.text(), e.term):
            text, roots = split_root(v)
            if not text:
                continue
            same = [i for i, x in enumerate(e.variants) if tr_lower(split_root(x)[0]) == tr_lower(text)]
            if same:  # aynı söyleniş: yalnızca "ekli hâlleri de" eklenebilir
                if roots:
                    e.variants[same[0]] = join_root(text, True)
            else:
                e.variants.append(join_root(text, roots))
        self._fill_variants(e.variants)
        self.variant_input.clear()
        self._update_label()
        self._refresh_try()

    def remove_selected_variants(self) -> None:
        if self._current < 0:
            return
        rows = {i.row() for i in self.variant_table.selectedIndexes()}
        e = self._entries[self._current]
        e.variants = [v for i, v in enumerate(e.variants) if i not in rows]
        self._fill_variants(e.variants)
        self._update_label()
        self._refresh_try()

    # ------------------------------------------------------------ dene
    def _refresh_try(self, *_args) -> None:
        text = self.try_input.text().strip()
        self.try_output.setText(f"→ {preview(self.entries(), text)}" if text else "")
