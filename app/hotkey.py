"""Global kısayol (pynput). Geri çağrı pynput iş parçacığında çalışır — UI'ya sinyal ile aktarın."""
from __future__ import annotations

from typing import Callable

from pynput import keyboard

_QT_TO_PYNPUT = {"ctrl": "<ctrl>", "alt": "<alt>", "shift": "<shift>", "meta": "<cmd>",
                 "space": "<space>", "ins": "<insert>", "del": "<delete>", "pause": "<pause>",
                 "home": "<home>", "end": "<end>", "pgup": "<page_up>", "pgdown": "<page_down>"}


def qt_to_pynput(seq: str) -> str:
    """'Ctrl+Alt+Space' -> '<ctrl>+<alt>+<space>', 'F9' -> '<f9>'."""
    out = []
    for part in seq.split("+"):
        p = part.strip().lower()
        if not p:
            continue
        if p in _QT_TO_PYNPUT:
            out.append(_QT_TO_PYNPUT[p])
        elif p.startswith("f") and p[1:].isdigit():
            out.append(f"<{p}>")
        elif len(p) == 1:
            out.append(p)
        else:
            out.append(f"<{p}>")
    return "+".join(out)


def pynput_to_qt(hk: str) -> str:
    rev = {v: k for k, v in _QT_TO_PYNPUT.items()}
    parts = []
    for p in hk.split("+"):
        name = rev.get(p, p.strip("<>"))
        parts.append(name.capitalize() if len(name) > 1 else name.upper())
    return "+".join(parts)


def is_valid(hk: str) -> bool:
    try:
        keyboard.HotKey.parse(hk)
        return True
    except ValueError:
        return False


class GlobalHotkey:
    """pynput.GlobalHotKeys yazılımla üretilen (injected) tuşları yok sayar. Dikte mikrofonları (SpeechMike vb.),
    ayak pedalları ve makro araçları düğmeleri çoğunlukla bu yolla kısayola çevirir; o yüzden kendi dinleyicimiz
    injected olayları da kabul eder."""

    def __init__(self, combo: str, callback: Callable[[], None]):
        self.combo = combo
        self.callback = callback
        self._listener: keyboard.Listener | None = None

    def start(self) -> None:
        self.stop()
        hk = keyboard.HotKey(keyboard.HotKey.parse(self.combo), self.callback)
        listener: keyboard.Listener

        def on_press(key):
            hk.press(listener.canonical(key))

        def on_release(key):
            hk.release(listener.canonical(key))

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        self._listener = listener
        listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def rebind(self, combo: str) -> None:
        self.combo = combo
        self.start()
