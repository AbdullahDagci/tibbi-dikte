"""Çevrimdışı ürün anahtarı doğrulama (Ed25519).

Anahtar = Base32( yük | imza ), 5'li gruplar hâlinde tire ile ayrılır.
Yük (17 bayt):  sürüm(1) | makine özeti(10) | bitiş günü(2, 2020-01-01'den gün; 0 = süresiz) | müşteri no(4)
İmza: 64 bayt Ed25519 — özel anahtar yalnızca geliştiricide (tools/keygen.py).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from ..paths import resource_dir, user_dir

VERSION = 1
EPOCH = dt.date(2020, 1, 1)
PAYLOAD_FMT = ">B10sHI"
PAYLOAD_LEN = struct.calcsize(PAYLOAD_FMT)
SIG_LEN = 64
LICENSE_FILE = user_dir() / "license.key"
_LAST_SEEN_FILE = user_dir() / ".ls"
# Demo anahtarı: makine alanı sıfır -> her bilgisayarda çalışır, ama süreli olmak ve en fazla DEMO_MAX_DAYS
# gün geçerli olmak zorundadır (müşteriye kurulumla birlikte e-postayla gönderilebilir).
DEMO_MACHINE = bytes(10)
DEMO_MAX_DAYS = 31


# ------------------------------------------------------------------ makine kimliği
def _reg(path: str, name: str) -> str:
    if sys.platform != "win32":
        return ""
    import winreg
    for view in (winreg.KEY_WOW64_64KEY, 0):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | view) as k:
                return str(winreg.QueryValueEx(k, name)[0])
        except OSError:
            continue
    return ""


def machine_digest() -> bytes:
    parts = [
        _reg(r"SOFTWARE\Microsoft\Cryptography", "MachineGuid"),
        _reg(r"HARDWARE\DESCRIPTION\System\BIOS", "BaseBoardManufacturer"),
        _reg(r"HARDWARE\DESCRIPTION\System\BIOS", "BaseBoardProduct"),
        _reg(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemProductName"),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).digest()[:10]


def _group(s: str, n: int = 4) -> str:
    return "-".join(s[i:i + n] for i in range(0, len(s), n))


def machine_code() -> str:
    """Kullanıcıya gösterilen ve satıcıya iletilen kod, ör. ABCD-EFGH-IJKL-MNOP."""
    return _group(base64.b32encode(machine_digest()).decode().rstrip("="))


def parse_machine_code(code: str) -> bytes:
    raw = code.replace("-", "").replace(" ", "").upper()
    raw += "=" * (-len(raw) % 8)
    d = base64.b32decode(raw)
    if len(d) != 10:
        raise ValueError("Geçersiz makine kodu")
    return d


# ------------------------------------------------------------------ anahtar biçimi
def encode_key(payload: bytes, signature: bytes) -> str:
    return _group(base64.b32encode(payload + signature).decode().rstrip("="), 5)


def decode_key(key: str) -> tuple[bytes, bytes]:
    raw = "".join(ch for ch in key.upper() if ch.isalnum())
    raw += "=" * (-len(raw) % 8)
    data = base64.b32decode(raw)
    if len(data) != PAYLOAD_LEN + SIG_LEN:
        raise ValueError("Anahtar uzunluğu hatalı")
    return data[:PAYLOAD_LEN], data[PAYLOAD_LEN:]


def pack_payload(machine: bytes, expires: dt.date | None, customer_id: int) -> bytes:
    days = 0 if expires is None else (expires - EPOCH).days
    if not 0 <= days < 65536:
        raise ValueError("Bitiş tarihi aralık dışında")
    return struct.pack(PAYLOAD_FMT, VERSION, machine, days, customer_id)


@dataclass
class LicenseInfo:
    valid: bool
    message: str
    expires: dt.date | None = None
    customer_id: int | None = None
    demo: bool = False
    days_left: int | None = None


def _public_key() -> Ed25519PublicKey:
    key = load_pem_public_key((resource_dir() / "licensing" / "public_key.pem").read_bytes())
    assert isinstance(key, Ed25519PublicKey)
    return key


def _clock_rolled_back(today: dt.date) -> bool:
    try:
        last = dt.date.fromisoformat(_LAST_SEEN_FILE.read_text().strip())
    except (OSError, ValueError):
        last = None
    if last and today < last - dt.timedelta(days=1):
        return True
    if last is None or today > last:
        try:
            _LAST_SEEN_FILE.write_text(today.isoformat())
        except OSError:
            pass
    return False


def verify(key: str, *, public_key: Ed25519PublicKey | None = None, machine: bytes | None = None,
           today: dt.date | None = None, check_clock: bool = True) -> LicenseInfo:
    try:
        payload, sig = decode_key(key)
    except (ValueError, base64.binascii.Error):
        return LicenseInfo(False, "Anahtar biçimi geçersiz.")
    try:
        (public_key or _public_key()).verify(sig, payload)
    except InvalidSignature:
        return LicenseInfo(False, "Anahtar geçersiz.")
    ver, mach, days, cust = struct.unpack(PAYLOAD_FMT, payload)
    if ver != VERSION:
        return LicenseInfo(False, "Anahtar sürümü desteklenmiyor.")
    demo = mach == DEMO_MACHINE
    if not demo and mach != (machine if machine is not None else machine_digest()):
        return LicenseInfo(False, "Bu anahtar başka bir bilgisayar için üretilmiş.")
    today = today or dt.date.today()
    expires = None if days == 0 else EPOCH + dt.timedelta(days=days)
    if demo and expires is None:
        return LicenseInfo(False, "Geçersiz deneme anahtarı (süresiz olamaz).", None, cust, demo=True)
    if demo and (expires - today).days > DEMO_MAX_DAYS:
        return LicenseInfo(False, f"Deneme anahtarı en fazla {DEMO_MAX_DAYS} gün geçerli olabilir.", expires, cust,
                           demo=True)
    if check_clock and _clock_rolled_back(today):
        return LicenseInfo(False, "Sistem saati geri alınmış görünüyor.", expires, cust)
    if expires and today > expires:
        what = "Deneme süresi" if demo else "Lisans süresi"
        return LicenseInfo(False, f"{what} {expires:%d.%m.%Y} tarihinde doldu.", expires, cust, demo=demo)
    left = None if expires is None else (expires - today).days
    if demo:
        msg = f"Deneme lisansı — {left} gün kaldı ({expires:%d.%m.%Y} tarihine kadar)"
    else:
        msg = "Süresiz lisans" if expires is None else f"Lisans {expires:%d.%m.%Y} tarihine kadar geçerli"
    return LicenseInfo(True, msg, expires, cust, demo=demo, days_left=left)


# ------------------------------------------------------------------ kayıtlı lisans
def load_saved() -> str | None:
    try:
        return LICENSE_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def save(key: str) -> None:
    LICENSE_FILE.write_text(key.strip(), encoding="utf-8")


def current() -> LicenseInfo:
    key = load_saved()
    if not key:
        return LicenseInfo(False, "Ürün anahtarı girilmemiş.")
    return verify(key)


def activate(key: str) -> LicenseInfo:
    info = verify(key)
    if info.valid:
        save(key)
    return info
