"""AES-256-GCM field encryption with a key id (docs/security.md)."""

import pytest

from app.core.crypto import FieldCipher, FieldDecryptError
from tests.helpers import random_key_b64


def _cipher(key_id: str = "f1", key: str | None = None) -> FieldCipher:
    return FieldCipher({key_id: key or random_key_b64()}, active_key_id=key_id)


def test_round_trip() -> None:
    cipher = _cipher()
    stored = cipher.encrypt("JBSWY3DPEHPK3PXP", context="users.totp_secret:1")
    assert stored.startswith("f1:")
    assert "JBSWY3DPEHPK3PXP" not in stored
    assert cipher.decrypt(stored, context="users.totp_secret:1") == "JBSWY3DPEHPK3PXP"


def test_each_encryption_uses_a_fresh_nonce() -> None:
    cipher = _cipher()
    assert cipher.encrypt("same", context="c") != cipher.encrypt("same", context="c")


def test_tampering_is_detected() -> None:
    cipher = _cipher()
    stored = cipher.encrypt("secret value", context="c")
    key_id, _, body = stored.partition(":")
    flipped = body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1]
    with pytest.raises(FieldDecryptError):
        cipher.decrypt(f"{key_id}:{flipped}", context="c")


def test_the_context_binds_the_value_to_its_row() -> None:
    cipher = _cipher()
    stored = cipher.encrypt("secret value", context="users.totp_secret:1")
    with pytest.raises(FieldDecryptError):
        cipher.decrypt(stored, context="users.totp_secret:2")


def test_old_keys_still_decrypt_after_rotation() -> None:
    old_key, new_key = random_key_b64(), random_key_b64()
    old = FieldCipher({"f1": old_key}, active_key_id="f1")
    stored = old.encrypt("secret value", context="c")
    rotated = FieldCipher({"f1": old_key, "f2": new_key}, active_key_id="f2")
    assert rotated.decrypt(stored, context="c") == "secret value"
    assert rotated.encrypt("x", context="c").startswith("f2:")


def test_unknown_key_id_is_refused() -> None:
    stored = _cipher("f1").encrypt("secret value", context="c")
    with pytest.raises(FieldDecryptError):
        _cipher("f9").decrypt(stored, context="c")


def test_a_missing_or_bad_key_is_refused() -> None:
    with pytest.raises(ValueError):
        FieldCipher({"f1": ""}, active_key_id="f1")
    with pytest.raises(ValueError):
        FieldCipher({"f1": "dG9vLXNob3J0"}, active_key_id="f1")  # "too-short"
