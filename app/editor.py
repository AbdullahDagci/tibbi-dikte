"""Dikte sayfası ve editörü.

Editör etkin pencereyken dikte metni klavye taklidi (SendInput) olmadan doğrudan editöre yazılır; böylece
hedef uygulamanın Backspace/Unicode işleyişinden bağımsız olarak tanıma + sonişleme + anlık düzeltme denenir.
Yanlış çıkan kelime seçilip sağ tıkla "Sözlüğe varyant olarak ekle…" ile doğru yazıma bağlanır.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QMessageBox, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme, user_dict
from .scoring import estimated_accuracy
from .ui import widgets

_STRIP = " \t\n.,;:!?\"'’()"
# Test ekranı: sonislemenin değiştirdiği ("corrected") ve değiştirmeden bıraktığı ama kuşkulu
# ("suspect") kelimeleri ayırt etmek için kullanıcıya gösterilen renkler.
_STATUS_COLORS = {"corrected": QColor(theme.BAD), "suspect": QColor(theme.WARN)}
_HELP = ("Sesli komutlar: \"alt satıra geç\", \"satır başı\", \"paragraf başı\", \"yeni madde\".\n"
         "Yanlış çıkan kelimeyi seçip sağ tıklayın: Sözlüğe varyant olarak ekle.\n"
         "Kırmızı: sonişleme değiştirdi ya da model düşük güvenle duydu, kontrol edin.\n"
         "Turuncu: tanınmayan kelime ya da model orta güvenle duydu.")


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

    def insert_annotated(self, spans: list[tuple[str, str]]) -> None:
        """insert_dictated ile zaten yazılmış son metni, sonisleme sonucuna göre renklendirir
        ("corrected": kırmızı, "suspect": turuncu). Yeni metin eklemez, yalnızca biçimlendirir."""
        total = sum(len(t) for t, _ in spans)
        end = self.document().characterCount() - 1  # belge sonu (son karakterden sonraki konum)
        pos = max(0, end - total)
        c = self.textCursor()
        default_fmt = QTextCharFormat()
        for text, status in spans:
            c.setPosition(pos)
            c.setPosition(pos + len(text), QTextCursor.KeepAnchor)
            fmt = QTextCharFormat(default_fmt)
            color = _STATUS_COLORS.get(status)
            if color is not None:
                fmt.setForeground(color)
            c.setCharFormat(fmt)
            pos += len(text)

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
    _annotated = Signal(list)
    scores = Signal(object)

    def __init__(self, editor: DictationEditor):
        super().__init__()
        self._typed.connect(editor.insert_dictated)
        self._erased.connect(editor.erase_dictated)
        self._annotated.connect(editor.insert_annotated)

    def type(self, text: str) -> None:
        if text:
            self._typed.emit(text)

    def erase(self, n: int) -> None:
        if n > 0:
            self._erased.emit(n)

    def show_annotated(self, spans: list[tuple[str, str]]) -> None:
        if spans:
            self._annotated.emit(spans)

    def show_scores(self, rows: list) -> None:
        if rows:
            self.scores.emit(rows)


class EditorPage(QWidget):
    """Dikte sayfası: başlat/durdur, editör, kopyala/kaydet/temizle, güven tablosu."""

    def __init__(self, lexicon_path: Path, corrections_path: Path, hotkey_label: str,
                 on_toggle: Callable[[], None] | None = None,
                 on_dictionary_changed: Callable[[], None] | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.lexicon_path, self.corrections_path = lexicon_path, corrections_path
        self.on_toggle = on_toggle
        self.on_dictionary_changed = on_dictionary_changed
        self.hotkey_label = hotkey_label

        self.btn = widgets.button("", "player-record", "primary")
        self.btn.clicked.connect(self._toggle_clicked)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        copy = widgets.button("Kopyala", "copy", "light")
        copy.clicked.connect(self._copy_text)
        save = widgets.button("Kaydet", "device-floppy", "success")
        save.clicked.connect(self._save)
        clear = widgets.button("Temizle", "eraser", "danger")
        clear.clicked.connect(self._clear)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.btn)
        row.addWidget(self.status, 1)
        row.addWidget(widgets.InfoTip(_HELP))
        for b in (copy, save, clear):
            row.addWidget(b)

        self.editor = DictationEditor()
        self.editor.add_variant_requested.connect(self._add_variant)
        self.setFocusProxy(self.editor)
        editor_card = widgets.Card()
        editor_card.body.addLayout(row)
        editor_card.body.addWidget(self.editor, 1)

        self._score_rows: list = []
        self.score_table = QTableWidget(0, 4)
        self.score_table.setHorizontalHeaderLabels(["Duyulan", "Yazılan", "Tahmini doğruluk", "Renk nedeni"])
        self.score_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.score_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.score_table.verticalHeader().hide()
        self.score_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.score_table.setMinimumHeight(190)
        self.score_summary = QLabel()
        self.score_summary.setObjectName("muted")
        self.score_summary.setWordWrap(True)
        copy_scores = widgets.button("Skorları kopyala", "copy", "light")
        copy_scores.clicked.connect(self._copy_scores)
        summary_row = QHBoxLayout()
        summary_row.addWidget(self.score_summary, 1)
        summary_row.addWidget(copy_scores)
        self.scores = widgets.Collapsible("Kelime skorları", "chart-bar", expanded=False)
        self.scores.body.addLayout(summary_row)
        self.scores.body.addWidget(self.score_table, 1)
        scores_card = widgets.Card()
        scores_card.body.addWidget(self.scores)

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)
        v.addWidget(editor_card, 1)
        v.addWidget(scores_card)
        self.sink = TextSink(self.editor)
        self.sink.scores.connect(self.add_scores)
        self._update_score_summary()
        self.set_listening(False)

    def _toggle_clicked(self) -> None:
        if self.on_toggle:
            self.on_toggle()

    def _copy_text(self) -> None:
        QGuiApplication.clipboard().setText(self.editor.toPlainText())

    # -------------------------------------------- güven tablosu
    @staticmethod
    def _conf_text(confidence: float | None) -> str:
        return "—" if confidence is None else f"%{estimated_accuracy(confidence) * 100:.0f}"

    def add_scores(self, rows: list) -> None:
        for r in rows:
            i = self.score_table.rowCount()
            self.score_table.insertRow(i)
            color = _STATUS_COLORS.get(r.status)
            for col, value in enumerate((r.heard, r.written, self._conf_text(r.confidence), r.reason)):
                item = QTableWidgetItem(value)
                if color is not None:
                    item.setForeground(color)
                self.score_table.setItem(i, col, item)
        self._score_rows += rows
        self.score_table.scrollToBottom()
        self._update_score_summary()

    def _update_score_summary(self) -> None:
        rows = self._score_rows
        if not rows:
            self.score_summary.setText("Henüz dikte yok")
            return
        confs = [estimated_accuracy(r.confidence) for r in rows if r.confidence is not None]
        mean = f"%{sum(confs) / len(confs) * 100:.0f}" if confs else "—"
        by_reason = lambda reason: sum(r.reason == reason for r in rows)
        self.score_summary.setText(
            f"{len(rows)} satır · ortalama tahmini doğruluk {mean} · "
            f"<span style='color:{theme.BAD}'>düşük güven: {by_reason('düşük güven')} · "
            f"sonişleme değiştirdi: {by_reason('sonişleme değiştirdi')}</span> · "
            f"<span style='color:{theme.WARN}'>orta güven: {by_reason('orta güven')} · "
            f"sözlükte yok: {by_reason('sözlükte yok')}</span>")

    def _copy_scores(self) -> None:
        lines = ["Duyulan\tYazılan\tTahmini doğruluk\tRenk nedeni"]
        lines += [f"{r.heard}\t{r.written}\t{self._conf_text(r.confidence)}\t{r.reason}" for r in self._score_rows]
        QGuiApplication.clipboard().setText("\n".join(lines))

    def _clear(self) -> None:
        self.editor.clear()
        self.score_table.setRowCount(0)
        self._score_rows = []
        self._update_score_summary()

    def set_listening(self, on: bool) -> None:
        self.btn.setText("Dikteyi durdur" if on else "Dikteyi başlat")
        widgets.set_variant(self.btn, "danger" if on else "primary", icon="player-stop" if on else "player-record")
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
