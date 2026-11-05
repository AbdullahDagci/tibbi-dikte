"""Test ekranındaki dikte editörü.

Editör etkin pencereyken dikte metni klavye taklidi (SendInput) olmadan doğrudan editöre yazılır; böylece
hedef uygulamanın Backspace/Unicode işleyişinden bağımsız olarak tanıma + sonişleme + anlık düzeltme denenir.
Yanlış çıkan kelime seçilip sağ tıkla "Sözlüğe varyant olarak ekle…" ile doğru yazıma bağlanır.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from . import user_dict

_STRIP = " \t\n.,;:!?\"'’()"


class DictationEditor(QPlainTextEdit):
    add_variant_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Segoe UI", 12))
        self.setPlaceholderText("Buraya tıklayıp dikteyi başlatın; metin imlecin olduğu yere yazılır.")

    # -------------------------------------------- dikte çıktısı (yalnızca UI iş parçacığında)
    def insert_dictated(self, text: str) -> None:
        self.insertPlainText(text)
        self.ensureCursorVisible()

    def erase_dictated(self, n: int) -> None:
        c = self.textCursor()
        c.clearSelection()
        c.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, max(0, n))
        c.removeSelectedText()
        self.setTextCursor(c)

    # -------------------------------------------- klavye
    def keyPressEvent(self, e) -> None:
        # Ctrl+Alt+Space dikte kısayoludur; Windows'ta Ctrl+Alt = AltGr sayıldığı için editöre boşluk yazardı
        if e.key() == Qt.Key_Space and e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            e.ignore()
            return
        super().keyPressEvent(e)

    # -------------------------------------------- sözlüğe varyant ekleme
    def request_add_variant(self) -> None:
        """Seçimi kelimeye daraltır (baş/son boşluk ve noktalama hariç) ve sinyali yayar."""
        c = self.textCursor()
        text = c.selectedText()
        word = text.strip(_STRIP)
        if not word:
            return
        start = min(c.anchor(), c.position()) + (len(text) - len(text.lstrip(_STRIP)))
        c.setPosition(start)
        c.setPosition(start + len(word), QTextCursor.KeepAnchor)
        self.setTextCursor(c)
        self.add_variant_requested.emit(word)

    def replace_selection(self, text: str) -> None:
        self.textCursor().insertText(text)

    def contextMenuEvent(self, e) -> None:
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        act = menu.addAction("Sözlüğe varyant olarak ekle…")
        act.setEnabled(bool(self.textCursor().selectedText().strip(_STRIP)))
        act.triggered.connect(self.request_add_variant)
        menu.exec(e.globalPos())


class TextSink(QObject):
    """Dikte iş parçacığından editöre güvenli yazma: çağrılar sırayla UI iş parçacığında uygulanır."""
    _typed = Signal(str)
    _erased = Signal(int)

    def __init__(self, editor: DictationEditor):
        super().__init__()
        self._typed.connect(editor.insert_dictated)
        self._erased.connect(editor.erase_dictated)

    def type(self, text: str) -> None:
        if text:
            self._typed.emit(text)

    def erase(self, n: int) -> None:
        if n > 0:
            self._erased.emit(n)


class EditorPage(QWidget):
    """Canlı dikte sekmesi: başlat/durdur, editör, kopyala/kaydet/temizle."""

    def __init__(self, lexicon_path: Path, corrections_path: Path, hotkey_label: str,
                 on_toggle: Callable[[], None] | None = None,
                 on_dictionary_changed: Callable[[], None] | None = None, parent=None):
        super().__init__(parent)
        self.lexicon_path, self.corrections_path = lexicon_path, corrections_path
        self.on_toggle = on_toggle
        self.on_dictionary_changed = on_dictionary_changed
        self.hotkey_label = hotkey_label

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.btn = QPushButton()
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(lambda: self.on_toggle and self.on_toggle())
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        copy = QPushButton("Kopyala")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.editor.toPlainText()))
        save = QPushButton("Kaydet…")
        save.clicked.connect(self._save)
        clear = QPushButton("Temizle")
        clear.clicked.connect(lambda: self.editor.clear())
        row.addWidget(self.btn)
        row.addWidget(self.status, 1)
        for b in (copy, save, clear):
            row.addWidget(b)
        v.addLayout(row)

        self.editor = DictationEditor()
        self.editor.add_variant_requested.connect(self._add_variant)
        v.addWidget(self.editor, 1)
        hint = QLabel("Sesli komutlar: \"alt satıra geç\", \"satır başı\" (yeni satır) · \"paragraf başı\" "
                      "(boş satır bırakıp yeni paragraf) · \"yeni madde\" (•).  Yanlış çıkan kelimeyi seçip "
                      "sağ tıklayın › Sözlüğe varyant olarak ekle.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.sink = TextSink(self.editor)
        self.set_listening(False)

    def set_listening(self, on: bool) -> None:
        self.btn.setText("■  Dikteyi durdur" if on else "●  Dikteyi başlat")
        self.status.setText("Dinliyor… metin editöre yazılıyor." if on else
                            f"Kısayol: {self.hotkey_label} ya da Boşluk'u basılı tutun.")

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Metni kaydet", "rapor.txt", "Metin (*.txt)")
        if path:
            Path(path).write_text(self.editor.toPlainText(), encoding="utf-8")

    def _add_variant(self, variant: str) -> None:
        terms = [e.term for e in user_dict.load(self.lexicon_path, self.corrections_path)]
        term, ok = QInputDialog.getItem(
            self, "Sözlüğe varyant ekle",
            f"Model “{variant}” yazdı. Doğru yazımı nedir?\n(listeden seçin ya da yazın)",
            terms, -1, True)
        term = " ".join((term or "").split())
        if not ok or not term:
            return
        if term.casefold() == variant.casefold():
            QMessageBox.information(self, "Sözlük", "Varyant doğru yazımla aynı.")
            return
        moved = user_dict.add_variant(self.lexicon_path, self.corrections_path, variant, term)
        self.editor.replace_selection(term)
        note = f" (önceden “{', '.join(moved)}” terimine bağlıydı)" if moved else ""
        self.status.setText(f"“{variant}” → “{term}” sözlüğe eklendi{note}.")
        if self.on_dictionary_changed:
            self.on_dictionary_changed()
