"""Sözlük değişince yalnız sonişleyici yenilenir: model yüklenmez, dikte kesilmez."""
import pytest

from app import dictation as dm
from app.config import Config


@pytest.fixture
def dictation(tmp_path, monkeypatch):
    lex, corr = tmp_path / "t.txt", tmp_path / "d.tsv"
    lex.write_text("", encoding="utf-8")
    corr.write_text("", encoding="utf-8")
    monkeypatch.setattr(dm, "USER_LEXICON", lex)
    monkeypatch.setattr(dm, "USER_CORRECTIONS", corr)
    monkeypatch.setattr(dm, "load_engine", lambda *a, **k: pytest.fail("model yüklenmemeliydi"))
    states = []
    d = dm.Dictation(Config(), on_state=states.append)
    d.states = states
    d.corrections_file = corr
    return d


def test_reload_applies_new_correction_without_touching_engine(dictation):
    engine = object()
    dictation.engine = engine
    dictation.reload_dictionary()
    assert "ömer" in dictation._finish_text("ömer geldi")
    dictation.corrections_file.write_text("ömer\tahmet\n", encoding="utf-8")
    dictation.reload_dictionary()
    assert dictation._finish_text("ömer geldi").startswith("ahmet")
    assert dictation.engine is engine and dictation.states == []


def test_reload_before_model_is_ready_does_nothing(dictation):
    dictation.engine = None
    dictation.reload_dictionary()
    assert dictation.post is None


def test_failed_reload_keeps_previous_dictionary(dictation, monkeypatch):
    dictation.engine = object()
    dictation.reload_dictionary()
    previous = dictation.post
    monkeypatch.setattr(dm.MedicalPostProcessor, "from_files", classmethod(lambda cls, *a, **k: 1 / 0))
    dictation.reload_dictionary()
    assert dictation.post is previous


class _Model:
    def __init__(self, hotwords):
        self.hotwords = hotwords


@pytest.mark.parametrize("use,model_hotwords,expected", [(True, True, True), (True, False, False), (False, True, False)])
def test_engine_reload_needed_only_when_model_uses_hotwords(dictation, use, model_hotwords, expected):
    dictation.cfg.use_hotwords = use
    dictation.model = _Model(model_hotwords)
    assert dictation.needs_engine_reload_for_dictionary() is expected
