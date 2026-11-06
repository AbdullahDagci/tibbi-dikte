"""Sözlük ekranı: sayfalı tablo, terim düzenleme penceresi, deneme kutusu ve kaydetme."""
from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCompleter, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import user_dict
from .medical.postprocess import COMMAND_PHRASES, tr_lower
from .ui.data_table import Column, DataTable, RowAction
from .ui import widgets
from .user_dict import Entry, join_root, parse_variants, preview, split_root

_SUFFIX_TIP = ("İşaretliyse protezyonu, protezyonlar, protezyonda gibi hâller de düzeltilir, ek korunur. "
               "Birden çok söylenişi virgülle ayırıp tek seferde ekleyebilirsiniz.")
_LEXICON_TIP = ("Sözlük, modelin yanlış yazdığı kelimeleri doğru yazıma çevirir. Söyleniş olmadan eklenen terimin "
                "büyük/küçük harfi korunur. Söyleniş bir sesli komuta da bağlanabilir (alt sağa geç → alt satıra geç).")


class _VariantInput(QLineEdit):
    """Enter yalnızca söyleniş ekler; olay pencereye geçip varsayılan düğmeyi tetiklemez."""

    def keyPressEvent(self, event) -> None:
        super().keyPressEvent(event)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()


class TermDialog(QDialog):
    """Bir terimin doğru yazımı ve söylenişleri; verilen kaydı değiştirmez, sonucu `entry()` ile döner."""

    def __init__(self, entry: Entry, title: str = "Terimi düzenle", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(560, 480)
        self._variants = list(entry.variants)

        self.term_edit = QLineEdit(entry.term)
        self.term_edit.setPlaceholderText("örn. protrüzyon, BT, Doppler")
        completer = QCompleter(list(COMMAND_PHRASES), self.term_edit)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.term_edit.setCompleter(completer)
        self.term_edit.textChanged.connect(self._term_changed)

        self.variant_table = QTableWidget(0, 2)
        self.variant_table.setHorizontalHeaderLabels(["Model böyle yazıyor", "Ekli hâlleri de"])
        header = self.variant_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.variant_table.verticalHeader().setVisible(False)
        self.variant_table.setAlternatingRowColors(True)
        self.variant_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.variant_table.itemChanged.connect(self._table_changed)

        self.variant_input = _VariantInput()
        self.variant_input.setPlaceholderText("Yeni söyleniş yazıp Enter'a basın")
        self.variant_input.returnPressed.connect(self.add_variants_from_input)
        add = widgets.button("Ekle", "plus", "primary")
        add.setAutoDefault(False)
        add.clicked.connect(self.add_variants_from_input)
        remove = widgets.button("Seçiliyi sil", "trash", "danger")
        remove.setAutoDefault(False)
        remove.clicked.connect(self.remove_selected_variants)
        row = QHBoxLayout()
        row.addWidget(self.variant_input, 1)
        row.addWidget(add)
        row.addWidget(remove)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save = self.buttons.button(QDialogButtonBox.Save)
        save.setText("Uygula")
        widgets.set_variant(save, "success", icon="check")
        cancel = self.buttons.button(QDialogButtonBox.Cancel)
        cancel.setText("Vazgeç")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        label_row = QHBoxLayout()
        heading = QLabel("Söylenişler")
        heading.setObjectName("fieldLabel")
        label_row.addWidget(heading)
        label_row.addWidget(widgets.InfoTip(_SUFFIX_TIP))
        label_row.addStretch()
        term_label = QLabel("Doğru yazım")
        term_label.setObjectName("fieldLabel")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)
        lay.addWidget(term_label)
        lay.addWidget(self.term_edit)
        lay.addSpacing(6)
        lay.addLayout(label_row)
        lay.addWidget(self.variant_table, 1)
        lay.addLayout(row)
        lay.addSpacing(6)
        lay.addWidget(self.buttons)

        self._fill_table()
        self._term_changed(entry.term)

    def entry(self) -> Entry:
        return Entry(" ".join(self.term_edit.text().split()), [v for v in self._variants if split_root(v)[0].strip()])

    def _term_changed(self, text: str) -> None:
        self.buttons.button(QDialogButtonBox.Save).setEnabled(bool(text.strip()))

    def _fill_table(self) -> None:
        t = self.variant_table
        t.blockSignals(True)
        t.setRowCount(0)
        for v in self._variants:
            text, roots = split_root(v)
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, QTableWidgetItem(text))
            box = QTableWidgetItem()
            box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            box.setCheckState(Qt.Checked if roots else Qt.Unchecked)
            t.setItem(r, 1, box)
        t.blockSignals(False)

    def _table_changed(self, _item=None) -> None:
        t = self.variant_table
        self._variants = [join_root((t.item(r, 0) or QTableWidgetItem()).text(),
                                    (t.item(r, 1) or QTableWidgetItem()).checkState() == Qt.Checked)
                          for r in range(t.rowCount())]

    def add_variants_from_input(self) -> None:
        for v in parse_variants(self.variant_input.text(), self.term_edit.text()):
            text, roots = split_root(v)
            if not text:
                continue
            same = [i for i, x in enumerate(self._variants) if tr_lower(split_root(x)[0]) == tr_lower(text)]
            if same:  # aynı söyleniş: yalnızca "ekli hâlleri de" eklenebilir
                if roots:
                    self._variants[same[0]] = join_root(split_root(self._variants[same[0]])[0], True)
            else:
                self._variants.append(join_root(text, roots))
        self._fill_table()
        self.variant_input.clear()

    def remove_selected_variants(self) -> None:
        rows = {i.row() for i in self.variant_table.selectedIndexes()}
        self._variants = [v for i, v in enumerate(self._variants) if i not in rows]
        self._fill_table()


