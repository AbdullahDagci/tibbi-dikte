"""NOTICE.txt (program klasörüne kurulur) yalnızca kurulumun paketlediği modelleri içerir. 06.11 kullanıcı: kurulum
yalnızca kendi eğittiğimiz modeli (tibbi-tr-v3-tam-w07) taşır; mihu adı geçmez. 10.11 kullanıcı: kurulumda kişi adı ve
bileşen listesi gösterilmez, standart son kullanıcı sözleşmesi gösterilir."""

PERSONAL_NAMES = ("abdullah", "ibrahim", "dağcı", "dagci")
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from make_notice import build_notice, shipped_models  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_installer_ships_only_our_model():
    assert shipped_models() == ["tibbi-tr-v3-tam-w07"]


def test_notice_names_our_model_not_mihu():
    text = build_notice().lower()
    assert "tıbbi türkçe v3" in text
    assert "mihu" not in text and "ertansa" not in text
    assert not any(n in text for n in PERSONAL_NAMES)


def test_about_tab_attribution_of_default_model():
    spec = json.loads((ROOT / "models" / "tibbi-tr-v3-tam-w07" / "model.json").read_text(encoding="utf-8"))
    assert "mihu" not in spec["attribution"].lower() and "Tıbbi Dikte" in spec["attribution"]
    assert not any(n in spec["attribution"].lower() for n in PERSONAL_NAMES)
    assert "mihu" not in spec["license"].lower()


def test_installer_shows_standard_agreement_without_names_or_components():
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert "LicenseFile=lisans_sozlesmesi.txt" in iss
    assert "AppPublisher=Tıbbi Dikte" in iss
    assert r'Source: "..\NOTICE.txt"; DestDir: "{app}"' in iss   # bildirimler program klasöründe kalır
    eula = (ROOT / "installer" / "lisans_sozlesmesi.txt").read_bytes()
    assert eula.startswith(b"\xef\xbb\xbf")                      # Inno Setup Türkçe karakterleri doğru okusun
    text = eula.decode("utf-8-sig").lower()
    assert not any(n in text for n in PERSONAL_NAMES)
    assert not any(lib in text for lib in ("sherpa", "pyside", "qt ", "lgpl", "apache", "ffmpeg", "pynput",
                                           "açık kaynak", "notice"))
    numbers = [int(line.split(".")[0]) for line in text.splitlines() if line[:1].isdigit()]
    assert numbers == list(range(1, len(numbers) + 1))           # maddeler 1'den sırayla


def test_uninstall_closes_running_app_and_asks_before_deleting_license():
    # 10.11: kaldırırken açık uygulama dosyaları kilitliyordu (klasör silinmedi, uygulama açık kaldı)
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    code = iss.split("[Code]", 1)[1]
    stop = code.index("taskkill.exe'), '/F /IM TibbiDikte.exe'")
    assert code.rindex("usUninstall then", 0, stop) < stop        # dosyalar silinmeden önce
    assert "{userappdata}\\TibbiDikte" in code and "DelTree" in code
    assert "MB_DEFBUTTON2, IDNO) = IDYES" in code                 # varsayılan ve sessiz kaldırma: veriler kalır


def test_installer_version_matches_app_version():
    import re
    from app import __version__
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert re.search(r'#define AppVersion "(.+)"', iss).group(1) == __version__
    readme = (ROOT / "installer" / "OKUBENI.txt").read_text(encoding="utf-8")
    assert "TibbiDikte-Demo-Kurulum-{SURUM}.exe" in readme   # build.ps1 sürümü yazar


def test_old_v2_folder_removed_on_upgrade():
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert r'Name: "{app}\models\tibbi-tr-v2"' in iss
    assert r"..\models\tibbi-tr-v2" not in iss


def test_old_default_folder_removed_on_upgrade():
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    assert r'Name: "{app}\models\tibbi-tr-v3-tam"' in iss
    assert r"..\models\tibbi-tr-v3-tam\*" not in iss
