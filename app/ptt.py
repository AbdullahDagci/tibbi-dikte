"""Bas-konuş (push-to-talk): tuş basılı tutulduğu sürece dikte.

Boşluk tuşu özel ele alınır, çünkü yazarken en çok kullanılan tuştur:
  * kısa basış -> normal boşluk (tuş yutulur, bırakınca boşluk yeniden gönderilir)
  * HOLD_SEC'ten uzun basılı tutma -> dikte başlar; bırakınca durur; bu arada boşluk yazılmaz
  * boşluk basılıyken başka bir tuşa basılırsa (hızlı yazımda çakışma) -> önce boşluk, sonra o tuş gönderilir
  * Ctrl/Alt/Shift/Win basılıyken boşluğa hiç dokunulmaz (Ctrl+Alt+Space gibi kısayollar çalışır)
Diğer tuşlar (Sağ Ctrl, F8-F10) beklemeden anında başlatır ve işletim sistemine hiç iletilmez
(aksi hâlde basılı Ctrl, yazılan metni kısayola çevirirdi).
Yazılımla üretilmiş (injected) olaylar yok sayılır: kendi yazdığımız metin ve yeniden gönderdiğimiz boşluk.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

HOLD_SEC = 0.35
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
LLKHF_INJECTED = 0x10
VK_SPACE = 0x20
MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5)

# ayar değeri -> (görünen ad, sanal tuş kodu)
PTT_KEYS = {
    "off": ("Kapalı", None),
    "space": ("Boşluk (basılı tut)", VK_SPACE),
    "rctrl": ("Sağ Ctrl", 0xA3),
    "f8": ("F8", 0x77),
    "f9": ("F9", 0x78),
    "f10": ("F10", 0x79),
}


def _send_key(vk: int, scan: int = 0, up: bool = False, extended: bool = False) -> None:
    flags = (0x0002 if up else 0) | (0x0001 if extended else 0)
    ctypes.windll.user32.keybd_event(vk, scan, flags, 0)


class PushToTalk:
    def __init__(self, key: str, on_start: Callable[[], None], on_stop: Callable[[], None]):
        self.key = key
        self.vk = PTT_KEYS.get(key, (None, None))[1]
        self.on_start, self.on_stop = on_start, on_stop
        self._listener = None
        self._lock = threading.Lock()
        self._pending = False   # boşluk basıldı, eşik henüz dolmadı
        self._active = False    # dikte bas-konuş ile açık
        self._press_id = 0

    # ------------------------------------------------ yaşam döngüsü
    def start(self) -> None:
        self.stop()
        if self.vk is None or sys.platform != "win32":
            return
        from pynput import keyboard
        self._listener = keyboard.Listener(win32_event_filter=self._filter)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self._active:
            self._active = False
            self.on_stop()

    def rebind(self, key: str) -> None:
        self.key, self.vk = key, PTT_KEYS.get(key, (None, None))[1]
        self.start()

    # ------------------------------------------------ olay süzgeci (kanca iş parçacığında çalışır; hızlı olmalı)
    @staticmethod
    def _modifier_down() -> bool:
        gks = ctypes.windll.user32.GetAsyncKeyState
        return any(gks(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C))

    def _suppress(self) -> None:
        self._listener.suppress_event()  # SuppressException fırlatır: olay işletim sistemine iletilmez

    def _filter(self, msg, data) -> bool:
        if data.flags & LLKHF_INJECTED:
            return True
        down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
        up = msg in (WM_KEYUP, WM_SYSKEYUP)
        vk = data.vkCode
        if vk == self.vk:
            if self.vk == VK_SPACE:
                return self._space(down, up)
            return self._instant(down, up)
        # boşluk beklerken başka tuş: hızlı yazım çakışması -> önce boşluk, sonra bu tuş
        if down and self._pending and vk not in MODIFIER_VKS:
            with self._lock:
                self._pending = False
                self._press_id += 1
            _send_key(VK_SPACE)
            _send_key(VK_SPACE, up=True)
            _send_key(vk, data.scanCode, extended=bool(data.flags & 0x01))
            self._suppress()
        return True

    def _instant(self, down: bool, up: bool):
        if down:
            if not self._active:
                self._active = True
                threading.Thread(target=self.on_start, daemon=True).start()
            self._suppress()
        elif up:
            if self._active:
                self._active = False
                threading.Thread(target=self.on_stop, daemon=True).start()
            self._suppress()
        return True

    def _space(self, down: bool, up: bool):
        if down:
            if self._active or self._pending:
                self._suppress()  # tuş tekrarı
            if self._modifier_down():
                return True  # Ctrl+Space, Ctrl+Alt+Space vb.: dokunma
            with self._lock:
                self._pending = True
                self._press_id += 1
                pid = self._press_id
            threading.Thread(target=self._arm, args=(pid,), daemon=True).start()
            self._suppress()
        elif up:
            with self._lock:
                was_pending, was_active = self._pending, self._active
                self._pending = self._active = False
                self._press_id += 1
            if was_active:
                threading.Thread(target=self.on_stop, daemon=True).start()
                self._suppress()
            elif was_pending:  # kısa basış: normal boşluk
                _send_key(VK_SPACE)
                _send_key(VK_SPACE, up=True)
                self._suppress()
        return True

    def _arm(self, pid: int) -> None:
        time.sleep(HOLD_SEC)
        with self._lock:
            if not self._pending or self._press_id != pid:
                return
            self._pending = False
            self._active = True
        log.info("bas-konuş: başladı")
        self.on_start()
