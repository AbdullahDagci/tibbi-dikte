"""NOTICE.txt (kurulumda lisans sayfası, Hakkında › Açık kaynak lisansları) yalnızca kurulumun paketlediği modelleri
içerir. 06.11 kullanıcı: kurulum yalnızca kendi eğittiğimiz modeli (tibbi-tr-v3-tam) taşır; mihu adı geçmez."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from make_notice import build_notice, shipped_models  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_installer_ships_only_our_model():
    assert shipped_models() == ["tibbi-tr-v3-tam"]


def test_notice_names_our_model_not_mihu():
    text = build_notice()
    assert "Tıbbi Türkçe v3" in text and "Abdullah DAĞCI" in text
    assert "mihu" not in text.lower() and "ertansa" not in text.lower()


def test_about_tab_attribution_of_default_model():
    spec = json.loads((ROOT / "models" / "tibbi-tr-v3-tam" / "model.json").read_text(encoding="utf-8"))
    assert "mihu" not in spec["attribution"].lower() and "Abdullah DAĞCI" in spec["attribution"]
    assert "mihu" not in spec["license"].lower()


def test_old_v2_folder_removed_on_upgrade():
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert r'Name: "{app}\models\tibbi-tr-v2"' in iss
    assert r"..\models\tibbi-tr-v2" not in iss
