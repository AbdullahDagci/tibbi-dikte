"""Saatle oynayarak lisans süresi uzatılamaz: geri alınan süre Windows kayıtlarından okunup kalan süreden düşülür."""
import csv
import datetime as dt
import importlib.util
from argparse import Namespace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.licensing import license as lic
from app.licensing.license import DEMO_MACHINE, encode_key, pack_payload, verify

winreg = pytest.importorskip("winreg")  # saat koruması Windows kayıtlarını kullanır
ROOT = Path(__file__).resolve().parent.parent
PRIV = Ed25519PrivateKey.generate()
PUB = PRIV.public_key()
MACHINE = bytes(range(10))
ISSUED = dt.date(2026, 11, 1)
EXPIRES = dt.date(2026, 11, 20)
TEST_REG_KEY = r"Software\TibbiDikteTest"


def utc(day, hour=12):
    return dt.datetime(2026, 11, day, hour, tzinfo=dt.timezone.utc)


def make(expires=EXPIRES, issued=ISSUED, machine=MACHINE, cid=7):
    payload = pack_payload(machine, expires, cid, issued=issued)
    return encode_key(payload, PRIV.sign(payload))


def make_v1(expires=EXPIRES, machine=DEMO_MACHINE, cid=2):
    import struct
    days = (expires - lic.EPOCH).days
    payload = struct.pack(">B10sHI", 1, machine, days, cid)
    return encode_key(payload, PRIV.sign(payload))


