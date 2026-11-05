"""Aktif penceredeki imleç konumuna metin yazar (Win32 SendInput, KEYEVENTF_UNICODE).

Unicode olay gönderildiği için klavye düzeninden bağımsızdır; ş, ğ, ı, İ, ö, ü, ç doğru çıkar
ve pano değiştirilmez.
"""
import ctypes
import logging
import sys
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))


def _events_for(text: str) -> list[INPUT]:
    events: list[INPUT] = []
    for ch in text:
        if ch == "\n":
            events += [_key(vk=VK_RETURN), _key(vk=VK_RETURN, flags=KEYEVENTF_KEYUP)]
            continue
        # BMP dışı karakterler UTF-16 vekil çift olarak gönderilir
        data = ch.encode("utf-16-le")
        for i in range(0, len(data), 2):
            code = int.from_bytes(data[i:i + 2], "little")
            events += [_key(scan=code, flags=KEYEVENTF_UNICODE),
                       _key(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    return events


_MODIFIERS = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # Shift, Ctrl, Alt, LWin, RWin


def wait_modifiers_released(timeout: float = 2.0) -> None:
    """Kısayol tuşları hâlâ basılıyken yazarsak Ctrl+Alt+harf (AltGr) kombinasyonu oluşur."""
    user32 = ctypes.windll.user32
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIERS):
            return
        time.sleep(0.02)


def _send(events: list[INPUT], what: str) -> int:
    """SendInput + tanı kaydı (süre, gönderilen olay sayısı)."""
    arr = (INPUT * len(events))(*events)
    t0 = time.perf_counter()
    sent = ctypes.windll.user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))
    ms = (time.perf_counter() - t0) * 1000
    level = logging.WARNING if ms > 250 or sent != len(events) else logging.DEBUG
    log.log(level, "SendInput %s: %d/%d olay, %.0f ms", what, sent, len(events), ms)
    return sent


def type_text(text: str) -> None:
    if not text or sys.platform != "win32":
        return
    wait_modifiers_released()
    events = _events_for(text)
    if _send(events, f"yaz {len(text)} karakter") != len(events):
        raise OSError("SendInput başarısız (hedef pencere yönetici yetkisiyle çalışıyor olabilir)")


VK_BACK = 0x08


def backspace(n: int) -> None:
    """n karakter sil (anlık yazımda, cümle sonu düzeltmesi için)."""
    if n <= 0 or sys.platform != "win32":
        return
    wait_modifiers_released()
    events = []
    for _ in range(n):
        events += [_key(vk=VK_BACK), _key(vk=VK_BACK, flags=KEYEVENTF_KEYUP)]
    _send(events, f"sil {n}")
