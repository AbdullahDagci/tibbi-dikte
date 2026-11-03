"""Bas-konuş karar mantığı (gerçek klavye kancası olmadan, sahte olaylarla)."""
import time
from types import SimpleNamespace

import pytest

from app import ptt as P


class Suppressed(Exception):
    pass


class FakeListener:
    def suppress_event(self):
        raise Suppressed


@pytest.fixture
def env(monkeypatch):
    sent, calls = [], []
    monkeypatch.setattr(P, "_send_key", lambda vk, scan=0, up=False, extended=False: sent.append((vk, up)))
    mods = {"down": False}
    monkeypatch.setattr(P.PushToTalk, "_modifier_down", staticmethod(lambda: mods["down"]))
    monkeypatch.setattr(P, "HOLD_SEC", 0.05)
    t = P.PushToTalk("space", lambda: calls.append("start"), lambda: calls.append("stop"))
    t._listener = FakeListener()
    return t, sent, calls, mods


def ev(t, msg, vk, injected=False):
    data = SimpleNamespace(vkCode=vk, scanCode=0, flags=P.LLKHF_INJECTED if injected else 0)
    try:
        t._filter(msg, data)
        return "pass"
    except Suppressed:
        return "suppressed"


def wait():
    time.sleep(0.25)


def test_short_tap_types_a_space(env):
    t, sent, calls, _ = env
    assert ev(t, P.WM_KEYDOWN, P.VK_SPACE) == "suppressed"
    assert ev(t, P.WM_KEYUP, P.VK_SPACE) == "suppressed"
    wait()
    assert sent == [(P.VK_SPACE, False), (P.VK_SPACE, True)] and calls == []


def test_hold_starts_and_release_stops(env):
    t, sent, calls, _ = env
    ev(t, P.WM_KEYDOWN, P.VK_SPACE)
    wait()
    assert calls == ["start"]
    assert ev(t, P.WM_KEYDOWN, P.VK_SPACE) == "suppressed"  # tuş tekrarı yutulur
    assert ev(t, P.WM_KEYUP, P.VK_SPACE) == "suppressed"
    wait()
    assert calls == ["start", "stop"] and sent == []  # hiç boşluk yazılmadı


def test_fast_typing_overlap_keeps_order(env):
    t, sent, calls, _ = env
    ev(t, P.WM_KEYDOWN, P.VK_SPACE)
    assert ev(t, P.WM_KEYDOWN, 0x41) == "suppressed"  # 'A' boşluk bırakılmadan basıldı
    assert sent == [(P.VK_SPACE, False), (P.VK_SPACE, True), (0x41, False)]
    assert ev(t, P.WM_KEYUP, P.VK_SPACE) == "pass"  # zaten gönderildi, tekrar yazılmaz
    wait()
    assert calls == [] and len(sent) == 3


def test_modifier_combo_passes_through(env):
    t, sent, calls, mods = env
    mods["down"] = True  # Ctrl+Alt+Space
    assert ev(t, P.WM_KEYDOWN, P.VK_SPACE) == "pass"
    assert ev(t, P.WM_KEYUP, P.VK_SPACE) == "pass"
    wait()
    assert sent == [] and calls == []


def test_injected_events_ignored(env):
    t, sent, calls, _ = env
    assert ev(t, P.WM_KEYDOWN, P.VK_SPACE, injected=True) == "pass"
    wait()
    assert calls == []


def test_instant_key(monkeypatch):
    calls = []
    t = P.PushToTalk("f9", lambda: calls.append("start"), lambda: calls.append("stop"))
    t._listener = FakeListener()
    assert ev(t, P.WM_KEYDOWN, 0x78) == "suppressed"
    assert ev(t, P.WM_KEYDOWN, 0x78) == "suppressed"  # tekrar: ikinci kez başlatmaz
    assert ev(t, P.WM_KEYUP, 0x78) == "suppressed"
    time.sleep(0.1)
    assert calls == ["start", "stop"]
