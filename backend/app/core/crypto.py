"""Application-level field encryption: AES-256-GCM with a key id (docs/security.md).

Stored form: ``<key_id>:<base64url(nonce || ciphertext+tag)>``. A `context` string (for
example ``users.totp_secret:42``) is bound in as associated data, so a value copied to another
row or column does not decrypt. Old key ids keep decrypting after a rotation.
"""

import base64
import binascii
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings

_KEY_BYTES = 32
_NONCE_BYTES = 12


class FieldDecryptError(Exception):
    """The value could not be decrypted (wrong key, wrong context or tampered)."""


def _decode_key(value: str) -> bytes:
    try:
        key = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Field encryption key must be base64.") from exc
    if len(key) != _KEY_BYTES:
        raise ValueError("Field encryption key must be 32 bytes.")
    return key


class FieldCipher:
    def __init__(self, keys: dict[str, str], *, active_key_id: str) -> None:
        if active_key_id not in keys:
            raise ValueError("The active field key id has no key.")
        self._keys = {key_id: AESGCM(_decode_key(key)) for key_id, key in keys.items()}
        self._active = active_key_id

    def encrypt(self, plaintext: str, *, context: str) -> str:
        nonce = secrets.token_bytes(_NONCE_BYTES)
        sealed = self._keys[self._active].encrypt(
            nonce, plaintext.encode("utf-8"), context.encode("utf-8")
        )
        body = base64.urlsafe_b64encode(nonce + sealed).decode("ascii")
        return f"{self._active}:{body}"

    def decrypt(self, stored: str, *, context: str) -> str:
        key_id, sep, body = stored.partition(":")
        aesgcm = self._keys.get(key_id)
        if not sep or aesgcm is None:
            raise FieldDecryptError("Unknown field key id.")
        try:
            raw = base64.urlsafe_b64decode(body.encode("ascii"))
            plaintext = aesgcm.decrypt(
                raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], context.encode("utf-8")
            )
        except (InvalidTag, binascii.Error, ValueError) as exc:
            raise FieldDecryptError("The value could not be decrypted.") from exc
        return plaintext.decode("utf-8")


def field_cipher(settings: Settings) -> FieldCipher:
    return FieldCipher(
        {settings.FIELD_ENCRYPTION_KEY_ID: settings.FIELD_ENCRYPTION_KEY.get_secret_value()},
        active_key_id=settings.FIELD_ENCRYPTION_KEY_ID,
    )
