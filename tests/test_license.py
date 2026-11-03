import datetime as dt

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.licensing.license import (DEMO_MACHINE, decode_key, encode_key, machine_code, pack_payload,
                                   parse_machine_code, verify)

PRIV = Ed25519PrivateKey.generate()
PUB = PRIV.public_key()
MACHINE = bytes(range(10))
TODAY = dt.date(2026, 6, 1)


def make(machine=MACHINE, expires=None, cid=7, priv=PRIV):
    p = pack_payload(machine, expires, cid)
    return encode_key(p, priv.sign(p))


def check(key, machine=MACHINE, today=TODAY):
    return verify(key, public_key=PUB, machine=machine, today=today, check_clock=False)


def test_valid_perpetual():
    info = check(make())
    assert info.valid and info.expires is None and info.customer_id == 7


def test_valid_until_date():
    info = check(make(expires=dt.date(2026, 12, 31)))
    assert info.valid and info.expires == dt.date(2026, 12, 31)


def test_expired():
    assert not check(make(expires=dt.date(2026, 5, 1))).valid


def test_wrong_machine():
    assert not check(make(), machine=bytes(10)).valid


def test_tampered_key():
    key = make()
    payload, sig = decode_key(key)
    forged = pack_payload(MACHINE, None, 999)  # müşteri no değiştirildi, imza aynı
    assert not check(encode_key(forged, sig)).valid


def test_other_signer():
    assert not check(make(priv=Ed25519PrivateKey.generate())).valid


@pytest.mark.parametrize("junk", ["", "ABC", "!!!!", "AAAAA-BBBBB"])
def test_garbage(junk):
    assert not check(junk).valid


def test_key_tolerates_formatting():
    key = make()
    assert check(key.lower().replace("-", " ")).valid


def test_machine_code_roundtrip():
    code = machine_code()
    assert len(parse_machine_code(code)) == 10
    assert machine_code() == code  # kararlı


def test_demo_key_works_on_any_machine():
    key = make(machine=DEMO_MACHINE, expires=TODAY + dt.timedelta(days=14))
    for m in (MACHINE, bytes(range(10, 20))):
        info = check(key, machine=m)
        assert info.valid and info.demo and info.days_left == 14 and "Deneme" in info.message


def test_demo_key_expires():
    key = make(machine=DEMO_MACHINE, expires=TODAY - dt.timedelta(days=1))
    info = check(key)
    assert not info.valid and "Deneme süresi" in info.message


def test_demo_key_cannot_be_long_or_perpetual():
    assert not check(make(machine=DEMO_MACHINE, expires=None)).valid
    assert not check(make(machine=DEMO_MACHINE, expires=TODAY + dt.timedelta(days=90))).valid


def test_normal_key_is_not_demo():
    info = check(make(expires=TODAY + dt.timedelta(days=30)))
    assert info.valid and not info.demo