def _normalized(entries: list[Entry]) -> list[Entry]:
    """Kaydedilecek sözlük: boş terim/söyleniş atılır, aynı terim tek kayıtta birleşir."""
    out: list[Entry] = []
    index: dict[str, Entry] = {}
    for e in entries:
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


class LexiconEditor(QWidget):
    """Terim tablosu ve deneme kutusu; dosyaya yazmaz, `entries()` güncel sözlüğü verir."""

    dirty_changed = Signal(bool)
    edited = Signal()  # kullanıcı bir kaydı ekledi, değiştirdi ya da sildi

    def __init__(self, entries: list[Entry], parent=None):
        super().__init__(parent)
        self._entries: list[Entry] = []
        self._saved: list[Entry] = []
        self._dirty = False

        self.table = DataTable(
            [Column("Doğru yazım", self._term_text, bold=True), Column("Söylenişler", self._variants_text, stretch=True),
             Column("Ekli hâller", self._suffix_text)],
            search_text=self._search_text, normalize=tr_lower,
            actions=[RowAction("pencil", "Düzenle", self.edit_entry),
                     RowAction("trash", "Sil", self.remove_entry, "ghost-danger")],
            search_placeholder="Terim ya da söyleniş ara…", empty_text="Sözlükte kayıt yok")
        self.table.row_activated.connect(self.edit_entry)
        self.search = self.table.search

        self.try_input = QLineEdit()
        self.try_input.setPlaceholderText("Modelin yazacağı bir cümle yazın")
        self.try_input.setClearButtonEnabled(True)
        self.try_input.textChanged.connect(self._refresh_try)
        self.try_output = QLabel()
        self.try_output.setTextFormat(Qt.PlainText)
        self.try_output.setWordWrap(True)
        self.try_output.setTextInteractionFlags(Qt.TextSelectableByMouse)
        tryer = widgets.Collapsible("Sözlüğü dene", "wand", expanded=False)
        tryer.body.addWidget(self.try_input)
        tryer.body.addWidget(self.try_output)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self.table, 1)
        lay.addWidget(tryer)
        self.set_entries(entries)

    # ------------------------------------------------------------ veri
    def set_entries(self, entries: list[Entry], *, keep_dirty_base: bool = False) -> None:
        """Tabloyu verilen sözlükle doldurur. keep_dirty_base: kayıtlı hâli değiştirmez (içe aktarma)."""
        self._entries = [Entry(e.term, list(e.variants)) for e in entries]
        if not keep_dirty_base:
            self._saved = _normalized(self._entries)
        self.table.set_rows(self._entries)
        self._changed()

    def entries(self) -> list[Entry]:
        return _normalized(self._entries)

    def is_dirty(self) -> bool:
        return self._dirty

    def saved_entries(self) -> list[Entry]:
        return [Entry(e.term, list(e.variants)) for e in self._saved]

    def mark_clean(self) -> None:
        self._saved = self.entries()
        self._changed()

    def set_saved_base(self, entries: list[Entry]) -> None:
        self._saved = _normalized(entries)
        self._changed()

    def _changed(self) -> None:
        dirty = self.entries() != self._saved
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)
        self._refresh_try()

    # ------------------------------------------------------------ işlemler
    def _ask_entry(self, entry: Entry, title: str) -> Entry | None:
        dialog = TermDialog(entry, title, self)
        result = dialog.entry() if dialog.exec() == QDialog.Accepted else None
        dialog.deleteLater()
        return result

    def new_entry(self) -> None:
        result = self._ask_entry(Entry("", []), "Yeni terim")
        if result is not None:
            self.add_entry(result)

    def edit_entry(self, entry: Entry) -> None:
        result = self._ask_entry(Entry(entry.term, list(entry.variants)), "Terimi düzenle")
        if result is not None:
            self.update_entry(entry, result)

    def add_entry(self, entry: Entry) -> None:
        """Aynı terim varsa söylenişleri ona eklenir; yeni kayıt görünür olacak şekilde son sayfaya gidilir."""
        target = self._find(entry.term)
        if target is None:
            target = Entry(entry.term, list(entry.variants))
            self._entries.append(target)
        else:
            self._merge_into(target, entry.variants)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.table.set_rows(self._entries)
        self.table.set_page(self.table.page_of(target))
        self._changed()
        self.edited.emit()

    def update_entry(self, old: Entry, new: Entry) -> None:
        other = self._find(new.term)
        if other is not None and other is not old:  # başka bir terimin adına çevrildi: tek kayıtta birleşir
            self._merge_into(other, new.variants)
            self._remove_identity(old)
        else:
            old.term, old.variants = new.term, list(new.variants)
        self.table.set_rows(self._entries, keep_page=True)
        self._changed()
        self.edited.emit()

    def remove_entry(self, entry: Entry) -> None:
        self._remove_identity(entry)
        self.table.set_rows(self._entries, keep_page=True)
        self._changed()
        self.edited.emit()

    def _find(self, term: str) -> Entry | None:
        wanted = " ".join(term.split())
        return next((e for e in self._entries if " ".join(e.term.split()) == wanted), None) if wanted else None

    @staticmethod
    def _merge_into(target: Entry, variants: list[str]) -> None:
        target.variants += [v for v in variants if v not in target.variants]

    def _remove_identity(self, entry: Entry) -> None:
        self._entries = [e for e in self._entries if e is not entry]

    # ------------------------------------------------------------ tablo metinleri
    @staticmethod
    def _term_text(e: Entry) -> str:
        return e.term

    @staticmethod
    def _variants_text(e: Entry) -> str:
        return ", ".join(split_root(v)[0] for v in e.variants if v.strip()) or "—"

    @staticmethod
    def _suffix_text(e: Entry) -> str:
        if not e.variants:
            return "—"
        return "Evet" if any(split_root(v)[1] for v in e.variants) else "Hayır"

    @staticmethod
    def _search_text(e: Entry) -> str:
        return " ".join([e.term, *e.variants])

    # ------------------------------------------------------------ dene
    def _refresh_try(self, *_args) -> None:
        text = self.try_input.text().strip()
        self.try_output.setText(f"→ {preview(self.entries(), text)}" if text else "")


