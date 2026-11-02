"""Security primitives: password hashing, sessions, CSRF, and credential encryption.

- Passwords use Argon2id (argon2-cffi, tuned defaults).
- Browser sessions are opaque tokens; only SHA-256 hashes are stored server-side.
- Integration credentials use AES-256-GCM authenticated encryption with an
  application-supplied key and an explicit key version.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional, Tuple

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core import config

_password_hasher = PasswordHasher()

_AUTH_TAG_BYTES = 16
_NONCE_BYTES = 12


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _password_hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, Exception):
        return False


def check_password_needs_rehash(password_hash: str) -> bool:
    return _password_hasher.check_needs_rehash(password_hash)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def hash_token_hex(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def compare_digest(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def constant_time_eq_bytes(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)


# ---------------------------------------------------------------------------
# Credential encryption (AES-256-GCM)
# ---------------------------------------------------------------------------


def _load_encryption_key() -> bytes:
    raw = config.settings.encryption_key
    if not raw:
        raise RuntimeError(
            "ENCRYPTION_KEY is required to store integration credentials. "
            "Set it to a base64 or hex encoded 32-byte key."
        )
    key = None
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception:
        key = None
    if key is None or len(key) != 32:
        # try hex
        try:
            key = bytes.fromhex(raw)
        except Exception:
            key = None
    if key is None or len(key) != 32:
        raise RuntimeError("ENCRYPTION_KEY must decode to exactly 32 bytes.")
    return key


def encrypt_secret(plaintext: str) -> Tuple[bytes, str]:
    """Encrypt a secret, returning (ciphertext, key_version)."""
    key = _load_encryption_key()
    aes = AESGCM(key)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ct, config.settings.encryption_key_version


def decrypt_secret(ciphertext: bytes) -> str:
    key = _load_encryption_key()
    aes = AESGCM(key)
    if len(ciphertext) < _NONCE_BYTES + _AUTH_TAG_BYTES:
        raise ValueError("Ciphertext too short")
    nonce, ct = ciphertext[:_NONCE_BYTES], ciphertext[_NONCE_BYTES:]
    return aes.decrypt(nonce, ct, None).decode("utf-8")


def mask_secret(secret: str, visible: int = 4) -> str:
    if not secret:
        return ""
    if len(secret) <= visible:
        return "*" * len(secret)
    return secret[:visible] + "*" * (min(len(secret), 24) - visible)
