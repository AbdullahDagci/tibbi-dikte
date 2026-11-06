"""Dikte metni her zaman sonişlemeden geçer."""
from app import dictation as dmod
from app.config import Config


def _dictation(**cfg):
    d = dmod.Dictation(Config(**cfg))
    d.post = lambda text: "DÜZELTİLDİ"  # sonişleyici çağrılırsa belli olsun
    return d


def test_dictation_text_is_postprocessed():
    assert _dictation()._finish_text("beş yüz miligram") == "DÜZELTİLDİ "


def test_finish_text_forwards_confidences_to_annotate():
    d = _dictation()
    seen = {}

    class FakePost:
        def __call__(self, text):
            return text.upper()

        def annotate(self, text, confidences=None):
            seen["confidences"] = confidences
            return [(text.upper(), "normal")]

    d.post = FakePost()
    confs = [("abc", 0.2)]
    d._finish_text("abc", confs)
    assert seen["confidences"] == confs


def test_live_writer_types_postprocessed_words():
    d = _dictation(live_typing=True)
    d.post = lambda text: text.upper()
    assert d._make_writer().transform("abc") == "ABC"
    d.cfg.live_typing = False
    assert d._make_writer() is None
