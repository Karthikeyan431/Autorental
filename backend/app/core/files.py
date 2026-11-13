"""Document files: checking uploads and storing them encrypted (docs/kyc.md, docs/security.md).

Uploads
* Only JPEG, PNG and PDF, recognised by their content, never by the name or the declared type.
  Images up to 5 MB, PDFs up to 10 MB.
* Images are decoded by Pillow (a file that only starts like an image is refused), re-saved
  without EXIF or text metadata, and optionally resized. Decompression bombs are refused: any
  image over MAX_IMAGE_PIXELS is an error, not a warning.
* The SHA-256 recorded is of the bytes actually stored (after cleaning).

Storage
* Files live under DOCUMENTS_DIR (outside the web root) at <first 2 chars>/<storage key>, where
  the storage key is random. They are never served by path; only the documents endpoint reads
  them, after a permission check.
* Each file is encrypted with AES-256-GCM in 64 KiB chunks, so it can be streamed and every
  chunk is authenticated as it is read. Each chunk's nonce is a random per-file prefix plus the
  chunk number, and its associated data binds the storage key, the chunk number and whether it
  is the last chunk. Reordering, truncating, swapping files or flipping a bit all fail.
* The key id is stored with the document, so old keys keep decrypting after a rotation.
"""

import base64
import binascii
import hashlib
import io
import os
import secrets
import struct
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import Settings
from app.core.errors import AppError

MIME_JPEG = "image/jpeg"
MIME_PNG = "image/png"
MIME_PDF = "application/pdf"
IMAGE_TYPES = frozenset({MIME_JPEG, MIME_PNG})

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_BYTES = MAX_PDF_BYTES  # read at most this much (+1) from a request

# About 40 megapixels: far more than any phone photo of a card needs. Pillow's own guard uses
# the same limit, and its warning is turned into a refusal below.
MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

CHUNK_SIZE = 64 * 1024
_TAG_BYTES = 16
_PREFIX_BYTES = 8
_MAGIC = b"ARMSDOC1"
_HEADER_BYTES = len(_MAGIC) + _PREFIX_BYTES
_KEY_BYTES = 32


def _reject(code: str, message: str) -> AppError:
    return AppError(code, message, status_code=422)


