import numpy as np

from app.collect import SR, quality


def tone(sec, amp):
    t = np.arange(int(sec * SR)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_quality():
    assert quality(tone(3, 0.2))[0]
    assert not quality(tone(0.5, 0.2))[0]          # çok kısa
    assert not quality(tone(3, 1.0))[0]            # patlama
    assert not quality(tone(3, 0.002))[0]          # çok kısık
    assert "uzun" in quality(tone(31, 0.2))[1]
