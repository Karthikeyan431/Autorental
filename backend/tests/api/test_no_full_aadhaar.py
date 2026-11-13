"""Hard constraint 5: no field may hold a full Aadhaar number.

A real Aadhaar number has 12 digits and starts with 2-9. The probes here are built at runtime
(tests/api/aadhaar_probes.py), so no realistic number is ever a literal in a fixture, and each
is sent plain, spaced 4-4-4 and hyphenated.

1. Every text field of every request model (drivers, KYC, autos) refuses a realistic number,
   found by inspecting the models, so a new field cannot be added without the check.
2. End to end, through the API, every driver and identity text field answers 422, never echoes
   the number, and nothing is stored.
"""

import types
import typing
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, text

from app.core.config import Settings
from app.main import create_app
from app.modules.drivers import schemas as driver_schemas
from app.modules.kyc import schemas as kyc_schemas
from app.modules.vehicles import router as vehicle_router
from app.modules.vehicles import schemas as vehicle_schemas
from tests.api.aadhaar_probes import PROBES, digits_of
from tests.api.conftest import Team
from tests.api.driver_helpers import (
    create_driver,
    driver_payload,
    identity_details,
    licence_details,
    new_attempt,
    record_consent,
    submitted_identity,
)
from tests.api.helpers import API, bearer

# Text inputs that are never stored, with the reason. Everything else must refuse.
NOT_STORED = {
    ("RevealIn", "field"): "a field name matched against a fixed list; unknown names give 404",
}

MODULES = (driver_schemas, kyc_schemas, vehicle_schemas, vehicle_router)


def _accepts_text(annotation: Any) -> bool:
    if annotation is str:
        return True
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Annotated:
        return _accepts_text(args[0])
    if origin in (typing.Union, types.UnionType):
        return any(_accepts_text(a) for a in args if a is not type(None))
    if origin is list:
        return _accepts_text(args[0])
    return False


def _is_list(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is list:
        return True
    if origin is typing.Annotated:
        return _is_list(args[0])
    if origin in (typing.Union, types.UnionType):
        return any(_is_list(a) for a in args if a is not type(None))
    return False


def _request_text_fields() -> Iterator[tuple[type[BaseModel], str, bool]]:
    for module in MODULES:
        for obj in vars(module).values():
            if not (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj.__module__ == module.__name__
                and obj.model_config.get("extra") == "forbid"  # request bodies only
            ):
                continue
            for name, info in obj.model_fields.items():
                if _accepts_text(info.annotation) and (obj.__name__, name) not in NOT_STORED:
                    yield obj, name, _is_list(info.annotation)


TEXT_FIELDS = sorted(_request_text_fields(), key=lambda f: (f[0].__name__, f[1]))


def test_the_inspection_finds_the_identity_and_driver_fields() -> None:
    found = {(model.__name__, name) for model, name, _ in TEXT_FIELDS}
    expected = {
        ("DriverCreate", "full_name"),
        ("DriverCreate", "address"),
        ("DriverCreate", "mobile"),
        ("DriverUpdate", "emergency_name"),
        ("IdentityDetailsIn", "name_on_document"),
        ("IdentityDetailsIn", "id_last4"),
        ("IdentityDetailsIn", "gender"),
        ("LicenceDetailsIn", "licence_number"),
        ("LicenceDetailsIn", "vehicle_classes"),
        ("AttestationIn", "name_on_document"),
        ("ParivahanLookupIn", "lookup_status_text"),
        ("ConsentCreate", "notice_version"),
        ("DecisionIn", "reason"),
        ("VehicleCreate", "registration_number"),
    }
    assert expected <= found


@pytest.mark.parametrize(
    ("model", "field", "is_list"),
    TEXT_FIELDS,
    ids=[f"{m.__name__}.{f}" for m, f, _ in TEXT_FIELDS],
)
def test_every_request_text_field_refuses_a_realistic_number(
    model: type[BaseModel], field: str, is_list: bool
) -> None:
    for probe in PROBES:
        for value in (probe, f"Test {probe} DEMO"):
            with pytest.raises(ValidationError) as refused:
                model.model_validate({field: [value] if is_list else value})
            assert any(e["loc"][0] == field for e in refused.value.errors()), (
                f"{model.__name__}.{field} accepted a 12-digit number"
            )


# --- End to end -----------------------------------------------------------------------------------


def _refused(response: Response, probe: str) -> None:
    assert response.status_code == 422, response.text
    assert digits_of(probe) not in response.text
    assert probe not in response.text


def _stored_nowhere(app_engine: Engine) -> None:
    """No table row holds any probe (plain or formatted)."""
    with app_engine.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
            )
        ).scalars()
        dump = "\n".join(
            row
            for table in list(tables)
            for row in connection.execute(
                text(f'SELECT row_to_json(t)::text FROM "{table}" t')  # noqa: S608  # names from the catalogue
            ).scalars()
        )
    for probe in PROBES:
        assert digits_of(probe) not in dump.replace(" ", "").replace("-", "")


