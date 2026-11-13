"""Documents: real type checks, EXIF removal, encryption at rest, access rules and access logs."""

import hashlib
import io
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.config import Settings
from app.modules.documents.models import Document, DocumentAccessLog
from tests.api.conftest import Team
from tests.api.driver_helpers import (
    EXIF_MAKE,
    EXIF_MARKER,
    create_driver,
    error_code,
    jpeg_bytes,
    new_attempt,
    pdf_bytes,
    png_bytes,
    record_consent,
    upload,
)
from tests.api.helpers import API, bearer

EXE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff" + b"\x00" * 200


@pytest.fixture
def attempt(api: TestClient, team: Team) -> int:
    driver = create_driver(api, team.staff_a)
    record_consent(api, team.staff_a, driver["id"])
    return new_attempt(api, team.staff_a, driver["id"], "identity")


def _uploaded(api: TestClient, team: Team, attempt: int, data: bytes | None = None) -> int:
    response = upload(api, team.staff_a, attempt, "id_front", data)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_no_access_without_sign_in(api: TestClient, team: Team, attempt: int) -> None:
    document_id = _uploaded(api, team, attempt)
    assert api.get(f"{API}/documents/{document_id}/content").status_code == 401
    assert api.get(f"{API}/documents/{document_id}").status_code == 401


def test_staff_without_kyc_access_get_404(api: TestClient, team: Team, attempt: int) -> None:
    document_id = _uploaded(api, team, attempt)
    other = bearer(team.staff_b)
    assert api.get(f"{API}/documents/{document_id}/content", headers=other).status_code == 404
    assert api.get(f"{API}/documents/{document_id}", headers=other).status_code == 404
    assert api.get(f"{API}/documents/999999/content", headers=other).status_code == 404
    owner = bearer(team.owner.token)
    assert api.get(f"{API}/documents/{document_id}/content", headers=owner).status_code == 200


def test_every_view_is_logged(
    api: TestClient, team: Team, attempt: int, app_engine: Engine
) -> None:
    document_id = _uploaded(api, team, attempt)
    for token in (team.staff_a, team.owner.token, team.staff_a):
        response = api.get(f"{API}/documents/{document_id}/content", headers=bearer(token))
        assert response.status_code == 200
    refused = api.get(f"{API}/documents/{document_id}/content", headers=bearer(team.staff_b))
    assert refused.status_code == 404

    with Session(app_engine) as session:
        rows = session.scalars(
            select(DocumentAccessLog)
            .where(DocumentAccessLog.document_id == document_id)
            .order_by(DocumentAccessLog.id)
        ).all()
        audited = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "document.viewed", AuditLog.entity_id == document_id)
        )
    assert [r.user_id for r in rows] == [team.staff_a_id, team.owner.id, team.staff_a_id]
    assert all(r.purpose == "view" for r in rows)
    assert audited == 3


def test_content_is_never_cached_and_pdfs_are_attachments(
    api: TestClient, team: Team, attempt: int
) -> None:
    image_id = _uploaded(api, team, attempt)
    image = api.get(f"{API}/documents/{image_id}/content", headers=bearer(team.staff_a))
    assert image.headers["cache-control"] == "no-store"
    assert image.headers["x-content-type-options"] == "nosniff"
    assert image.headers["content-type"] == "image/jpeg"

    pdf = upload(
        api,
        team.staff_a,
        attempt,
        "id_back",
        pdf_bytes(),
        filename="back.pdf",
        content_type="application/pdf",
    )
    assert pdf.status_code == 201, pdf.text
    response = api.get(f"{API}/documents/{pdf.json()['id']}/content", headers=bearer(team.staff_a))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["cache-control"] == "no-store"
    assert response.content == pdf_bytes()


def test_the_stored_file_is_not_readable_without_the_key(
    api: TestClient, team: Team, attempt: int, app_engine: Engine, test_settings: Settings
) -> None:
    original = png_bytes()
    document_id = _uploaded(api, team, attempt, original)
    with Session(app_engine) as session:
        document = session.get(Document, document_id)
        assert document is not None
        storage_key, key_id, sha256 = document.storage_key, document.key_id, document.sha256
    assert key_id == test_settings.ACTIVE_FILE_KEY_ID

    files = [p for p in Path(test_settings.DOCUMENTS_DIR).rglob("*") if p.name == storage_key]
    assert len(files) == 1
    raw = files[0].read_bytes()
    assert b"PNG" not in raw[:64]
    with pytest.raises(OSError):
        Image.open(io.BytesIO(raw))

    served = api.get(f"{API}/documents/{document_id}/content", headers=bearer(team.staff_a))
    assert hashlib.sha256(served.content).hexdigest() == sha256


