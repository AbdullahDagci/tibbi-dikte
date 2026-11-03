"""Kısayol, yazılımla üretilen tuşlarda da (dikte mikrofonu/pedal yazılımları) tetiklenmeli."""
import ctypes
import sys
import time

import pytest

from app.hotkey import GlobalHotkey, is_valid, pynput_to_qt, qt_to_pynput

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows'a özgü")


def _tap(*vks):
    user32 = ctypes.windll.user32
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.03)


def test_conversions():
    assert qt_to_pynput("Ctrl+Alt+Space") == "<ctrl>+<alt>+<space>"
    assert qt_to_pynput("F9") == "<f9>"
    assert pynput_to_qt("<ctrl>+<alt>+<space>") == "Ctrl+Alt+Space"
    assert is_valid("<ctrl>+<alt>+<space>") and not is_valid("<ctrl>+<nope>")


def test_injected_keys_trigger_hotkey():
    hits = []
    hk = GlobalHotkey("<ctrl>+<alt>+<f13>", lambda: hits.append(1))  # F13: kullanıcının işini bozmaz
    hk.start()
    time.sleep(0.4)
    try:
        _tap(0x11, 0x12, 0x7C)  # Ctrl, Alt, F13
        time.sleep(0.4)
    finally:
        hk.stop()
    assert hits == [1]
