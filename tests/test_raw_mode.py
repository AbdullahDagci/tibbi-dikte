"""Ham metin modu (05.11 kullanıcı: "ne duyuyorsan onu yaz, düzenleme ayarları şimdilik pasif olsun"):
sonişleme kapalıyken model çıktısı olduğu gibi yazılır."""
import json

from app import config as cfgmod
from app import dictation as dmod
from app.config import Config


def _dictation(**cfg):
    d = dmod.Dictation(Config(**cfg))
    d.post = lambda text: "DÜZELTİLDİ"  # sonişleyici çağrılırsa belli olsun
    return d


def test_postprocess_on_by_default():
    assert Config().use_postprocess is True
    assert _dictation()._finish_text("beş yüz miligram") == "DÜZELTİLDİ "


def test_raw_mode_types_model_output_unchanged():
    d = _dictation(use_postprocess=False)
    assert d._finish_text("beş yüz miligram, sol L dört") == "beş yüz miligram, sol L dört "
    assert d._finish_text("") == ""


def test_raw_mode_setting_persists(monkeypatch, tmp_path):
    f = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", f)
    Config(use_postprocess=False, live_typing=False).save()
    assert json.loads(f.read_text(encoding="utf-8"))["use_postprocess"] is False
    c = Config.load()
    assert c.use_postprocess is False and c.live_typing is False


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
    d.cfg.use_postprocess = False
    assert d._make_writer().transform("abc") == "abc"
    d.cfg.live_typing = False
    assert d._make_writer() is None
