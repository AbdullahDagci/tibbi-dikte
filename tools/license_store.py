"""Verilen lisansların kaydı ve yeni anahtar üretimi (keygen.py ile license_manager.py ortak kullanır).

Yalnızca geliştirici bilgisayarında çalışır: özel anahtar ve kayıt dosyası git'e girmez, müşteri paketine konmaz.
"""
from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from app.licensing.license import (DEMO_MACHINE, DEMO_MAX_DAYS, encode_key, machine_code_text, pack_payload,
                                   parse_machine_code)

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_KEY = ROOT / "tools" / "private_key.pem"
ISSUED_KEYS = ROOT / "tools" / "issued_keys.csv"
FIELDS = ["customer_id", "customer", "machine_code", "expires", "issued", "key"]
ANY_MACHINE = "DEMO (her bilgisayar)"
NO_EXPIRY = "süresiz"
EXPIRING_DAYS = 30  # bundan az gün kaldıysa "Bitiyor"

ACTIVE, EXPIRING, EXPIRED, PERPETUAL, RENEWED = "Etkin", "Bitiyor", "Süresi doldu", "Süresiz", "Yenilendi"


class LicenseError(ValueError):
    """Kullanıcıya gösterilecek anlaşılır hata."""


@dataclass(frozen=True)
class LicenseRecord:
    customer_id: int
    customer: str
    machine_code: str
    expires: dt.date | None
    issued: dt.date
    key: str

    @property
    def is_demo(self) -> bool:
        return self.machine_code == ANY_MACHINE


@dataclass(frozen=True)
class LicenseRow:
    record: LicenseRecord
    status: str
    days_left: int | None
    renewals: int = 0  # bu lisansın en yeni anahtarından önce üretilmiş anahtar sayısı


@dataclass(frozen=True)
class Summary:
    active: int        # süresi dolmamış geçerli lisanslar (bitmek üzere olanlar dahil)
    expiring: int
    expired: int
    total_keys: int    # yenilenenler dahil üretilen tüm anahtarlar


# ------------------------------------------------------------------ kayıt dosyası
def _parse_row(row: dict) -> LicenseRecord:
    expires = None if row["expires"] == NO_EXPIRY else dt.date.fromisoformat(row["expires"])
    return LicenseRecord(int(row["customer_id"]), row["customer"], row["machine_code"], expires,
                         dt.date.fromisoformat(row["issued"]), row["key"])


def load_records(log: Path = ISSUED_KEYS) -> list[LicenseRecord]:
    """Dosya yoksa boş liste. Okunamayan satır sessizce atlanmaz: kayıp lisans fark edilmeden kalmasın."""
    if not log.exists():
        return []
    try:
        with log.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return []
            missing = set(FIELDS) - set(reader.fieldnames)
            if missing:
                raise ValueError(f"eksik sütunlar: {', '.join(sorted(missing))}")
            return [_parse_row(row) for row in reader]
    except (OSError, ValueError, TypeError) as e:
        raise LicenseError(f"Lisans kayıtları okunamadı ({log.name}): {e}") from e


def has_private_key(private_key: Path = PRIVATE_KEY) -> bool:
    return private_key.is_file()


# ------------------------------------------------------------------ anahtar üretme
def issue(customer: str, machine_code: str | None = None, demo: bool = False, expires: dt.date | None = None, *,
          private_key: Path = PRIVATE_KEY, log: Path = ISSUED_KEYS, today: dt.date | None = None) -> LicenseRecord:
    """Yeni anahtar üretir ve kayda ekler. expires=None süresizdir; yenileme de yeni bir kayıttır."""
    today = today or dt.date.today()
    customer = customer.strip()
    if not customer:
        raise LicenseError("Müşteri adı gerekli.")
    if expires is not None and expires <= today:
        raise LicenseError("Bitiş tarihi bugünden sonra olmalı.")
    if demo:
        if expires is None or (expires - today).days > DEMO_MAX_DAYS:
            raise LicenseError(f"Her bilgisayarda çalışan anahtar en fazla {DEMO_MAX_DAYS} gün olabilir.")
        machine, machine_label = DEMO_MACHINE, ANY_MACHINE
    else:
        if not (machine_code or "").strip():
            raise LicenseError("Makine kodu gerekli.")
        try:
            machine = parse_machine_code(machine_code)
        except ValueError as e:
            raise LicenseError("Makine kodu geçersiz. Müşterinin Lisans sayfasındaki kodu aynen yazın.") from e
        machine_label = machine_code_text(machine)
    try:
        signer = serialization.load_pem_private_key(private_key.read_bytes(), password=None)
    except (OSError, ValueError) as e:
        raise LicenseError(f"Özel anahtar okunamadı: {private_key}") from e
    records = load_records(log)
    customer_id = max((r.customer_id for r in records), default=0) + 1
    payload = pack_payload(machine, expires, customer_id, issued=today)
    record = LicenseRecord(customer_id, customer, machine_label, expires, today, encode_key(payload, signer.sign(payload)))
    new_file = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(FIELDS)
        writer.writerow([record.customer_id, record.customer, record.machine_code, expires or NO_EXPIRY, today, record.key])
    return record


# ------------------------------------------------------------------ durum ve kalan gün
def _license_id(record: LicenseRecord) -> tuple[str, str]:
    """Aynı müşterinin aynı bilgisayardaki anahtarları aynı lisansın yenilemeleridir."""
    return record.customer.strip().casefold(), record.machine_code


def latest_of(records: list[LicenseRecord], record: LicenseRecord) -> LicenseRecord:
    same = [r for r in records if _license_id(r) == _license_id(record)]
    return max(same, key=lambda r: r.customer_id, default=record)


def build_rows(records: list[LicenseRecord], today: dt.date) -> list[LicenseRow]:
    """Önce süresi en yakın olanlar, sonra süresizler, en sonda yenilenmiş eski anahtarlar."""
    rows = []
    for record in records:
        renewals = sum(_license_id(r) == _license_id(record) for r in records) - 1
        if latest_of(records, record) is not record:
            rows.append(LicenseRow(record, RENEWED, None))
        elif record.expires is None:
            rows.append(LicenseRow(record, PERPETUAL, None, renewals))
        else:
            days = (record.expires - today).days
            status = EXPIRED if days < 0 else EXPIRING if days <= EXPIRING_DAYS else ACTIVE
            rows.append(LicenseRow(record, status, days, renewals))
    rows.sort(key=lambda r: (r.status == RENEWED, r.days_left is None, r.days_left or 0, -r.record.customer_id))
    return rows


def current_rows(rows: list[LicenseRow]) -> list[LicenseRow]:
    """Her lisansın yalnızca en yeni anahtarı: yenileme var olan lisansı günceller, yeni lisans sayılmaz."""
    return [r for r in rows if r.status != RENEWED]


def summarize(rows: list[LicenseRow]) -> Summary:
    count = {status: sum(r.status == status for r in rows) for status in (ACTIVE, EXPIRING, EXPIRED, PERPETUAL)}
    return Summary(count[ACTIVE] + count[EXPIRING] + count[PERPETUAL], count[EXPIRING], count[EXPIRED], len(rows))


def renewal_start(record: LicenseRecord, today: dt.date) -> dt.date:
    """Süresi dolmadıysa yeni süre mevcut bitişin üzerine eklenir: müşteri kalan günlerini kaybetmez."""
    return record.expires if record.expires is not None and record.expires > today else today
