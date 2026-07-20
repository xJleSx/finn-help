from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from typing import Optional


def generate_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode()


def get_totp_uri(secret: str, username: str, issuer: str = "FinAdvisor") -> str:
    return f"otpauth://totp/{issuer}:{username}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret, casefold=True)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[19] & 15
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def _timecode(period: int = 30) -> int:
    return int(time.time()) // period


def _valid_window(secret: str, code: str, window: int = 1, period: int = 30) -> bool:
    tc = _timecode(period)
    return any(hmac.compare_digest(_hotp(secret, tc + i), code) for i in range(-window, window + 1))


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    if len(code) != 6 or not code.isdigit():
        return False
    return _valid_window(secret, code)


def generate_recovery_codes(count: int = 8) -> list[str]:
    import secrets

    codes: list[str] = []
    for _ in range(count):
        code = secrets.token_hex(4).upper()
        codes.append(f"{code[:4]}-{code[4:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def verify_recovery_code(code: str, hashed_codes: list[str]) -> Optional[str]:
    for stored in hashed_codes:
        if hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(), stored):
            return stored
    return None