def _sniff(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return MIME_JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return MIME_PNG
    if data.startswith(b"%PDF-"):
        return MIME_PDF
    raise _reject("FILE_TYPE_NOT_ALLOWED", "Upload a JPEG or PNG photo, or a PDF.")


@dataclass(frozen=True)
class PreparedFile:
    data: bytes
    mime_type: str
    sha256: str


def _clean_image(data: bytes, mime_type: str, max_side: int | None) -> bytes:
    expected = "JPEG" if mime_type == MIME_JPEG else "PNG"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as opened:
                if opened.format != expected:
                    raise _reject("FILE_TYPE_NOT_ALLOWED", "Upload a JPEG or PNG photo, or a PDF.")
                if opened.width * opened.height > MAX_IMAGE_PIXELS:
                    raise _reject("IMAGE_TOO_LARGE", "This image is too large. Take a new photo.")
                opened.load()
                image = ImageOps.exif_transpose(opened)  # keep the visible orientation
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise _reject("IMAGE_TOO_LARGE", "This image is too large. Take a new photo.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise _reject("FILE_TYPE_NOT_ALLOWED", "This file is damaged or not an image.") from exc

    if max_side is not None and max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    if mime_type == MIME_JPEG:
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        # A fresh save writes no EXIF, ICC or comment data unless asked to.
        image.save(out, format="JPEG", quality=90, optimize=True)
    else:
        if image.mode not in ("RGB", "RGBA", "L", "LA", "P", "1"):
            image = image.convert("RGBA")
        image.save(out, format="PNG", optimize=True)  # no text chunks are copied
    return out.getvalue()


def prepare_upload(data: bytes, *, max_side: int | None = None) -> PreparedFile:
    """Check the real type and size, clean images, and return what will be stored."""
    if not data:
        raise _reject("FILE_TYPE_NOT_ALLOWED", "The file is empty.")
    mime_type = _sniff(data)
    limit = MAX_PDF_BYTES if mime_type == MIME_PDF else MAX_IMAGE_BYTES
    if len(data) > limit:
        megabytes = limit // (1024 * 1024)
        raise _reject("FILE_TOO_LARGE", f"The file is larger than {megabytes} MB.")

    if mime_type == MIME_PDF:
        if b"%%EOF" not in data[-1024:]:
            raise _reject("FILE_TYPE_NOT_ALLOWED", "This PDF is damaged or incomplete.")
        cleaned = data
    else:
        cleaned = _clean_image(data, mime_type, max_side)
    return PreparedFile(cleaned, mime_type, hashlib.sha256(cleaned).hexdigest())


# --- Encrypted storage -----------------------------------------------------------------------


class FileDecryptError(Exception):
    """The stored file could not be decrypted (wrong key, moved, truncated or tampered)."""


@dataclass(frozen=True)
class StoredFile:
    storage_key: str
    key_id: str


def _associated_data(storage_key: str, index: int, final: bool) -> bytes:
    return storage_key.encode("ascii") + struct.pack(">IB", index, 1 if final else 0)


def _nonce(prefix: bytes, index: int) -> bytes:
    return prefix + struct.pack(">I", index)


class DocumentStore:
    def __init__(self, directory: Path, keys: dict[str, bytes], *, active_key_id: str) -> None:
        if active_key_id not in keys:
            raise ValueError("The active file key id has no key.")
        if any(len(key) != _KEY_BYTES for key in keys.values()):
            raise ValueError("File encryption keys must be 32 bytes.")
        self._directory = Path(directory)
        self._ciphers = {key_id: AESGCM(key) for key_id, key in keys.items()}
        self._active = active_key_id

    def path_for(self, storage_key: str) -> Path:
        if not storage_key.isalnum() or len(storage_key) < 32:
            raise ValueError("Invalid storage key.")
        return self._directory / storage_key[:2] / storage_key

    def save(self, plaintext: bytes) -> StoredFile:
        storage_key = secrets.token_hex(24)
        cipher = self._ciphers[self._active]
        prefix = secrets.token_bytes(_PREFIX_BYTES)
        chunks = [plaintext[i : i + CHUNK_SIZE] for i in range(0, len(plaintext), CHUNK_SIZE)]
        if not chunks or len(chunks[-1]) == CHUNK_SIZE:
            chunks.append(b"")  # the final chunk is always short, so its end is unambiguous

        path = self.path_for(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".part")
        with temporary.open("wb") as handle:
            handle.write(_MAGIC + prefix)
            last = len(chunks) - 1
            for index, chunk in enumerate(chunks):
                aad = _associated_data(storage_key, index, index == last)
                handle.write(cipher.encrypt(_nonce(prefix, index), chunk, aad))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return StoredFile(storage_key=storage_key, key_id=self._active)

    def read_chunks(self, storage_key: str, key_id: str) -> Iterator[bytes]:
        """Decrypt and yield the plaintext chunk by chunk. Raises FileDecryptError."""
        cipher = self._ciphers.get(key_id)
        if cipher is None:
            raise FileDecryptError("Unknown file key id.")
        try:
            handle = self.path_for(storage_key).open("rb")
        except OSError as exc:
            raise FileDecryptError("The stored file is missing.") from exc
        with handle:
            header = handle.read(_HEADER_BYTES)
            if len(header) != _HEADER_BYTES or not header.startswith(_MAGIC):
                raise FileDecryptError("Not an encrypted document.")
            prefix = header[len(_MAGIC) :]
            block = CHUNK_SIZE + _TAG_BYTES
            index = 0
            current = handle.read(block)
            while True:
                following = handle.read(block)
                final = not following
                try:
                    yield cipher.decrypt(
                        _nonce(prefix, index),
                        current,
                        _associated_data(storage_key, index, final),
                    )
                except (InvalidTag, ValueError) as exc:
                    raise FileDecryptError("The stored file failed its integrity check.") from exc
                if final:
                    return
                current = following
                index += 1


def _parse_keys(value: str) -> dict[str, bytes]:
    keys: dict[str, bytes] = {}
    for item in filter(None, (part.strip() for part in value.split(","))):
        key_id, _, encoded = item.partition(":")
        try:
            keys[key_id.strip()] = base64.b64decode(encoded.strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("FILE_ENCRYPTION_KEYS must be key_id:base64 entries.") from exc
    return keys


def document_store(settings: Settings) -> DocumentStore:
    keys = _parse_keys(settings.FILE_ENCRYPTION_KEYS.get_secret_value())
    if not keys or settings.ACTIVE_FILE_KEY_ID not in keys:
        raise RuntimeError(
            "Document storage is not configured: set FILE_ENCRYPTION_KEYS and ACTIVE_FILE_KEY_ID "
            "(scripts\\db-setup.ps1 writes them for development)."
        )
    return DocumentStore(
        Path(settings.DOCUMENTS_DIR), keys, active_key_id=settings.ACTIVE_FILE_KEY_ID
    )
