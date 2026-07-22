from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from src.config import settings

logger = logging.getLogger(__name__)

_CIPHER: Optional[Fernet] = None


class CryptoError(Exception):
    pass


def _validate_key(key: str) -> bytes:
    if len(key) == 44 and key.endswith("="):
        return key.encode()
    raise CryptoError(
        "ENCRYPTION_KEY must be a 44-character base64 Fernet key ending with '='. "
        "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )


def _get_cipher() -> Fernet:
    global _CIPHER
    if _CIPHER is not None:
        return _CIPHER

    key = settings.encryption_key
    if not key:
        raise CryptoError("ENCRYPTION_KEY is not set in configuration")

    key_bytes = _validate_key(key)
    _CIPHER = Fernet(key_bytes)
    return _CIPHER


def encrypt(plaintext: str) -> str:
    cipher = _get_cipher()
    try:
        return cipher.encrypt(plaintext.encode()).decode()
    except Exception as e:
        raise CryptoError(f"Encryption failed: {e}") from e


def decrypt(ciphertext: str) -> str:
    cipher = _get_cipher()
    try:
        return cipher.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise CryptoError("Decryption failed: invalid token or wrong key")
    except Exception as e:
        raise CryptoError(f"Decryption failed: {e}") from e


def is_encrypted(value: str) -> bool:
    return value.startswith("gAAAAA")