def check(key, today):
    return verify(key, public_key=PUB, machine=MACHINE, today=today)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Testler gerçek lisans durumuna ve gerçek Windows kayıtlarına bakmaz."""
    monkeypatch.setattr(lic, "_LAST_SEEN_FILE", tmp_path / ".ls")
    monkeypatch.setattr(lic, "_STATE_KEY", TEST_REG_KEY)
    monkeypatch.setattr(lic, "_clock_rollbacks", lambda: [])
    yield
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_REG_KEY)
    except OSError:
        pass


def rollbacks(monkeypatch, *pairs):
    monkeypatch.setattr(lic, "_clock_rollbacks", lambda: list(pairs))


# ------------------------------------------------------------ saat geri alınınca
def test_rolling_clock_back_after_expiry_does_not_revive_license(monkeypatch):
    rollbacks(monkeypatch, (utc(25), utc(16)))
    info = check(make(), dt.date(2026, 11, 16))
    assert not info.valid and "doldu" in info.message and "saat" in info.message.lower()


def test_rolling_clock_back_before_expiry_does_not_add_days(monkeypatch):
    rollbacks(monkeypatch, (utc(13), utc(10)))
    info = check(make(), dt.date(2026, 11, 10))
    assert info.valid and info.days_left == 7


def test_resetting_clock_every_morning_adds_up(monkeypatch):
    rollbacks(monkeypatch, *[(utc(11), utc(10)) for _ in range(6)])
    info = check(make(), dt.date(2026, 11, 10))
    assert info.valid and info.days_left == 4
    rollbacks(monkeypatch, *[(utc(11), utc(10)) for _ in range(11)])
    assert not check(make(), dt.date(2026, 11, 10)).valid


def test_small_steps_cannot_slip_under_a_threshold(monkeypatch):
    step = (utc(10, 12), utc(10, 12) - dt.timedelta(minutes=4))
    rollbacks(monkeypatch, *[step] * 720)  # 48 saat
    assert check(make(), dt.date(2026, 11, 10)).days_left == 8


def test_rollback_before_key_was_issued_does_not_count(monkeypatch):
    rollbacks(monkeypatch, (dt.datetime(2026, 10, 30, tzinfo=dt.timezone.utc), dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)))
    assert check(make(), dt.date(2026, 11, 10)).days_left == 10


def test_clock_before_issue_date_is_refused():
    info = check(make(), dt.date(2026, 10, 15))
    assert not info.valid and "saat" in info.message.lower()


def test_old_format_demo_key_is_protected_too(monkeypatch):
    rollbacks(monkeypatch, (utc(25), utc(16)))
    info = check(make_v1(), dt.date(2026, 11, 16))
    assert not info.valid and info.demo


# ------------------------------------------------------------ son görülen tarih
def test_last_seen_date_never_goes_back():
    key = make()
    assert check(key, dt.date(2026, 11, 15)).days_left == 5
    assert check(key, dt.date(2026, 11, 10)).days_left == 5


def test_deleting_the_file_is_not_enough():
    key = make()
    check(key, dt.date(2026, 11, 25))
    lic._LAST_SEEN_FILE.unlink()
    assert not check(key, dt.date(2026, 11, 16)).valid


def test_deleting_the_registry_value_is_not_enough():
    key = make()
    check(key, dt.date(2026, 11, 25))
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_REG_KEY)
    assert not check(key, dt.date(2026, 11, 16)).valid


def test_last_seen_of_old_key_does_not_block_a_new_key():
    check(make(cid=1), dt.date(2026, 11, 25))
    new_key = make(cid=2, expires=dt.date(2026, 12, 20), issued=dt.date(2026, 11, 10))
    assert check(new_key, dt.date(2026, 11, 12)).days_left == 38


def test_old_plain_state_file_is_ignored(tmp_path):
    lic._LAST_SEEN_FILE.write_text("2030-01-01")
    assert check(make(), dt.date(2026, 11, 10)).days_left == 10


# ------------------------------------------------------------ süresiz lisans
def test_perpetual_key_ignores_clock_entirely(monkeypatch):
    def fail():
        raise AssertionError("süresiz lisansta Windows kayıtları okunmamalı")
    monkeypatch.setattr(lic, "_clock_rollbacks", fail)
    info = check(make(expires=None), dt.date(2020, 2, 1))
    assert info.valid and info.expires is None
    assert not lic._LAST_SEEN_FILE.exists()


# ------------------------------------------------------------ Windows kaydını okuma
SAMPLE = ("<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><EventID>1</EventID></System><EventData>"
          "<Data Name='NewTime'>2026-11-16T09:00:00.2055821Z</Data><Data Name='OldTime'>2026-11-25T09:00:00.2050756Z</Data>"
          "<Data Name='TimeDeltaInMs'>0</Data><Data Name='Reason'>1</Data></EventData></Event>"
          "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><EventData>"
          "<Data Name='NewTime'>2026-11-03T16:41:13.2055821Z</Data><Data Name='OldTime'>2026-11-03T16:41:13.2050756Z</Data>"
          "</EventData></Event>")


def test_parser_keeps_only_backward_jumps():
    found = lic._parse_clock_events(SAMPLE)
    assert len(found) == 1
    old, new = found[0]
    assert old.date() == dt.date(2026, 11, 25) and new.date() == dt.date(2026, 11, 16)


def test_parser_ignores_garbage():
    assert lic._parse_clock_events("hata: erişim reddedildi") == []
    assert lic._parse_clock_events("<Data Name='NewTime'>x</Data><Data Name='OldTime'>y</Data>") == []


@pytest.mark.parametrize("error", [FileNotFoundError("wevtutil yok"), PermissionError("erişim"), OSError("hata")])
def test_unreadable_windows_log_does_not_crash(monkeypatch, error):
    monkeypatch.undo()  # sahte _clock_rollbacks yerine gerçeği denensin

    def broken(*a, **k):
        raise error
    monkeypatch.setattr(lic.subprocess, "run", broken)
    assert lic._clock_rollbacks() == []


# ------------------------------------------------------------ anahtar biçimi ve üretici
def test_new_key_carries_issue_date():
    payload, _ = lic.decode_key(make())
    assert payload[0] == lic.VERSION and len(payload) == lic.PAYLOAD_LEN


def _load_keygen(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("keygen_test", ROOT / "tools" / "keygen.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    private = tmp_path / "private.pem"
    private.write_bytes(PRIV.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    monkeypatch.setattr(mod, "PRIVATE", private)
    monkeypatch.setattr(mod, "LOG", tmp_path / "issued.csv")
    return mod


def _issue_args(**kw):
    base = dict(machine_code=None, demo=False, customer="Test", days=None, until=None, perpetual=False)
    return Namespace(**{**base, **kw})


def test_customer_key_is_bound_to_machine_and_logged(tmp_path, monkeypatch, capsys):
    keygen = _load_keygen(tmp_path, monkeypatch)
    code = lic._group(lic.base64.b32encode(MACHINE).decode().rstrip("="))
    assert keygen.cmd_issue(_issue_args(machine_code=code, customer="X Hastanesi", days=14)) == 0
    key = capsys.readouterr().out.strip()
    today = dt.date.today()
    info = verify(key, public_key=PUB, machine=MACHINE, today=today, check_clock=False)
    assert info.valid and not info.demo and info.days_left == 14
    assert not verify(key, public_key=PUB, machine=b"\x11" * 10, today=today, check_clock=False).valid
    with (tmp_path / "issued.csv").open(encoding="utf-8") as f:
        assert next(csv.DictReader(f))["customer"] == "X Hastanesi"


def test_open_demo_key_warns_that_it_is_not_for_customers(tmp_path, monkeypatch, capsys):
    keygen = _load_keygen(tmp_path, monkeypatch)
    assert keygen.cmd_issue(_issue_args(demo=True, days=14)) == 0
    assert "her bilgisayarda" in capsys.readouterr().err.lower()
