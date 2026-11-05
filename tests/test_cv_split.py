"""Common Voice: eğitim = validated − (dev ∪ test); cümle düzeyinde ayrım (aynı cümlenin başka okuması da sızıntıdır)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from cvsplit import cv_train_rows  # noqa: E402


def row(path, sentence):
    return {"path": path, "sentence": sentence}


def test_validated_minus_dev_test_by_clip_and_sentence():
    validated = [row("a.mp3", "Bugün hava güzel."), row("b.mp3", "Yarın yağmur var."),
                 row("c.mp3", "bugün hava  güzel"),            # dev cümlesinin başka okuması (yazım farkıyla)
                 row("d.mp3", "Test cümlesi burada."),         # test klibi
                 row("e.mp3", "Yeni bir cümle.")]
    dev = [row("x.mp3", "Bugün hava güzel.")]
    test = [row("d.mp3", "Test cümlesi burada.")]
    got = [r["path"] for r in cv_train_rows(validated, dev, test)]
    assert got == ["b.mp3", "e.mp3"]
