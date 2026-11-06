"""Ürün anahtarı üretici — YALNIZCA geliştirici/satıcı bilgisayarında kullanılır.
Günlük kullanım için ekranlı sürüm: tools\\LisansYoneticisi.cmd

İlk kurulum (bir kez):
    python tools/keygen.py init
    -> tools/private_key.pem (GİZLİ, yedekleyin, asla paylaşmayın / pakete koymayın)
    -> app/licensing/public_key.pem (uygulamaya gömülür)

Anahtar üretme (müşteri, uygulamadaki "Makine kodu"nu size iletir; her müşteriye ayrı anahtar):
    python tools/keygen.py issue ABCD-EFGH-IJKL-MNOP --customer "X Hastanesi (deneme)" --days 14
    python tools/keygen.py issue ABCD-EFGH-IJKL-MNOP --customer "Dr. X Klinik" --days 365
    python tools/keygen.py issue ABCD-EFGH-IJKL-MNOP --customer "Y Hastanesi" --until 2027-12-31
    python tools/keygen.py issue ABCD-EFGH-IJKL-MNOP --customer "Z" --perpetual

Herkese açık demo anahtarı — YALNIZCA kendi sunumlarınız için, müşteriye verilmez. Her bilgisayarda çalışır, en fazla
31 gün geçerlidir ve iptal edilemez:
    python tools/keygen.py issue --demo --customer "Kendi sunumum" --days 14
Üretilen her anahtar tools/issued_keys.csv dosyasına kaydedilir.
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import license_store  # noqa: E402

PRIVATE = ROOT / "tools" / "private_key.pem"
PUBLIC = ROOT / "app" / "licensing" / "public_key.pem"
LOG = ROOT / "tools" / "issued_keys.csv"


def cmd_init(_a) -> int:
    if PRIVATE.exists():
        print(f"Zaten var: {PRIVATE} — üzerine yazılmadı (yazılırsa eski anahtarlar geçersiz olur).")
        return 1
    k = Ed25519PrivateKey.generate()
    PRIVATE.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    PUBLIC.write_bytes(k.public_key().public_bytes(serialization.Encoding.PEM,
                                                   serialization.PublicFormat.SubjectPublicKeyInfo))
    print(f"Özel anahtar: {PRIVATE}\nAçık anahtar: {PUBLIC}")
    return 0


def cmd_issue(a) -> int:
    if a.perpetual:
        expires = None
    elif a.until:
        expires = dt.date.fromisoformat(a.until)
    else:
        days = a.days if a.days is not None else (14 if a.demo else 365)
        expires = dt.date.today() + dt.timedelta(days=days)
    try:
        record = license_store.issue(a.customer, a.machine_code, a.demo, expires, private_key=PRIVATE, log=LOG)
    except license_store.LicenseError as e:
        raise SystemExit(str(e)) from e
    if a.demo:
        print("UYARI: Bu anahtar her bilgisayarda çalışır ve iptal edilemez. Müşteriye makine koduna bağlı anahtar verin.",
              file=sys.stderr)
    print(record.key)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    p = sub.add_parser("issue")
    p.add_argument("machine_code", nargs="?")
    p.add_argument("--demo", action="store_true", help="her bilgisayarda çalışan süreli anahtar (yalnız kendi sunumlarınız için)")
    p.add_argument("--customer", required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--days", type=int, default=None, help="varsayılan: 365 (demo: 14)")
    g.add_argument("--until")
    g.add_argument("--perpetual", action="store_true")
    p.set_defaults(fn=cmd_issue)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
