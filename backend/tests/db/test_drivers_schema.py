"""Database guards for drivers and KYC: they hold even if the service is bypassed."""

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session


def _staff(db: Session, n: int) -> int:
    return int(
        db.scalar(
            text(
                "INSERT INTO users (name, mobile, password_hash, role) "
                "VALUES (:name, :mobile, 'not-a-real-hash', 'staff') RETURNING id"
            ),
            {"name": f"Test Staff {n:03d}", "mobile": f"+91900000{n:04d}"},
        )
        or 0
    )


def _driver(db: Session, staff_id: int, n: int = 1) -> int:
    return int(
        db.scalar(
            text(
                "INSERT INTO drivers (full_name, mobile, address, date_of_birth, created_by, "
                "managed_by) VALUES (:name, :mobile, 'Test address', :dob, :staff, :staff) "
                "RETURNING id"
            ),
            {
                "name": f"Test Driver {n:03d}",
                "mobile": f"+9190000{n:05d}",
                "dob": date(1990, 1, 1),
                "staff": staff_id,
            },
        )
        or 0
    )


def test_driver_code_comes_from_the_sequence(db: Session) -> None:
    staff = _staff(db, 401)
    first = _driver(db, staff, 1)
    second = _driver(db, staff, 2)
    codes = db.execute(
        text("SELECT id, code FROM drivers WHERE id IN (:a, :b) ORDER BY id"),
        {"a": first, "b": second},
    ).all()
    numbers = [int(code[1:]) for _, code in codes]
    assert all(code.startswith("D") and len(code) >= 5 for _, code in codes)
    assert numbers[1] == numbers[0] + 1


def test_a_direct_update_of_created_by_is_refused(db: Session) -> None:
    staff = _staff(db, 402)
    other = _staff(db, 403)
    driver = _driver(db, staff)
    with pytest.raises(DBAPIError, match="created_by"):
        db.execute(
            text("UPDATE drivers SET created_by = :other WHERE id = :id"),
            {"other": other, "id": driver},
        )


def test_a_direct_update_of_the_code_is_refused(db: Session) -> None:
    staff = _staff(db, 404)
    driver = _driver(db, staff)
    with pytest.raises(DBAPIError, match="code"):
        db.execute(text("UPDATE drivers SET code = 'D9999' WHERE id = :id"), {"id": driver})


def test_other_driver_fields_can_still_be_updated(db: Session) -> None:
    staff = _staff(db, 405)
    other = _staff(db, 406)
    driver = _driver(db, staff)
    db.execute(
        text("UPDATE drivers SET managed_by = :other, address = 'New' WHERE id = :id"),
        {"other": other, "id": driver},
    )


def test_a_duplicate_driver_mobile_is_refused_by_the_database(db: Session) -> None:
    staff = _staff(db, 407)
    _driver(db, staff, 1)
    with pytest.raises(IntegrityError):
        _driver(db, staff, 1)


def _licence(db: Session, driver_id: int, check_hash: str, attempt_no: int = 1) -> None:
    check_id = db.scalar(
        text(
            "INSERT INTO kyc_checks (driver_id, check_type, attempt_no, method, status, "
            "is_current) VALUES (:d, 'licence', :n, 'manual', 'draft', false) RETURNING id"
        ),
        {"d": driver_id, "n": attempt_no},
    )
    db.execute(
        text(
            "INSERT INTO licence_details (kyc_check_id, driver_id, licence_number, "
            "licence_number_hash, licence_number_last4, name_on_licence) "
            "VALUES (:c, :d, 'f1:not-real', :h, '0001', 'Test Driver')"
        ),
        {"c": check_id, "d": driver_id, "h": check_hash},
    )


def test_one_licence_number_cannot_belong_to_two_drivers(db: Session) -> None:
    staff = _staff(db, 408)
    first = _driver(db, staff, 1)
    second = _driver(db, staff, 2)
    _licence(db, first, "same-hash", 1)
    _licence(db, first, "same-hash", 2)  # the same driver's next attempt is fine
    with pytest.raises(IntegrityError):
        _licence(db, second, "same-hash", 1)


def test_only_one_current_attempt_per_check(db: Session) -> None:
    staff = _staff(db, 409)
    driver = _driver(db, staff)
    insert = text(
        "INSERT INTO kyc_checks (driver_id, check_type, attempt_no, method, status, is_current) "
        "VALUES (:d, 'identity', :n, 'manual', 'draft', true)"
    )
    db.execute(insert, {"d": driver, "n": 1})
    with pytest.raises(IntegrityError):
        db.execute(insert, {"d": driver, "n": 2})


def test_identity_details_keep_only_four_digits(db: Session) -> None:
    staff = _staff(db, 410)
    driver = _driver(db, staff)
    check_id = db.scalar(
        text(
            "INSERT INTO kyc_checks (driver_id, check_type, attempt_no, method, status, "
            "is_current) VALUES (:d, 'identity', 1, 'manual', 'draft', true) RETURNING id"
        ),
        {"d": driver},
    )
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO identity_details (kyc_check_id, document_type, id_last4) "
                "VALUES (:c, 'masked_aadhaar', '123412341234')"
            ),
            {"c": check_id},
        )


def test_one_open_manager_row_per_driver(db: Session) -> None:
    staff = _staff(db, 411)
    driver = _driver(db, staff)
    insert = text(
        "INSERT INTO driver_manager_history (driver_id, staff_id, from_at, changed_by) "
        "VALUES (:d, :s, now(), :s)"
    )
    db.execute(insert, {"d": driver, "s": staff})
    with pytest.raises(IntegrityError):
        db.execute(insert, {"d": driver, "s": staff})


def test_week_3_tables_get_ordinary_grants(db: Session) -> None:
    for table in (
        "drivers",
        "driver_manager_history",
        "driver_restrictions",
        "consents",
        "documents",
        "kyc_checks",
        "identity_details",
        "licence_details",
        "alerts",
    ):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert db.scalar(
                text("SELECT has_table_privilege('app_user', :t, :p)"),
                {"t": table, "p": privilege},
            ), f"{table} {privilege}"


def test_week_3_insert_only_tables_exist(db: Session) -> None:
    for table in ("kyc_events", "document_access_log"):
        assert db.scalar(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"})
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not db.scalar(
                text("SELECT has_table_privilege('app_user', :t, :p)"),
                {"t": table, "p": privilege},
            ), f"{table} {privilege}"
