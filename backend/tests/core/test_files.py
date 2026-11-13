"""Document files: real type checks, EXIF removal, bomb guard, chunked AES-256-GCM at rest."""

import base64
import io
import secrets
from pathlib import Path

import pytest
from PIL import Image

from app.core.errors import AppError
from app.core.files import (
    CHUNK_SIZE,
    DocumentStore,
    FileDecryptError,
    prepare_upload,
)


def _key() -> bytes:
    return secrets.token_bytes(32)


def _store(directory: Path, key: bytes | None = None, key_id: str = "t1") -> DocumentStore:
    return DocumentStore(directory, {key_id: key or _key()}, active_key_id=key_id)


def _jpeg(size: tuple[int, int] = (40, 30), exif: bool = False) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, (1, 2, 3))
    if exif:
        data = Image.Exif()
        data[0x010F] = "TestCameraMaker"
        image.save(buffer, format="JPEG", exif=data.tobytes())
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _code(exc: pytest.ExceptionInfo[AppError]) -> str:
    return exc.value.code


# --- Type and size --------------------------------------------------------------------------------


def test_jpeg_png_and_pdf_are_recognised_by_content() -> None:
    png = io.BytesIO()
    Image.new("RGB", (5, 5)).save(png, format="PNG")
    assert prepare_upload(_jpeg()).mime_type == "image/jpeg"
    assert prepare_upload(png.getvalue()).mime_type == "image/png"
    assert prepare_upload(b"%PDF-1.4\n%DEMO\n%%EOF\n").mime_type == "application/pdf"


@pytest.mark.parametrize(
    "data",
    [
        b"MZ\x90\x00" + b"\x00" * 100,  # Windows executable
        b"<html><script>alert(1)</script></html>",
        b"GIF89a" + b"\x00" * 50,
        b"",
    ],
)
def test_other_content_is_refused(data: bytes) -> None:
    with pytest.raises(AppError) as caught:
        prepare_upload(data)
    assert _code(caught) == "FILE_TYPE_NOT_ALLOWED"


def test_a_pdf_without_an_end_marker_is_refused() -> None:
    with pytest.raises(AppError) as caught:
        prepare_upload(b"%PDF-1.4\nnot finished")
    assert _code(caught) == "FILE_TYPE_NOT_ALLOWED"


def test_size_limits_are_per_type() -> None:
    with pytest.raises(AppError) as caught:
        prepare_upload(b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024) + b"\n%%EOF\n")
    assert _code(caught) == "FILE_TOO_LARGE"
    big_image = b"\xff\xd8\xff\xe0" + b"0" * (5 * 1024 * 1024)
    with pytest.raises(AppError) as caught:
        prepare_upload(big_image)
    assert _code(caught) == "FILE_TOO_LARGE"


# --- Images ---------------------------------------------------------------------------------------


def test_exif_is_stripped() -> None:
    prepared = prepare_upload(_jpeg(exif=True))
    assert b"TestCameraMaker" not in prepared.data
    assert dict(Image.open(io.BytesIO(prepared.data)).getexif()) == {}


def test_png_text_chunks_are_stripped() -> None:
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "TestSecretComment")
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG", pnginfo=info)
    prepared = prepare_upload(buffer.getvalue())
    assert b"TestSecretComment" not in prepared.data


def test_images_can_be_resized() -> None:
    prepared = prepare_upload(_jpeg(size=(4000, 1000)), max_side=1600)
    assert Image.open(io.BytesIO(prepared.data)).size == (1600, 400)
    untouched = prepare_upload(_jpeg(size=(400, 100)), max_side=1600)
    assert Image.open(io.BytesIO(untouched.data)).size == (400, 100)


def test_decompression_bombs_are_refused() -> None:
    buffer = io.BytesIO()
    Image.new("1", (10_000, 10_000)).save(buffer, format="PNG", optimize=True)
    with pytest.raises(AppError) as caught:
        prepare_upload(buffer.getvalue())
    assert _code(caught) == "IMAGE_TOO_LARGE"


def test_a_truncated_image_is_refused() -> None:
    with pytest.raises(AppError) as caught:
        prepare_upload(_jpeg(size=(200, 200))[:200])
    assert _code(caught) == "FILE_TYPE_NOT_ALLOWED"