TEXT_DRIVER_FIELDS = ("full_name", "address", "emergency_name")
MOBILE_FIELDS = ("mobile", "alt_mobile", "emergency_mobile")


def test_driver_fields_refuse_a_realistic_number(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    owner = team.owner.token
    for probe in PROBES:
        for field in TEXT_DRIVER_FIELDS:
            payload = driver_payload(9, **{field: f"Test {probe}"})
            _refused(api.post(f"{API}/drivers", json=payload, headers=bearer(owner)), probe)
        for field in MOBILE_FIELDS:
            payload = driver_payload(9, **{field: probe})
            _refused(api.post(f"{API}/drivers", json=payload, headers=bearer(owner)), probe)

    driver = create_driver(api, owner)
    url = f"{API}/drivers/{driver['id']}"
    restriction = api.post(
        f"{url}/restrictions", json={"reason": "Test restriction"}, headers=bearer(owner)
    ).json()
    for probe in PROBES:
        for field in TEXT_DRIVER_FIELDS:
            _refused(api.patch(url, json={field: f"Test {probe}"}, headers=bearer(owner)), probe)
        for field in MOBILE_FIELDS:
            _refused(api.patch(url, json={field: probe}, headers=bearer(owner)), probe)
        reason = {"reason": f"Test {probe}"}
        _refused(
            api.post(
                f"{url}/manager",
                json={"staff_id": team.staff_b_id, **reason},
                headers=bearer(owner),
            ),
            probe,
        )
        _refused(api.post(f"{url}/suspend", json=reason, headers=bearer(owner)), probe)
        _refused(api.post(f"{url}/reactivate", json=reason, headers=bearer(owner)), probe)
        _refused(api.post(f"{url}/restrictions", json=reason, headers=bearer(owner)), probe)
        _refused(
            api.post(
                f"{API}/restrictions/{restriction['id']}/lift", json=reason, headers=bearer(owner)
            ),
            probe,
        )
    _stored_nowhere(app_engine)


def test_consent_and_identity_fields_refuse_a_realistic_number(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    owner = team.owner.token
    driver = create_driver(api, owner)
    for probe in PROBES:
        _refused(
            api.post(
                f"{API}/drivers/{driver['id']}/consents",
                json={
                    "purpose": "kyc",
                    "notice_version": f"v-{probe}",
                    "method": "in_person_checkbox",
                },
                headers=bearer(owner),
            ),
            probe,
        )
    consent = record_consent(api, owner, driver["id"])
    attempt = new_attempt(api, owner, driver["id"], "identity")
    url = f"{API}/kyc/attempts/{attempt}/identity-details"
    for probe in PROBES:
        for field, value in (
            ("name_on_document", f"Test {probe}"),
            ("gender", f"Test {probe}"),
            ("id_last4", probe),
            ("dob_or_yob", probe),
        ):
            body = identity_details(**{field: value})
            _refused(api.put(url, json=body, headers=bearer(owner)), probe)
        _refused(
            api.post(
                f"{API}/consents/{consent['id']}/withdraw",
                json={"reason": f"Test {probe}"},
                headers=bearer(owner),
            ),
            probe,
        )
    _stored_nowhere(app_engine)


def test_licence_and_parivahan_fields_refuse_a_realistic_number(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    owner = team.owner.token
    manual = create_driver(api, owner, 1)
    record_consent(api, owner, manual["id"])
    manual_attempt = new_attempt(api, owner, manual["id"], "licence")
    lookup = create_driver(api, owner, 2)
    record_consent(api, owner, lookup["id"])
    lookup_attempt = api.post(
        f"{API}/drivers/{lookup['id']}/kyc/licence/attempts",
        json={"method": "parivahan_lookup"},
        headers=bearer(owner),
    ).json()["id"]
    for probe in PROBES:
        fields: tuple[tuple[str, Any], ...] = (
            ("licence_number", probe),
            ("licence_number", f"Test {probe}"),
            ("name_on_licence", f"Test {probe}"),
            ("issuing_authority", f"Test {probe}"),
            ("vehicle_classes", [f"Test {probe}"]),
        )
        for field, value in fields:
            _refused(
                api.put(
                    f"{API}/kyc/attempts/{manual_attempt}/licence-details",
                    json=licence_details(1, **{field: value}),
                    headers=bearer(owner),
                ),
                probe,
            )
        for field, value in (*fields, ("lookup_status_text", f"Test {probe}")):
            body = {
                **licence_details(2),
                "lookup_status_text": "ACTIVE (DEMO)",
                "looked_up_at": "2026-11-13T05:00:00+00:00",
                field: value,
            }
            _refused(
                api.post(
                    f"{API}/kyc/attempts/{lookup_attempt}/parivahan-lookup",
                    json=body,
                    headers=bearer(owner),
                ),
                probe,
            )
    _stored_nowhere(app_engine)


@pytest.fixture
def attest_client(test_settings: Settings, app: FastAPI) -> Iterator[TestClient]:
    """The app with AADHAAR_APP_ATTEST_ENABLED (same database, so `team` tokens work)."""
    application = create_app(test_settings.model_copy(update={"AADHAAR_APP_ATTEST_ENABLED": True}))
    yield TestClient(
        application,
        base_url="https://testserver",
        raise_server_exceptions=False,
        client=("127.0.0.1", 50000),
    )
    application.state.engine.dispose()


def test_attestation_fields_refuse_a_realistic_number(
    attest_client: TestClient, team: Team, app_engine: Engine
) -> None:
    api, owner = attest_client, team.owner.token
    driver = create_driver(api, owner)
    record_consent(api, owner, driver["id"])
    attempt = api.post(
        f"{API}/drivers/{driver['id']}/kyc/identity/attempts",
        json={"method": "uidai_app_attested"},
        headers=bearer(owner),
    ).json()["id"]
    base = {
        "name_on_document": "Test Driver 001",
        "dob_or_yob": "1990",
        "id_last4": "0001",
        "signature_valid": True,
    }
    for probe in PROBES:
        for field, value in (
            ("name_on_document", f"Test {probe}"),
            ("gender", f"Test {probe}"),
            ("id_last4", probe),
            ("dob_or_yob", probe),
        ):
            _refused(
                api.post(
                    f"{API}/kyc/attempts/{attempt}/uidai-app-attestation",
                    json={**base, field: value},
                    headers=bearer(owner),
                ),
                probe,
            )
    _stored_nowhere(app_engine)


def test_decision_and_reopen_reasons_refuse_a_realistic_number(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    owner = team.owner.token
    driver = create_driver(api, owner)
    record_consent(api, owner, driver["id"])
    attempt = submitted_identity(api, owner, driver["id"])
    for probe in PROBES:
        for decision in ("reject", "resubmit"):
            _refused(
                api.post(
                    f"{API}/kyc/attempts/{attempt}/decision",
                    json={"decision": decision, "reason": f"Test {probe}"},
                    headers=bearer(owner),
                ),
                probe,
            )
    rejected = api.post(
        f"{API}/kyc/attempts/{attempt}/decision",
        json={"decision": "reject", "reason": "Test reason"},
        headers=bearer(owner),
    )
    assert rejected.status_code == 200, rejected.text
    for probe in PROBES:
        _refused(
            api.post(
                f"{API}/kyc/attempts/{attempt}/reopen",
                json={"reason": f"Test {probe}"},
                headers=bearer(owner),
            ),
            probe,
        )
    _stored_nowhere(app_engine)


def test_auto_fields_refuse_a_realistic_number(
    api: TestClient, team: Team, app_engine: Engine
) -> None:
    owner = team.owner.token
    base = {"registration_number": "XX00TT0101", "make": "DEMO", "model": "Test 3W"}
    vehicle = api.post(f"{API}/vehicles", json=base, headers=bearer(owner)).json()
    url = f"{API}/vehicles/{vehicle['id']}"
    for probe in PROBES:
        for field, value in (
            ("registration_number", probe),
            ("make", f"Test {probe}"),
            ("model", f"Test {probe}"),
            ("notes", f"Test {probe}"),
        ):
            body = {**base, "registration_number": "XX00TT0102", field: value}
            _refused(api.post(f"{API}/vehicles", json=body, headers=bearer(owner)), probe)
            _refused(api.patch(url, json={field: value}, headers=bearer(owner)), probe)
        _refused(
            api.post(
                f"{url}/status",
                json={"status": "maintenance", "reason": f"Test {probe}"},
                headers=bearer(owner),
            ),
            probe,
        )
        _refused(
            api.post(
                f"{url}/compliance",
                data={"kind": "insurance", "valid_until": "2027-01-01", "number": probe},
                headers=bearer(owner),
            ),
            probe,
        )
        _refused(
            api.post(
                f"{url}/maintenance",
                json={"started_on": "2026-11-13", "description": f"Test {probe}"},
                headers=bearer(owner),
            ),
            probe,
        )
    _stored_nowhere(app_engine)
