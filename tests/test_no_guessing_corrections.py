"""Tahmine dayalı düzeltmeler kaldırıldı: bulanık düzeltme doğru bir terimi başka bir hastalığa çevirebiliyordu
("pankreatik" -> "pankreatit"), bağlamsal düzeltme olumluyu olumsuza ("saptanmıştır" -> "saptanmamıştır").
Sonişleme de artık ayarlardan kapatılamaz."""
import dataclasses
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app import config as cfgmod  # noqa: E402
from app import dictation as dmod  # noqa: E402
from app.config import Config  # noqa: E402
from app.medical.postprocess import MedicalPostProcessor  # noqa: E402
from app.settings_window import SettingsPage  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
M = ROOT / "app" / "medical"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def post():
    return MedicalPostProcessor.from_files([M / "lexicon_tr.txt", M / "radiology_terms_tr.txt"], [M / "corrections_tr.tsv"],
                                           protected_files=[M / "radiology_known_tr.txt"],
                                           general_files=[M / "general_tr_words.txt"], use_itn=False)


@pytest.fixture(autouse=True)
def private_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", tmp_path / "config.json")


@pytest.mark.parametrize("text", ["ana pankreatik kanal", "menenjiom lehine", "müsinöz neoplazm lehine",
                                  "posterior desendan arter", "hemanjiyom izlenmektedir"])
def test_correctly_spelled_terms_stay_as_they_are(post, text):
    assert post(text) == text


@pytest.mark.parametrize("word", ["Tropolin", "intrabenoz"])
def test_misheard_word_is_not_guessed(post, word):
    assert post(word) == word


def test_exact_corrections_still_work(post):
    assert post("protezyon") == "protrüzyon"


def test_processor_has_no_fuzzy_option():
    with pytest.raises(TypeError):
        MedicalPostProcessor(fuzzy=False)
    assert not hasattr(MedicalPostProcessor, "apply_fuzzy")


def test_processor_has_no_context_option():
    with pytest.raises(TypeError):
        MedicalPostProcessor(context=None)


def test_context_corrector_is_gone():
    assert not (M / "context.py").exists()
    assert not (ROOT / "tools" / "build_context_lm.py").exists()
    assert "context_lm" not in (ROOT / "TibbiDikte.spec").read_text(encoding="utf-8")
    assert "context_lm" not in (ROOT / "app" / "dictation.py").read_text(encoding="utf-8")


def test_positive_finding_is_not_turned_negative(post):
    assert post("kitle saptanmıştır") == "kitle saptanmıştır"


def test_fuzzy_target_list_is_gone():
    assert not (M / "radiology_fuzzy_tr.txt").exists()
    assert "radiology_fuzzy" not in (ROOT / "TibbiDikte.spec").read_text(encoding="utf-8")


def test_config_has_no_fuzzy_or_postprocess_setting():
    names = {f.name for f in dataclasses.fields(Config)}
    assert not names & {"fuzzy_correction", "use_postprocess", "use_context", "context_threshold"}


def test_old_settings_file_cannot_leave_postprocess_off(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"fuzzy_correction": True, "use_postprocess": False, "num_threads": 3}),
                                          encoding="utf-8")
    cfg = Config.load()
    assert cfg.num_threads == 3
    d = dmod.Dictation(cfg)
    d.post = lambda text: text.upper()
    assert d._finish_text("abc") == "ABC "
    assert d._make_writer().transform("abc") == "ABC"


def test_settings_page_has_no_fuzzy_or_postprocess_switch(qapp):
    page = SettingsPage(Config())
    labels = [label.text() for label in page.findChildren(QLabel)]
    assert "Yanlış duyulan terimleri düzelt" not in labels and "Bağlama göre kelime düzelt" not in labels
    assert "Sonişleme" not in labels and "Tıbbi düzeltmeleri uygula" not in labels
    assert not hasattr(page, "cb_fuzzy") and not hasattr(page, "cb_post") and not hasattr(page, "cb_ctx")
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_saving_settings_does_not_write_removed_keys(qapp):
    page = SettingsPage(Config())
    page.show()
    assert page.save()
    saved = json.loads(cfgmod.CONFIG_FILE.read_text(encoding="utf-8"))
    assert not set(saved) & {"fuzzy_correction", "use_postprocess", "use_context", "context_threshold"}
    page.close()
    page.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
