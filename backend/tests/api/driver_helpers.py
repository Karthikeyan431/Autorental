"""Helpers for the driver, KYC and document API tests.

Every value is obviously fake (hard constraint 7): names like "Test Driver 001", mobiles that
start with 90000, licence numbers like TEST-DL-0001, and images drawn here in memory.
"""

import io
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

from app.core.time import business_date
from tests.api.helpers import API, bearer

IDENTITY_CHECKLIST = {
    "last4_only_visible": True,
    "photo_matches_person": True,
    "details_match_document": True,
}
LICENCE_CHECKLIST = {
    "photo_matches_person": True,
    "details_match_card": True,
    "classes_permitted": True,
    "valid_today": True,
}

# EXIF tags used to prove stripping: 0x010F Make, 0x0110 Model, 0x8825 GPS IFD.
EXIF_MAKE = 0x010F
EXIF_MARKER = "TestCameraMaker"


def jpeg_bytes(*, size: tuple[int, int] = (64, 48), with_exif: bool = False) -> bytes:
    image = Image.new("RGB", size, (200, 120, 40))
    buffer = io.BytesIO()
    if with_exif:
        exif = Image.Exif()
        exif[EXIF_MAKE] = EXIF_MARKER
        image.save(buffer, format="JPEG", exif=exif.tobytes())
    else:
        image.save(buffer, format="JPEG")
    return buffer.getvalue()


def png_bytes(size: tuple[int, int] = (32, 32)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def pdf_bytes(padding: int = 0) -> bytes:
    body = b"%PDF-1.4\n% DEMO test document, not real\n" + b"0" * padding
    return body + b"\n%%EOF\n"


def driver_payload(n: int = 1, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "full_name": f"Test Driver {n:03d}",
        "mobile": f"90000{n:05d}",
        "address": f"Test address {n:03d}, Demo Nagar",
        "date_of_birth": "1990-01-01",
        "emergency_name": f"Test Contact {n:03d}",
        "emergency_mobile": f"90001{n:05d}",
    }
    payload.update(overrides)
    return payload


def create_driver(api: TestClient, token: str, n: int = 1, **overrides: Any) -> dict[str, Any]:
    response = api.post(
        f"{API}/drivers", json=driver_payload(n, **overrides), headers=bearer(token)
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def record_consent(api: TestClient, token: str, driver_id: int) -> dict[str, Any]:
    response = api.post(
        f"{API}/drivers/{driver_id}/consents",
        json={"purpose": "kyc", "notice_version": "v1-test", "method": "in_person_checkbox"},
        headers=bearer(token),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def start_attempt(api: TestClient, token: str, driver_id: int, check_type: str) -> Response:
    response: Response = api.post(
        f"{API}/drivers/{driver_id}/kyc/{check_type}/attempts",
        json={"method": "manual"},
        headers=bearer(token),
    )
    return response


def new_attempt(api: TestClient, token: str, driver_id: int, check_type: str) -> int:
    response = start_attempt(api, token, driver_id, check_type)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def identity_details(**overrides: Any) -> dict[str, Any]:
    details: dict[str, Any] = {
        "document_type": "masked_aadhaar",
        "id_last4": "0001",
        "name_on_document": "Test Driver 001",
        "dob_or_yob": "1990",
    }
    details.update(overrides)
    return details


def licence_details(n: int = 1, **overrides: Any) -> dict[str, Any]:
    details: dict[str, Any] = {
        "licence_number": f"TEST-DL-{n:04d}",
        "name_on_licence": f"Test Driver {n:03d}",
        "date_of_birth": "1990-01-01",
        "issue_date": "2020-01-01",
        "valid_until_non_transport": (business_date() + timedelta(days=3650)).isoformat(),
        "valid_until_transport": None,
        "vehicle_classes": ["3W-TEST"],
        "issuing_authority": "DEMO RTO",
    }
    details.update(overrides)
    return details


def save_identity(api: TestClient, token: str, attempt_id: int, **overrides: Any) -> Response:
    response: Response = api.put(
        f"{API}/kyc/attempts/{attempt_id}/identity-details",
        json=identity_details(**overrides),
        headers=bearer(token),
    )
    return response


def save_licence(
    api: TestClient, token: str, attempt_id: int, n: int = 1, **overrides: Any
) -> Response:
    response: Response = api.put(
        f"{API}/kyc/attempts/{attempt_id}/licence-details",
        json=licence_details(n, **overrides),
        headers=bearer(token),
    )
    return response


def upload(
    api: TestClient,
    token: str,
    attempt_id: int,
    doc_type: str,
    data: bytes | None = None,
    *,
    filename: str = "scan.jpg",
    content_type: str = "image/jpeg",
) -> Response:
    response: Response = api.post(
        f"{API}/kyc/attempts/{attempt_id}/documents",
        data={"doc_type": doc_type},
        files={"file": (filename, data if data is not None else jpeg_bytes(), content_type)},
        headers=bearer(token),
    )
    return response


def submit(api: TestClient, token: str, attempt_id: int) -> Response:
    response: Response = api.post(f"{API}/kyc/attempts/{attempt_id}/submit", headers=bearer(token))
    return response


def decide(
    api: TestClient,
    token: str,
    attempt_id: int,
    decision: str = "approve",
    *,
    checklist: dict[str, bool] | None = None,
    reason: str | None = None,
) -> Response:
    body: dict[str, Any] = {"decision": decision, "checklist": checklist or {}}
    if reason is not None:
        body["reason"] = reason
    response: Response = api.post(
        f"{API}/kyc/attempts/{attempt_id}/decision", json=body, headers=bearer(token)
    )
    return response


def submitted_identity(api: TestClient, token: str, driver_id: int) -> int:
    attempt_id = new_attempt(api, token, driver_id, "identity")
    assert save_identity(api, token, attempt_id).status_code == 200
    assert upload(api, token, attempt_id, "id_front").status_code == 201
    response = submit(api, token, attempt_id)
    assert response.status_code == 200, response.text
    return attempt_id


def submitted_licence(
    api: TestClient, token: str, driver_id: int, n: int = 1, **overrides: Any
) -> int:
    attempt_id = new_attempt(api, token, driver_id, "licence")
    response = save_licence(api, token, attempt_id, n, **overrides)
    assert response.status_code == 200, response.text
    assert upload(api, token, attempt_id, "licence_front").status_code == 201
    assert upload(api, token, attempt_id, "licence_back").status_code == 201
    response = submit(api, token, attempt_id)
    assert response.status_code == 200, response.text
    return attempt_id


def approve_identity(api: TestClient, token: str, attempt_id: int) -> None:
    response = decide(api, token, attempt_id, checklist=IDENTITY_CHECKLIST)
    assert response.status_code == 200, response.text


def approve_licence(api: TestClient, token: str, attempt_id: int) -> None:
    response = decide(api, token, attempt_id, checklist=LICENCE_CHECKLIST)
    assert response.status_code == 200, response.text


def onboarded_driver(api: TestClient, token: str, n: int = 1) -> dict[str, Any]:
    """A driver with consent and both checks approved by manual review."""
    driver = create_driver(api, token, n)
    record_consent(api, token, driver["id"])
    identity = submitted_identity(api, token, driver["id"])
    approve_identity(api, token, identity)
    licence = submitted_licence(api, token, driver["id"], n)
    approve_licence(api, token, licence)
    return {"driver": driver, "identity_attempt": identity, "licence_attempt": licence}


def error_code(response: Response) -> str:
    return str(response.json()["error"]["code"])
