"""Uygulama yolları: kurulum dizini (salt okunur) ve kullanıcı verisi (%APPDATA%)."""
import os
import sys
from pathlib import Path

APP_NAME = "TibbiDikte"


def install_dir() -> Path:
    """PyInstaller paketinde exe'nin klasörü, geliştirmede proje kökü."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Paketlenmiş kaynaklar (sözlük, açık anahtar). PyInstaller onedir'de _internal altında."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", install_dir())) / "app"
    return Path(__file__).resolve().parent


def user_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dirs() -> list[Path]:
    """Modellerin aranacağı klasörler: kurulum/models ve kullanıcı/models."""
    dirs = [install_dir() / "models", user_dir() / "models"]
    return [d for d in dirs if d.is_dir()]
