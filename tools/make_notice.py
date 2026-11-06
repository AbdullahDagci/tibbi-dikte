"""NOTICE.txt'yi kurulumun paketlediği modellerden (installer/setup.iss) üretir (build.ps1 çağırır).
models/ altındaki yerel deneme modelleri (pilot, -best, karışımlar) NOTICE'a girmez.

Bir modelin model.json'unda "attribution" varsa (ör. mihu türevi modeller), lisansı gereği atıf ve lisans
dosyası NOTICE'a girer. Bağımsız (kendi eğittiğimiz) modellerde bu alan yoktur ve NOTICE'a hiçbir şey eklenmez.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

THIRD_PARTY = """Üçüncü taraf bileşenler
  sherpa-onnx  — Apache License 2.0
  Silero VAD   — MIT License
  damga        — Apache License 2.0
  PySide6 (Qt) — LGPL v3
  Tabler Icons — MIT License
  FFmpeg (Qt Multimedia içinde) — LGPL v2.1 veya üzeri
  pynput       — LGPL v3
  sounddevice  — MIT License
  soundfile / libsndfile — BSD / LGPL v2.1
  RapidFuzz    — MIT License
  cryptography — Apache License 2.0 / BSD
"""


def shipped_models() -> list[str]:
    """Kurulumun paketlediği model klasörleri (installer/setup.iss: Source: "..\\models\\<ad>\\*")."""
    iss = (ROOT / "installer" / "setup.iss").read_text(encoding="utf-8")
    return re.findall(r'^Source:\s*"\.\.\\models\\([^\\"]+)\\\*"', iss, flags=re.M)


def build_notice() -> str:
    lines = ["Tıbbi Dikte", "===========", ""]
    for name in shipped_models():
        spec_file = ROOT / "models" / name / "model.json"
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
        if spec.get("attribution"):
            lic_name = spec.get("license_file", "LICENSE")  # "" = lisans dosyası paketlenmez
            lic = spec_file.parent / lic_name if lic_name else None
            rel = f"models\\{name}\\{lic_name}" if lic is not None and lic.exists() else ""
            lines += [f"{spec.get('name', name)}: {spec['attribution']}",
                      f"  Lisans: {spec.get('license', '')}" + (f" — {rel}" if rel else ""), ""]
    return "\n".join(lines) + "\n" + THIRD_PARTY


def main() -> int:
    out = ROOT / "NOTICE.txt"
    out.write_text(build_notice(), encoding="utf-8")
    print(out.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
