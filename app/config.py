"""Kullanıcı ayarları: %APPDATA%\\TibbiDikte\\config.json"""
import json
from dataclasses import asdict, dataclass, field

from .paths import user_dir

CONFIG_FILE = user_dir() / "config.json"


@dataclass
class Config:
    model_dir: str = ""                 # seçili model klasörü (boşsa ilk bulunan)
    hotkey: str = "<ctrl>+<alt>+<space>"  # pynput GlobalHotKeys biçimi
    ptt_key: str = "space"              # bas-konuş: off | space | rctrl | f8 | f9 | f10
    input_device: int | None = None     # None = varsayılan mikrofon
    num_threads: int = 2
    use_hotwords: bool = True
    hotwords_score: float = 2.0
    use_itn: bool = True                # sayı/yüzde/tarih -> yazılı biçim
    add_trailing_space: bool = True
    live_typing: bool = True            # kelimeleri konuşurken yaz; cümle sonunda düzeltilmiş hâliyle güncelle
    show_overlay: bool = True           # dinlerken ekranın sağ altında nabız + canlı metin
    beep_enabled: bool = True           # dikte başlarken ve biterken bip
    beep_start_hz: int = 990
    beep_stop_hz: int = 660
    beep_ms: int = 70
    extra: dict = field(default_factory=dict)
    config_version: int = 2             # 2: model_dir boşsa model.json'da "default" olan model kullanılır

    @classmethod
    def load(cls) -> "Config":
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                # Sürüm 1'de tek model v2'ydi ve Ayarlar kaydedilince listedeki ilk model yazılıyordu:
                # bu kayıt bir tercih değil -> varsayılan modele geç
                if "config_version" not in data and str(known.get("model_dir", "")).rstrip("\\/").endswith(
                        "tibbi-tr-v2"):
                    known["model_dir"] = ""
                return cls(**known)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        CONFIG_FILE.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
