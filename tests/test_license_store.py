"""Lisans kayıtları: okuma, anahtar üretme, yenileme ve kalan gün hesabı."""
import csv
import datetime as dt
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.licensing import license as lic
from tools import license_store as store

ROOT = Path(__file__).resolve().parent.parent
PRIV = Ed25519PrivateKey.generate()
PUB = PRIV.public_key()
TODAY = dt.date(2026, 11, 7)
MACHINE = bytes(range(10))
CODE = lic._group(lic.base64.b32encode(MACHINE).decode().rstrip("="))
HEADER = "customer_id,customer,machine_code,expires,issued,key\n"


@pytest.fixture
def paths(tmp_path):
    private = tmp_path / "private.pem"
    private.write_bytes(PRIV.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return private, tmp_path / "issued.csv"


def issue(paths, **kw):
    private, log = paths
    args = dict(customer="X Hastanesi", machine_code=CODE, expires=dt.date(2026, 11, 21), today=TODAY)
    return store.issue(**{**args, **kw}, private_key=private, log=log)


def record(cid=1, customer="X", machine=CODE, expires=dt.date(2026, 12, 1), issued=TODAY, key="K"):
    return store.LicenseRecord(cid, customer, machine, expires, issued, key)


# ------------------------------------------------------------ okuma
def test_missing_file_is_an_empty_list(tmp_path):
    assert store.load_records(tmp_path / "yok.csv") == []


def test_records_are_read_with_dates_and_turkish_text(tmp_path):
    f = tmp_path / "k.csv"
    f.write_text(HEADER + "1,Geliştirici Çalışması,ABCD-EFGH-IJKL-MNOP,süresiz,2026-11-03,AAA\n"
                          "2,Demo,DEMO (her bilgisayar),2026-11-20,2026-11-06,BBB\n", encoding="utf-8")
    first, second = store.load_records(f)
    assert first.customer == "Geliştirici Çalışması" and first.expires is None and first.issued == dt.date(2026, 11, 3)
    assert second.expires == dt.date(2026, 11, 20) and second.is_demo and not first.is_demo


def test_file_saved_with_bom_is_read(tmp_path):
    f = tmp_path / "k.csv"
    f.write_text(HEADER + "1,Ç,DEMO (her bilgisayar),2026-11-20,2026-11-06,BBB\n", encoding="utf-8-sig")
    assert store.load_records(f)[0].customer_id == 1


@pytest.mark.parametrize("content", ["customer_id;customer;expires\n1;X;2026-01-01\n",
                                     HEADER + "bir,X,KOD,tarih-degil,2026-11-06,K\n"])
def test_unreadable_file_reports_an_error_instead_of_hiding_rows(tmp_path, content):
    f = tmp_path / "k.csv"
    f.write_text(content, encoding="utf-8")
    with pytest.raises(store.LicenseError):
        store.load_records(f)


# ------------------------------------------------------------ anahtar üretme
def test_machine_key_verifies_only_on_that_machine_and_is_logged(paths):
    rec = issue(paths)
    info = lic.verify(rec.key, public_key=PUB, machine=MACHINE, today=TODAY, check_clock=False)
    assert info.valid and info.days_left == 14 and not info.demo and info.customer_id == rec.customer_id
    assert not lic.verify(rec.key, public_key=PUB, machine=b"\x11" * 10, today=TODAY, check_clock=False).valid
    assert store.load_records(paths[1]) == [rec]


def test_log_keeps_the_format_of_the_command_line_tool(paths):
    rec = issue(paths)
    with paths[1].open(encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    assert row == {"customer_id": "1", "customer": "X Hastanesi", "machine_code": CODE, "expires": "2026-11-21",
                   "issued": "2026-11-07", "key": rec.key}


def test_customer_numbers_increase(paths):
    assert [issue(paths).customer_id, issue(paths).customer_id] == [1, 2]


def test_perpetual_key(paths):
    rec = issue(paths, expires=None)
    assert rec.expires is None
    assert store.load_records(paths[1])[0].expires is None
    assert lic.verify(rec.key, public_key=PUB, machine=MACHINE, today=TODAY, check_clock=False).valid


def test_demo_key_works_everywhere_but_is_limited(paths):
    rec = issue(paths, machine_code=None, demo=True, expires=TODAY + dt.timedelta(days=31))
    assert rec.is_demo
    assert lic.verify(rec.key, public_key=PUB, machine=b"\x11" * 10, today=TODAY, check_clock=False).demo


@pytest.mark.parametrize("kw", [
    {"customer": "   "},
    {"machine_code": ""},
    {"machine_code": "bozuk kod"},
    {"expires": TODAY},
    {"expires": TODAY - dt.timedelta(days=1)},
    {"machine_code": None, "demo": True, "expires": TODAY + dt.timedelta(days=32)},
    {"machine_code": None, "demo": True, "expires": None},
])
def test_invalid_requests_are_refused_and_not_logged(paths, kw):
    with pytest.raises(store.LicenseError):
        issue(paths, **kw)
    assert not paths[1].exists()


def test_missing_private_key_is_reported(paths):
    paths[0].unlink()
    with pytest.raises(store.LicenseError, match="Özel anahtar"):
        issue(paths)
    assert not paths[1].exists()


# ------------------------------------------------------------ kalan gün ve durum
def status_of(rec, today=TODAY):
    return store.build_rows([rec], today)[0]


@pytest.mark.parametrize("expires,status,days", [
    (TODAY + dt.timedelta(days=31), store.ACTIVE, 31),
    (TODAY + dt.timedelta(days=30), store.EXPIRING, 30),
    (TODAY, store.EXPIRING, 0),
    (TODAY - dt.timedelta(days=1), store.EXPIRED, -1),
    (None, store.PERPETUAL, None),
])
def test_status_and_days_left(expires, status, days):
    row = status_of(record(expires=expires))
    assert row.status == status and row.days_left == days


def test_renewal_replaces_older_key_of_same_customer_and_machine():
    old = record(1, expires=dt.date(2026, 11, 20))
    new = record(2, expires=dt.date(2027, 11, 20))
    rows = {r.record.customer_id: r for r in store.build_rows([old, new], TODAY)}
    assert rows[1].status == store.RENEWED and rows[1].days_left is None
    assert rows[2].status == store.ACTIVE


def test_other_machine_of_same_customer_is_not_a_renewal():
    other = lic._group(lic.base64.b32encode(b"\x11" * 10).decode().rstrip("="))
    rows = store.build_rows([record(1), record(2, machine=other)], TODAY)
    assert all(r.status != store.RENEWED for r in rows)


def test_rows_show_soonest_expiry_first_and_renewed_last():
    rows = store.build_rows([record(1, "Eski", expires=dt.date(2026, 11, 8)), record(2, "Eski", expires=dt.date(2027, 1, 1)),
                             record(3, "Süresiz", machine="A", expires=None),
                             record(4, "Yakın", machine="B", expires=dt.date(2026, 11, 10)),
                             record(5, "Bitti", machine="C", expires=dt.date(2026, 11, 1))], TODAY)
    assert [r.record.customer_id for r in rows] == [5, 4, 2, 3, 1]


def test_summary_ignores_renewed_keys():
    rows = store.build_rows([record(1, "A", expires=dt.date(2026, 11, 8)), record(2, "A", expires=dt.date(2027, 6, 1)),
                             record(3, "B", machine="B", expires=dt.date(2026, 11, 10)),
                             record(4, "C", machine="C", expires=dt.date(2026, 11, 1)),
                             record(5, "D", machine="D", expires=None)], TODAY)
    s = store.summarize(rows)
    assert (s.active, s.expiring, s.expired, s.total_keys) == (3, 1, 1, 5)


# ------------------------------------------------------------ yenileme
def test_renewal_continues_from_current_expiry_if_still_valid():
    assert store.renewal_start(record(expires=dt.date(2026, 12, 1)), TODAY) == dt.date(2026, 12, 1)


@pytest.mark.parametrize("expires", [dt.date(2026, 11, 1), None])
def test_renewal_starts_today_if_expired_or_perpetual(expires):
    assert store.renewal_start(record(expires=expires), TODAY) == TODAY


def test_latest_record_of_a_license_is_found():
    old, new = record(1), record(2, expires=dt.date(2027, 1, 1))
    assert store.latest_of([old, new], old) is new


# ------------------------------------------------------------ müşteri paketi
def test_manager_is_never_packaged_for_customers():
    spec = (ROOT / "TibbiDikte.spec").read_text(encoding="utf-8")
    assert "license_manager" not in spec and "license_store" not in spec and "private_key" not in spec
    for path in (ROOT / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "license_store" not in source and "license_manager" not in source, path


def test_rows_count_earlier_keys_of_a_license():
    rows = {r.record.customer_id: r for r in store.build_rows(
        [record(1, expires=dt.date(2026, 11, 20)), record(2, expires=dt.date(2027, 1, 1)), record(3, expires=dt.date(2027, 6, 1)),
         record(4, "Başka", machine="B")], TODAY)}
    assert rows[3].renewals == 2 and rows[1].renewals == 0 and rows[4].renewals == 0


def test_current_rows_leave_out_renewed_keys():
    rows = store.build_rows([record(1, expires=dt.date(2026, 11, 20)), record(2, expires=dt.date(2027, 1, 1))], TODAY)
    assert [r.record.customer_id for r in store.current_rows(rows)] == [2]


# ------------------------------------------------------------ listeden kaldırma
def test_removing_keeps_other_records_unchanged(paths):
    first, second = issue(paths, customer="A"), issue(paths, customer="B")
    store.remove([first], log=paths[1])
    assert store.load_records(paths[1]) == [second]


def test_removed_key_is_kept_in_archive_not_lost(paths):
    rec = issue(paths)
    store.remove([rec], log=paths[1])
    assert store.load_records(store.removed_log(paths[1])) == [rec]


def test_customer_number_is_not_reused_after_removal(paths):
    rec = issue(paths)
    store.remove([rec], log=paths[1])
    assert issue(paths).customer_id == rec.customer_id + 1


def test_removing_last_record_leaves_empty_readable_file(paths):
    rec = issue(paths)
    store.remove([rec], log=paths[1])
    assert store.load_records(paths[1]) == []
    assert issue(paths).customer == "X Hastanesi"


def test_removal_leaves_no_temporary_file(paths):
    store.remove([issue(paths)], log=paths[1])
    assert sorted(f.name for f in paths[1].parent.glob("*issued*")) == ["issued.csv", "issued_removed.csv"]


def test_all_keys_of_a_license_are_found():
    old, new, other = record(1), record(2), record(3, customer="Başka", machine="B")
    assert store.keys_of([old, new, other], new) == [old, new]


def test_key_files_never_reach_public_repository():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "tools/issued_keys*" in ignore