def test_sha256_is_of_the_stored_content() -> None:
    import hashlib

    prepared = prepare_upload(_jpeg(exif=True))
    assert prepared.sha256 == hashlib.sha256(prepared.data).hexdigest()


# --- Encryption at rest ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", [0, 1, CHUNK_SIZE - 1, CHUNK_SIZE, CHUNK_SIZE * 3 + 17])
def test_round_trip(tmp_path: Path, size: int) -> None:
    store = _store(tmp_path)
    data = secrets.token_bytes(size)
    stored = store.save(data)
    assert stored.key_id == "t1"
    assert b"".join(store.read_chunks(stored.storage_key, stored.key_id)) == data


def test_the_file_on_disk_is_not_the_plaintext(tmp_path: Path) -> None:
    store = _store(tmp_path)
    data = _jpeg() * 3
    stored = store.save(data)
    raw = store.path_for(stored.storage_key).read_bytes()
    assert data not in raw
    assert data[:64] not in raw
    assert not raw.startswith(b"\xff\xd8")
    assert str(tmp_path) in str(store.path_for(stored.storage_key))


def test_another_key_cannot_read_it(tmp_path: Path) -> None:
    stored = _store(tmp_path).save(b"secret test bytes" * 100)
    stranger = _store(tmp_path)
    with pytest.raises(FileDecryptError):
        b"".join(stranger.read_chunks(stored.storage_key, stored.key_id))


def test_an_unknown_key_id_cannot_read_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stored = store.save(b"data")
    with pytest.raises(FileDecryptError):
        b"".join(store.read_chunks(stored.storage_key, "nope"))


def test_tampering_is_detected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stored = store.save(secrets.token_bytes(CHUNK_SIZE * 2 + 5))
    path = store.path_for(stored.storage_key)
    raw = bytearray(path.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    path.write_bytes(bytes(raw))
    with pytest.raises(FileDecryptError):
        b"".join(store.read_chunks(stored.storage_key, stored.key_id))


def test_truncation_at_a_chunk_boundary_is_detected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stored = store.save(secrets.token_bytes(CHUNK_SIZE * 2 + 5))
    path = store.path_for(stored.storage_key)
    raw = path.read_bytes()
    # Drop the final chunk; what remains is a valid prefix of whole chunks.
    last_chunk = 5 + 16
    path.write_bytes(raw[:-last_chunk])
    with pytest.raises(FileDecryptError):
        b"".join(store.read_chunks(stored.storage_key, stored.key_id))


def test_a_file_moved_to_another_storage_key_does_not_decrypt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.save(b"first test file")
    second = store.save(b"second test file")
    store.path_for(second.storage_key).write_bytes(store.path_for(first.storage_key).read_bytes())
    with pytest.raises(FileDecryptError):
        b"".join(store.read_chunks(second.storage_key, second.key_id))


def test_old_keys_still_decrypt_after_rotation(tmp_path: Path) -> None:
    old_key = _key()
    stored = _store(tmp_path, old_key, "k1").save(b"before rotation")
    rotated = DocumentStore(tmp_path, {"k1": old_key, "k2": _key()}, active_key_id="k2")
    assert b"".join(rotated.read_chunks(stored.storage_key, "k1")) == b"before rotation"
    assert rotated.save(b"after").key_id == "k2"


def test_storage_keys_are_random_and_safe(tmp_path: Path) -> None:
    store = _store(tmp_path)
    keys = {store.save(b"x").storage_key for _ in range(5)}
    assert len(keys) == 5
    for key in keys:
        assert key.isalnum()
        assert len(key) >= 32
    with pytest.raises(ValueError):
        store.path_for("../escape")


def test_store_from_settings_parses_the_key_list(tmp_path: Path) -> None:
    from app.core.files import document_store
    from tests.helpers import make_settings

    key = base64.b64encode(_key()).decode()
    settings = make_settings(
        DOCUMENTS_DIR=tmp_path, FILE_ENCRYPTION_KEYS=f"a1:{key}", ACTIVE_FILE_KEY_ID="a1"
    )
    stored = document_store(settings).save(b"from settings")
    assert stored.key_id == "a1"
