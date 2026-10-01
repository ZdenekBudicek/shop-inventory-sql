"""Salted password storage. Passwords never appear in application output."""

import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 1024:
        raise ValueError("Password must contain 12..1024 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=67108864)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    if len(password) > 1024:
        return False
    try:
        kind, salt_hex, digest_hex = encoded.split("$")
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        if kind != "scrypt" or len(salt) != 16 or len(expected) != 64:
            return False
        actual = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=67108864)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
