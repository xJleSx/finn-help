from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_CIPHER: Optional[object] = None


def _get_cipher() -> Optional[object]:
    global _CIPHER
    if _CIPHER is not None:
        return _CIPHER

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("cryptography not installed, tokens stored in plaintext")
        return None

    from src.config import settings

    key = settings.encryption_key
    if not key:
        logger.warning("ENCRYPTION_KEY not set, tokens stored in plaintext")
        return None

    try:
        if len(key) != 44 or not key.endswith("="):
            derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
            _CIPHER = Fernet(derived)
        else:
            _CIPHER = Fernet(key.encode())
        return _CIPHER
    except Exception as e:
        logger.warning("Failed to initialize encryption: %s", e)
        return None


def encrypt(plaintext: str) -> str:
    cipher = _get_cipher()
    if cipher is None:
        return plaintext
    try:
        return cipher.encrypt(plaintext.encode()).decode()
    except Exception as e:
        logger.error("Encryption failed: %s", e)
        return plaintext


def decrypt(ciphertext: str) -> str:
    cipher = _get_cipher()
    if cipher is None:
        return ciphertext
    try:
        return cipher.decrypt(ciphertext.encode()).decode()
    except Exception as e:
        logger.error("Decryption failed: %s", e)
        return ciphertext


def is_encrypted(value: str) -> bool:
    return value.startswith("gAAAAA")