class LexiconPage(QWidget):
    """Sözlük sayfası: tablo + yeni terim, içe/dışa aktar. Her değişiklik anında kaydedilir ve dikteye geçer."""

    saved = Signal()

    def __init__(self, lexicon_path: Path, corrections_path: Path, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.lexicon_path, self.corrections_path = Path(lexicon_path), Path(corrections_path)
        self.editor = LexiconEditor(user_dict.load(self.lexicon_path, self.corrections_path))
        self.editor.dirty_changed.connect(self._dirty_changed)
        self.editor.edited.connect(self._edited)

        tip = widgets.InfoTip(_LEXICON_TIP)
        self.dirty_badge = widgets.Badge("Kaydedilemedi", "danger")
        self.dirty_badge.setToolTip("Aynı söyleniş birden çok terime bağlı. Düzeltince otomatik kaydedilir.")
        self.dirty_badge.setVisible(False)
        add = widgets.button("Yeni terim", "plus", "primary")
        add.clicked.connect(self.editor.new_entry)
        imp = widgets.button("İçe aktar", "upload", "light")
        imp.clicked.connect(self._import)
        exp = widgets.button("Dışa aktar", "download", "light")
        exp.clicked.connect(self._export)
        for w in (tip, self.dirty_badge, add, imp, exp):
            self.editor.table.add_action(w)

        card = widgets.Card()
        card.body.addWidget(self.editor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(card, 1)

    def _dirty_changed(self, dirty: bool) -> None:
        self.dirty_badge.setVisible(dirty)

    def _edited(self) -> None:
        self.save()

    def showEvent(self, event) -> None:
        """Dosya elle düzenlendiyse sayfa açılınca görünür; küçültüp geri açmak dokunmaz."""
        super().showEvent(event)
        if not event.spontaneous():
            self.reload_from_disk()

    def save(self) -> bool:
        self.reload_from_disk()  # sayfa açıkken dosyada yapılan değişiklik üzerine yazılmasın
        entries = self.editor.entries()
        clash = user_dict.conflicts(entries)
        if clash:
            lines = "\n".join(f"• “{v}” → {', '.join(t)}" for v, t in clash[:10])
            QMessageBox.warning(self, "Sözlük", "Aynı söyleniş birden çok terime bağlı; birini seçin:\n" + lines)
            return False
        user_dict.save(entries, self.lexicon_path, self.corrections_path)
        self.editor.mark_clean()
        self.saved.emit()
        return True

    def reload_from_disk(self) -> None:
        """Dosya dışarıdan değişti (dikte ekranından söyleniş eklendi): kaydedilmemiş düzenlemeler korunur."""
        disk = user_dict.load(self.lexicon_path, self.corrections_path)
        if _normalized(disk) == self.editor.saved_entries():
            return  # dosya değişmedi: tablodaki sayfa ve arama korunur
        if self.editor.is_dirty():
            rebased = user_dict.rebase(self.editor.saved_entries(), disk, self.editor.entries())
            self.editor.set_entries(rebased, keep_dirty_base=True)
            self.editor.set_saved_base(disk)
        else:
            self.editor.set_entries(disk)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Sözlüğü içe aktar", "",
                                              "Sözlük dosyaları (*.csv *.tsv *.txt);;Tüm dosyalar (*.*)")
        if not path:
            return
        try:
            incoming = user_dict.import_file(Path(path))
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            QMessageBox.warning(self, "İçe aktar", f"Dosya okunamadı:\n{e}")
            return
        merged, nt, nv = user_dict.merge(self.editor.entries(), incoming)
        self.editor.set_entries(merged, keep_dirty_base=True)
        if self.save():
            QMessageBox.information(self, "İçe aktar", f"{nt} yeni terim, {nv} yeni söyleniş eklendi.")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Sözlüğü dışa aktar", "tibbi_dikte_sozluk.csv",
                                              "CSV (Excel) (*.csv)")
        if not path:
            return
        entries = self.editor.entries()
        user_dict.export_file(entries, Path(path))
        QMessageBox.information(self, "Dışa aktar", f"{len(entries)} terim kaydedildi:\n{path}")
