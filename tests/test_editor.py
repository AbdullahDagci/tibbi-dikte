"""Test ekranındaki dikte editörü: dikte metni klavye taklidi olmadan doğrudan editöre yazılır."""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.editor import DictationEditor, TextSink  # noqa: E402
from app.live import LiveWriter  # noqa: E402


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
