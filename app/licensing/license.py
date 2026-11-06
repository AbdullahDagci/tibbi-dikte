"""Çevrimdışı ürün anahtarı doğrulama (Ed25519).

Anahtar = Base32( yük | imza ), 5'li gruplar hâlinde tire ile ayrılır.
Yük (19 bayt):  sürüm(1) | makine özeti(10) | bitiş günü(2, 2020-01-01'den gün; 0 = süresiz) | verilme günü(2)
                | müşteri no(4). Sürüm 1 anahtarlarda verilme günü yoktur (17 bayt), onlar da geçerlidir.
İmza: 64 bayt Ed25519 — özel anahtar yalnızca geliştiricide (tools/keygen.py).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import logging
import re
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from ..paths import resource_dir, user_dir

log = logging.getLogger(__name__)

VERSION = 2
EPOCH = dt.date(2020, 1, 1)
PAYLOAD_FMT = ">B10sHHI"
PAYLOAD_LEN = struct.calcsize(PAYLOAD_FMT)
_PAYLOAD_V1_FMT = ">B10sHI"
_PAYLOAD_V1_LEN = struct.calcsize(_PAYLOAD_V1_FMT)
SIG_LEN = 64
LICENSE_FILE = user_dir() / "license.key"
_LAST_SEEN_FILE = user_dir() / ".ls"
_STATE_KEY = r"Software\TibbiDikte"  # son görülen tarihin ikinci kopyası (kayıt defteri, kullanıcıya özel)
_STATE_VALUE = "ls"
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


def machine_code_text(digest: bytes) -> str:
    return _group(base64.b32encode(digest).decode().rstrip("="))


def machine_code() -> str:
    """Kullanıcıya gösterilen ve satıcıya iletilen kod, ör. ABCD-EFGH-IJKL-MNOP."""
    return machine_code_text(machine_digest())


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
    if len(data) - SIG_LEN not in (PAYLOAD_LEN, _PAYLOAD_V1_LEN):
        raise ValueError("Anahtar uzunluğu hatalı")
    return data[:-SIG_LEN], data[-SIG_LEN:]


def pack_payload(machine: bytes, expires: dt.date | None, customer_id: int, issued: dt.date | None = None) -> bytes:
    days = 0 if expires is None else (expires - EPOCH).days
    issued_days = ((issued or dt.date.today()) - EPOCH).days
    if not 0 <= days < 65536 or not 0 <= issued_days < 65536:
        raise ValueError("Tarih aralık dışında")
    return struct.pack(PAYLOAD_FMT, VERSION, machine, days, issued_days, customer_id)


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


# ------------------------------------------------------------------ saat denetimi
# Süreli anahtarlarda saat geri alınırsa süre uzamaz: Windows her saat değişikliğini Sistem günlüğüne yazar
# (yönetici yetkisi olmadan okunur), geri alınan süre bugüne eklenir. Son görülen tarih ikinci güvencedir.
_CLOCK_EVENT_QUERY = "*[System[Provider[@Name='Microsoft-Windows-Kernel-General'] and (EventID=1)]]"
_CLOCK_EVENT_RE = re.compile(r"""Name=['"]NewTime['"]>([^<]+)</Data>\s*<Data Name=['"]OldTime['"]>([^<]+)</Data>""")
_V1_ROLLBACK_WINDOW_DAYS = 366  # verilme tarihi olmayan eski anahtarlarda geriye bakılan süre


def _parse_clock_events(xml: str) -> list[tuple[dt.datetime, dt.datetime]]:
    """Saat değişikliği kayıtlarından yalnızca geri alınanlar: (eski saat, yeni saat)."""
    found = []
    for new_text, old_text in _CLOCK_EVENT_RE.findall(xml):
        try:
            new, old = dt.datetime.fromisoformat(new_text), dt.datetime.fromisoformat(old_text)
        except ValueError:
            continue
        if old > new:
            found.append((old, new))
    return found


def _clock_rollbacks() -> list[tuple[dt.datetime, dt.datetime]]:
    if sys.platform != "win32":
        return []
    try:
        done = subprocess.run(["wevtutil", "qe", "System", f"/q:{_CLOCK_EVENT_QUERY}", "/f:xml", "/rd:true", "/c:5000"],
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Saat değişikliği kayıtları okunamadı: %s", e)
        return []
    return _parse_clock_events(done.stdout.decode("utf-8", "ignore"))


def _read_state_texts() -> list[str]:
    texts = []
    try:
        texts.append(_LAST_SEEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STATE_KEY) as k:
                texts.append(str(winreg.QueryValueEx(k, _STATE_VALUE)[0]))
        except OSError:
            pass
    return texts


def _last_seen(key_id: str) -> dt.date | None:
    """İki kopyadan en ileri tarih. Başka anahtara ait kayıt sayılmaz: yeni anahtar eski kaydın altında kalmasın."""
    best = None
    for text in _read_state_texts():
        owner, _, day = text.strip().partition("=")
        if owner != key_id:
            continue
        try:
            seen = dt.date.fromisoformat(day)
        except ValueError:
            continue
        best = seen if best is None else max(best, seen)
    return best


def _remember_seen(key_id: str, day: dt.date) -> None:
    text = f"{key_id}={day.isoformat()}"
    try:
        _LAST_SEEN_FILE.write_text(text, encoding="utf-8")
    except OSError:
        pass
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _STATE_KEY) as k:
                winreg.SetValueEx(k, _STATE_VALUE, 0, winreg.REG_SZ, text)
        except OSError:
            pass


def _trusted_today(key_id: str, today: dt.date, since: dt.date) -> dt.date:
    """Saat geri alındıysa gerçeğe en yakın tarih: bugün + geri alınan süre, son görülen tarihten geri gitmez."""
    rolled = sum((old - new for old, new in _clock_rollbacks() if old.date() >= since), dt.timedelta())
    trusted = today + dt.timedelta(days=rolled.days)
    seen = _last_seen(key_id)
    if seen is not None:
        trusted = max(trusted, seen)
    if trusted != seen:
        _remember_seen(key_id, trusted)
    return trusted


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
    issued = None
    if payload[0] == 1 and len(payload) == _PAYLOAD_V1_LEN:
        _, mach, days, cust = struct.unpack(_PAYLOAD_V1_FMT, payload)
    elif payload[0] == VERSION and len(payload) == PAYLOAD_LEN:
        _, mach, days, issued_days, cust = struct.unpack(PAYLOAD_FMT, payload)
        issued = EPOCH + dt.timedelta(days=issued_days)
    else:
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
    trusted = today
    if check_clock and expires is not None:  # süresiz lisans saatten etkilenmez
        if issued is not None and today < issued - dt.timedelta(days=1):
            return LicenseInfo(False, "Sistem saati geri alınmış görünüyor. Saati düzeltip yeniden deneyin.", expires, cust,
                               demo=demo)
        since = issued or expires - dt.timedelta(days=DEMO_MAX_DAYS if demo else _V1_ROLLBACK_WINDOW_DAYS)
        trusted = _trusted_today(hashlib.sha256(payload).hexdigest()[:16], today, since)
    if expires and trusted > expires:
        what = "Deneme süresi" if demo else "Lisans süresi"
        why = " Sistem saati geri alındığı için süre uzatılmadı." if today <= expires else ""
        return LicenseInfo(False, f"{what} {expires:%d.%m.%Y} tarihinde doldu.{why}", expires, cust, demo=demo)
    left = None if expires is None else (expires - trusted).days
    if demo:
        msg = f"Deneme lisansı — {left} gün kaldı ({expires:%d.%m.%Y} tarihine kadar)"
    else:
        msg = "Süresiz lisans" if expires is None else f"Lisans {expires:%d.%m.%Y} tarihine kadar geçerli ({left} gün kaldı)"
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