def test_exif_is_removed(api: TestClient, team: Team, attempt: int) -> None:
    with_exif = jpeg_bytes(with_exif=True)
    assert Image.open(io.BytesIO(with_exif)).getexif().get(EXIF_MAKE) == EXIF_MARKER

    document_id = _uploaded(api, team, attempt, with_exif)
    served = api.get(f"{API}/documents/{document_id}/content", headers=bearer(team.staff_a))
    image = Image.open(io.BytesIO(served.content))
    assert dict(image.getexif()) == {}
    assert EXIF_MARKER.encode() not in served.content


def test_an_exe_renamed_to_jpg_is_refused(api: TestClient, team: Team, attempt: int) -> None:
    response = upload(api, team.staff_a, attempt, "id_front", EXE_BYTES, filename="photo.jpg")
    assert response.status_code == 422
    assert error_code(response) == "FILE_TYPE_NOT_ALLOWED"


def test_a_file_that_only_claims_to_be_an_image_is_refused(
    api: TestClient, team: Team, attempt: int
) -> None:
    broken = b"\xff\xd8\xff\xe0" + b"not really a jpeg" * 20
    response = upload(api, team.staff_a, attempt, "id_front", broken)
    assert response.status_code == 422
    assert error_code(response) == "FILE_TYPE_NOT_ALLOWED"


def test_size_limits(api: TestClient, team: Team, attempt: int) -> None:
    big_pdf = pdf_bytes(padding=10 * 1024 * 1024)
    response = upload(
        api,
        team.staff_a,
        attempt,
        "id_front",
        big_pdf,
        filename="big.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 422
    assert error_code(response) == "FILE_TOO_LARGE"

    # A real PNG just over 5 MB (random noise does not compress).
    noise = Image.frombytes("RGB", (1500, 1500), os.urandom(1500 * 1500 * 3))
    buffer = io.BytesIO()
    noise.save(buffer, format="PNG")
    assert buffer.tell() > 5 * 1024 * 1024
    response = upload(
        api,
        team.staff_a,
        attempt,
        "id_front",
        buffer.getvalue(),
        filename="big.png",
        content_type="image/png",
    )
    assert response.status_code == 422
    assert error_code(response) == "FILE_TOO_LARGE"


def test_a_decompression_bomb_is_refused(api: TestClient, team: Team, attempt: int) -> None:
    # A small PNG that decodes to a huge canvas: 100 million pixels of one colour.
    buffer = io.BytesIO()
    Image.new("1", (10_000, 10_000)).save(buffer, format="PNG", optimize=True)
    assert buffer.tell() < 5 * 1024 * 1024
    response = upload(
        api,
        team.staff_a,
        attempt,
        "id_front",
        buffer.getvalue(),
        filename="bomb.png",
        content_type="image/png",
    )
    assert response.status_code == 422
    assert error_code(response) == "IMAGE_TOO_LARGE"


def test_unknown_document_types_are_refused(api: TestClient, team: Team, attempt: int) -> None:
    response = upload(api, team.staff_a, attempt, "licence_front")  # identity attempt
    assert response.status_code == 422
    assert error_code(response) == "DOC_TYPE_NOT_ALLOWED"


def test_driver_photo_is_resized(api: TestClient, team: Team) -> None:
    driver = create_driver(api, team.staff_a)
    response = api.post(
        f"{API}/drivers/{driver['id']}/photo",
        files={"file": ("photo.jpg", jpeg_bytes(size=(3200, 2000)), "image/jpeg")},
        headers=bearer(team.staff_a),
    )
    assert response.status_code == 200, response.text
    photo_id = response.json()["photo_document_id"]
    served = api.get(f"{API}/documents/{photo_id}/content", headers=bearer(team.staff_a))
    assert max(Image.open(io.BytesIO(served.content)).size) == 1600


def test_document_metadata_never_has_a_public_url(
    api: TestClient, team: Team, attempt: int
) -> None:
    document_id = _uploaded(api, team, attempt)
    meta = api.get(f"{API}/documents/{document_id}", headers=bearer(team.staff_a)).json()
    assert meta["content_url"] == f"/api/v1/documents/{document_id}/content"
    assert "storage_key" not in meta
    assert meta["mime_type"] == "image/jpeg"
