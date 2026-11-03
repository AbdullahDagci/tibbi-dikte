"""NOTICE.txt'yi paketlenecek modellerden üretir (build.ps1 çağırır).

Bir modelin model.json'unda "attribution" varsa (ör. mihu türevi modeller), lisansı gereği atıf ve lisans
dosyası NOTICE'a girer. Bağımsız (kendi eğittiğimiz) modellerde bu alan yoktur ve NOTICE'a hiçbir şey eklenmez.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

THIRD_PARTY = """Üçüncü taraf bileşenler
  sherpa-onnx  — Apache License 2.0
  Silero VAD   — MIT License
  damga        — Apache License 2.0
  PySide6 (Qt) — LGPL v3
  pynput       — LGPL v3
  sounddevice  — MIT License
  soundfile / libsndfile — BSD / LGPL v2.1
  RapidFuzz    — MIT License
  cryptography — Apache License 2.0 / BSD
"""


def main() -> int:
    lines = ["Tıbbi Dikte", "===========", ""]
    for spec_file in sorted((ROOT / "models").glob("*/model.json")):
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
        if spec.get("attribution"):
            lic = spec_file.parent / "LICENSE"
            rel = f"models\\{spec_file.parent.name}\\LICENSE" if lic.exists() else ""
            lines += [f"{spec.get('name', spec_file.parent.name)}: {spec['attribution']}",
                      f"  Lisans: {spec.get('license', '')}" + (f" — {rel}" if rel else ""), ""]
    out = ROOT / "NOTICE.txt"
    out.write_text("\n".join(lines) + "\n" + THIRD_PARTY, encoding="utf-8")
    print(out.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
