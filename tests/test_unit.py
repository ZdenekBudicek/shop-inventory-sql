import secrets

import pytest

from shop.auth import hash_password, verify_password
from shop.service import label, number


def test_hashes_are_salted_and_verifiable():
    password = secrets.token_urlsafe(24)
    a, b = hash_password(password), hash_password(password)
    assert a != b and password not in a
    assert verify_password(password, a)
    assert not verify_password(password + "x", a)


@pytest.mark.parametrize("encoded", ["", "scrypt$broken$hash", "other$00$00"])
def test_corrupt_hash_fails_closed(encoded):
    assert not verify_password("synthetic input", encoded)


@pytest.mark.parametrize("value", [-1, True, 1.5, "3", 1_000_000_001])
def test_invalid_numbers(value):
    with pytest.raises(ValueError):
        number(value)


@pytest.mark.parametrize("value", ["", " ", "x" * 201, "bad\nlabel", "bad\x1b[31m"])
def test_invalid_labels(value):
    with pytest.raises(ValueError):
        label(value)


def test_exact_boundaries():
    assert number(0) == 0 and number(1_000_000_000) == 1_000_000_000
    assert label("  Sample  ") == "Sample"


def test_short_password_rejected():
    with pytest.raises(ValueError):
        hash_password("short")
