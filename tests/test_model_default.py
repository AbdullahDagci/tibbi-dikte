"""Varsayılan konuşma modeli: model.json'da "default": true olan model (06.11: tibbi-tr-v3-tam-w07) seçilir;
kullanıcı başka bir model seçtiyse onunki geçerli."""
import json
from pathlib import Path

from app import config as cfgmod
from app.config import Config
from app.engines.base import ModelInfo
from app.engines.registry import resolve_model

ROOT = Path(__file__).resolve().parent.parent


def _m(tmp_path, name, **spec):
    d = tmp_path / name
    d.mkdir()
    return ModelInfo(dir=d, spec={"name": name, **spec})


def test_default_flag_beats_alphabetical_order(tmp_path):
    v2, tam = _m(tmp_path, "tibbi-tr-v2"), _m(tmp_path, "tibbi-tr-v3-tam", default=True)
    assert resolve_model([v2, tam], "") is tam


def test_without_default_flag_first_model_is_used(tmp_path):
    a, b = _m(tmp_path, "a"), _m(tmp_path, "b")
    assert resolve_model([a, b], "") is a


def test_user_choice_wins_over_default(tmp_path):
    v2, tam = _m(tmp_path, "tibbi-tr-v2"), _m(tmp_path, "tibbi-tr-v3-tam", default=True)
    assert resolve_model([v2, tam], str(v2.dir)) is v2


def test_missing_user_choice_falls_back_to_default(tmp_path):
    v2, tam = _m(tmp_path, "tibbi-tr-v2"), _m(tmp_path, "tibbi-tr-v3-tam", default=True)
    assert resolve_model([v2, tam], str(tmp_path / "silinmis-model")) is tam


def test_dictation_uses_default_model(monkeypatch, tmp_path):
    from app import dictation as dmod
    v2, tam = _m(tmp_path, "tibbi-tr-v2"), _m(tmp_path, "tibbi-tr-v3-tam", default=True)
    monkeypatch.setattr(dmod, "discover_models", lambda: [v2, tam])
    assert dmod.Dictation(Config()).pick_model() is tam


def test_legacy_auto_saved_v2_choice_is_cleared(monkeypatch, tmp_path):
    """Eski sürümlerde tek model v2 idi ve Ayarlar kaydedilince listedeki ilk model (v2) yazılıyordu:
    bu kayıt kullanıcı tercihi sayılmaz, yeni varsayılan modele geçilir."""
    f = tmp_path / "config.json"
    f.write_text(json.dumps({"model_dir": r"C:\Program Files\TibbiDikte\models\tibbi-tr-v2", "num_threads": 4}),
                 encoding="utf-8")
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", f)
    c = Config.load()
    assert c.model_dir == "" and c.num_threads == 4


def test_v2_chosen_in_new_version_is_kept(monkeypatch, tmp_path):
    f = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", f)
    Config(model_dir=r"C:\Program Files\TibbiDikte\models\tibbi-tr-v2").save()
    assert Config.load().model_dir.endswith("tibbi-tr-v2")


def test_repo_default_is_w07():
    flagged = [p.parent.name for p in (ROOT / "models").glob("*/model.json")
               if json.loads(p.read_text(encoding="utf-8")).get("default")]
    assert flagged == ["tibbi-tr-v3-tam-w07"]


def test_installer_ships_default_model():
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert r"models\tibbi-tr-v3-tam-w07\*" in iss
