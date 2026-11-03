"""Ürün anahtarı üretici — YALNIZCA geliştirici/satıcı bilgisayarında kullanılır.

İlk kurulum (bir kez):
    python tools/keygen.py init
    -> tools/private_key.pem (GİZLİ, yedekleyin, asla paylaşmayın / pakete koymayın)
    -> app/licensing/public_key.pem (uygulamaya gömülür)

Anahtar üretme (müşteri, uygulamadaki "Makine kodu"nu size iletir):
    python tools/keygen.py issue ABCD-EFGH-IJKL-MNOP --customer "Dr. X Klinik" --days 365
    python tools/keygen.py issue ABCD-EFGH-IJKL-MNOP --customer "Y Hastanesi" --until 2027-12-31
    python tools/keygen.py issue ABCD-EFGH-IJKL-MNOP --customer "Z" --perpetual
Üretilen her anahtar tools/issued_keys.csv dosyasına kaydedilir.
"""
import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.licensing.license import encode_key, pack_payload, parse_machine_code  # noqa: E402

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


def _next_customer_id() -> int:
    if not LOG.exists():
        return 1
    with LOG.open(encoding="utf-8") as f:
        ids = [int(r["customer_id"]) for r in csv.DictReader(f)]
    return max(ids, default=0) + 1


def cmd_issue(a) -> int:
    key = serialization.load_pem_private_key(PRIVATE.read_bytes(), password=None)
    if a.perpetual:
        expires = None
    elif a.until:
        expires = dt.date.fromisoformat(a.until)
    else:
        expires = dt.date.today() + dt.timedelta(days=a.days)
    cid = _next_customer_id()
    payload = pack_payload(parse_machine_code(a.machine_code), expires, cid)
    product_key = encode_key(payload, key.sign(payload))
    new = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["customer_id", "customer", "machine_code", "expires", "issued", "key"])
        w.writerow([cid, a.customer, a.machine_code, expires or "süresiz", dt.date.today(), product_key])
    print(product_key)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    p = sub.add_parser("issue")
    p.add_argument("machine_code")
    p.add_argument("--customer", required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--days", type=int, default=365)
    g.add_argument("--until")
    g.add_argument("--perpetual", action="store_true")
    p.set_defaults(fn=cmd_issue)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
