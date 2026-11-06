"""Test ekranındaki dikte editörü: dikte metni klavye taklidi olmadan doğrudan editöre yazılır."""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.editor import DictationEditor, EditorPage, TextSink  # noqa: E402
from app.live import LiveWriter  # noqa: E402
from app.medical.postprocess import WordScore  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_live_correction_replaces_typed_tail_at_cursor(qapp):
    ed = DictationEditor()
    ed.setPlainText("Bulgular: ")
    ed.moveCursor(QTextCursor.End)
    w = LiveWriter(ed.insert_dictated, ed.erase_dictated)
    w.update_partial("beş yüz miligram")
    w._sync("beş yüz miligram ")  # anlık yazılmış hâl
    w.finalize("500 mg ")           # cümle sonu düzeltmesi
    assert ed.toPlainText() == "Bulgular: 500 mg "


def test_sink_applies_worker_thread_calls_in_order(qapp):
    ed = DictationEditor()
    sink = TextSink(ed)

    def work():
        sink.type("abc def ")
        sink.erase(4)
        sink.type("xyz\n")

    t = threading.Thread(target=work)
    t.start()
    t.join()
    QCoreApplication.processEvents()
    assert ed.toPlainText() == "abc xyz\n"


def test_dictation_hotkey_does_not_type_into_editor(qapp):
    ed = DictationEditor()
    QTest.keyClick(ed, Qt.Key_Space, Qt.ControlModifier | Qt.AltModifier)
    assert ed.toPlainText() == ""
    QTest.keyClick(ed, Qt.Key_Space)  # normal boşluk çalışmaya devam eder
    assert ed.toPlainText() == " "


def test_insert_annotated_colors_trailing_text_without_changing_it(qapp):
    ed = DictationEditor()
    ed.insert_dictated("Bulgular: ")
    ed.insert_dictated("metformin kullanan hastada ")
    ed.insert_annotated([("metformin", "corrected"), (" kullanan hastada ", "normal")])
    assert ed.toPlainText() == "Bulgular: metformin kullanan hastada "
    c = ed.textCursor()
    c.setPosition(len("Bulgular: "))
    c.setPosition(len("Bulgular: metformin"), QTextCursor.KeepAnchor)
    assert c.charFormat().foreground().color().name() == "#d14343"
    c.setPosition(len("Bulgular: metformin kullanan"))
    c.setPosition(len("Bulgular: metformin kullanan hastada"), QTextCursor.KeepAnchor)
    assert c.charFormat().foreground().color() != QColor("#d14343")


def test_sink_show_annotated_from_worker_thread(qapp):
    ed = DictationEditor()
    sink = TextSink(ed)

    def work():
        sink.type("metformın")
        sink.show_annotated([("metformin", "corrected")])

    t = threading.Thread(target=work)
    t.start()
    t.join()
    QCoreApplication.processEvents()
    assert ed.toPlainText() == "metformın"
    c = ed.textCursor()
    c.select(QTextCursor.Document)
    assert c.charFormat().foreground().color().name() == "#d14343"


def test_score_table_lists_rows_from_worker_thread_and_clears(qapp, tmp_path):
    page = EditorPage(tmp_path / "l.txt", tmp_path / "c.tsv", "Ctrl+Alt+Space")
    rows = [WordScore("astaya", "Astaya", 0.32, "corrected", "düşük güven"), WordScore("kez", "kez", None, "normal")]
    t = threading.Thread(target=page.sink.show_scores, args=(rows,))
    t.start()
    t.join()
    QCoreApplication.processEvents()
    assert page.score_table.rowCount() == 2
    assert page.score_table.item(0, 2).text() == "%32"
    assert page.score_table.item(1, 2).text() == "—"
    assert "düşük güven: 1" in page.score_summary.text()
    page._copy_scores()
    assert "astaya\tAstaya\t%32\tdüşük güven" in QGuiApplication.clipboard().text()
    page._clear()
    assert page.score_table.rowCount() == 0 and page.editor.toPlainText() == ""
    # Açıkça silinmezse süreç kapanışta aralıklı çöküyor (0xC0000005)
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_add_variant_request_uses_selection_and_replaces_it(qapp):
    ed = DictationEditor()
    ed.setPlainText("Toraks pete, incelemesi")
    c = ed.textCursor()
    c.setPosition(7)
    c.setPosition(12, QTextCursor.KeepAnchor)  # "pete,"
    ed.setTextCursor(c)
    got = []
    ed.add_variant_requested.connect(got.append)
    ed.request_add_variant()
    assert got == ["pete"]
    ed.replace_selection("BT")
    assert ed.toPlainText() == "Toraks BT, incelemesi"
