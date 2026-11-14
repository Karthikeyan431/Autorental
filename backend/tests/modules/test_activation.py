"""Agreement activation and ending (rules 2, 6 and 10; Q1, Q2; D20; D51, D52).

Activation runs in one transaction: lock the driver and the auto, check eligibility on the start
date and today, check the auto is available, set the agreement active and the auto rented, and
write the audit entry. Every refusal lists all of its reasons.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.errors import AppError
from app.core.permissions import STAFF_DEFAULTS, CurrentUser
from app.modules.agreements.models import Agreement
from app.modules.agreements.schemas import AgreementCreate, AgreementEnd
from app.modules.agreements.service import activate_agreement, create_draft, end_agreement
from app.modules.drivers.models import DriverRestriction
from app.modules.kyc.models import KycCheck
from app.modules.rent.accrual import accrue
from app.modules.rent.ledger import driver_position
from app.modules.rent.models import ChargeAdjustment, RentCharge
from app.modules.users.models import User
from tests.helpers import make_settings
from tests.rent_helpers import (
    Scene,
    ist,
    make_agreement,
    make_driver,
    make_settings_version,
    make_user,
    make_vehicle,
    rupees,
    scene,
)

TODAY = date(2026, 11, 13)  # Friday
NOW = ist(TODAY, 9)
SETTINGS = make_settings()


def staff_of(user: User) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        role=user.role,
        must_change_password=False,
        permissions=frozenset(p.value for p in STAFF_DEFAULTS),
        family_id="test-family",
    )


def _draft(db: Session, s: Scene, *, start: date = TODAY, rent: int = rupees(300)) -> Agreement:
    return create_draft(
        db,
        staff_of(s.staff),
        AgreementCreate(
            driver_id=s.driver.id,
            vehicle_id=s.vehicle.id,
            start_date=start,
            daily_rent_paise=rent,
            advance_required_paise=rupees(2000),
        ),
        now=NOW,
    )


def _activate(db: Session, s: Scene, agreement: Agreement) -> Agreement:
    return activate_agreement(db, staff_of(s.staff), agreement.id, settings=SETTINGS, now=NOW)


def _refusal(db: Session, s: Scene, agreement: Agreement) -> AppError:
    with pytest.raises(AppError) as refused:
        _activate(db, s, agreement)
    return refused.value


def _reasons(error: AppError) -> list[str]:
    assert error.code == "NOT_ELIGIBLE", error.code
    return list(error.details["reasons"])


def test_activation_sets_the_agreement_active_and_the_auto_rented(db: Session) -> None:
    s = scene(db)
    agreement = _draft(db, s)
    assert agreement.status == "draft"
    assert agreement.agreement_no.startswith("AG") and len(agreement.agreement_no) == 8

    _activate(db, s, agreement)

    assert agreement.status == "active"
    assert agreement.activated_by == s.staff.id
    assert s.vehicle.status == "rented"
    entry = db.scalars(
        select(AuditLog).where(
            AuditLog.action == "agreement.activated", AuditLog.entity_id == agreement.id
        )
    ).one()
    assert entry.actor_id == s.staff.id
    assert entry.after is not None
    assert entry.after["vehicle_status"] == "rented"


def test_the_rate_and_advance_are_stored_in_paise(db: Session) -> None:
    s = scene(db)
    agreement = _draft(db, s, rent=rupees(300))
    assert agreement.daily_rent_paise == 30_000
    assert agreement.advance_required_paise == 200_000


# --- Eligibility (rules 6 and 10) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"identity": "under_review"}, "IDENTITY_NOT_APPROVED"),
        ({"licence": "submitted"}, "LICENCE_NOT_APPROVED"),
        ({"licence": None}, "LICENCE_NOT_APPROVED"),
        ({"licence_valid_until": TODAY - timedelta(days=1)}, "LICENCE_EXPIRED"),
        ({"account_status": "suspended"}, "ACCOUNT_NOT_ACTIVE"),
        ({"account_status": "inactive"}, "ACCOUNT_NOT_ACTIVE"),
    ],
)
def test_activation_is_refused_for_each_eligibility_reason(
    db: Session, kwargs: dict[str, object], reason: str
) -> None:
    s = scene(db)
    s = Scene(s.staff, make_driver(db, s.staff, **kwargs), s.vehicle, s.settings)  # type: ignore[arg-type]
    agreement = _draft(db, s)
    assert _reasons(_refusal(db, s, agreement)) == [reason]
    assert agreement.status == "draft"
    assert s.vehicle.status == "available"


@pytest.mark.parametrize("status", ["draft", "submitted", "under_review", "rejected"])
def test_kyc_before_any_auto_every_identity_state_but_approved_is_refused(
    db: Session, status: str
) -> None:
    s = scene(db)
    s = Scene(s.staff, make_driver(db, s.staff, identity=status), s.vehicle, s.settings)
    assert _reasons(_refusal(db, s, _draft(db, s))) == ["IDENTITY_NOT_APPROVED"]


def test_a_licence_valid_until_today_is_allowed(db: Session) -> None:
    s = scene(db)
    s = Scene(s.staff, make_driver(db, s.staff, licence_valid_until=TODAY), s.vehicle, s.settings)
    assert _activate(db, s, _draft(db, s)).status == "active"


def test_the_licence_must_be_valid_on_the_start_date_and_today(db: Session) -> None:
    s = scene(db)
    # Valid on the backdated start date, but it ran out yesterday.
    driver = make_driver(db, s.staff, licence_valid_until=TODAY - timedelta(days=1))
    s = Scene(s.staff, driver, s.vehicle, s.settings)
    agreement = _draft(db, s, start=TODAY - timedelta(days=3))
    assert _reasons(_refusal(db, s, agreement)) == ["LICENCE_EXPIRED"]


def test_a_blocking_restriction_refuses_activation(db: Session) -> None:
    s = scene(db)
    db.add(
        DriverRestriction(
            driver_id=s.driver.id, reason="Test restriction", is_blocking=True, placed_by=s.staff.id
        )
    )
    db.flush()
    assert _reasons(_refusal(db, s, _draft(db, s))) == ["BLOCKING_RESTRICTION"]


def test_a_driver_with_an_active_agreement_is_already_assigned(db: Session) -> None:
    s = scene(db)
    other = make_vehicle(db, status="rented")
    make_agreement(db, s.driver, other, s.staff, start=TODAY - timedelta(days=5), status="active")
    assert _reasons(_refusal(db, s, _draft(db, s))) == ["ALREADY_ASSIGNED"]


def test_a_simulated_check_is_refused_in_production(db: Session) -> None:
    s = scene(db)
    identity = db.scalars(
        select(KycCheck).where(KycCheck.driver_id == s.driver.id, KycCheck.check_type == "identity")
    ).one()
    identity.is_simulated = True
    db.flush()
    agreement = _draft(db, s)
    production = make_settings(APP_ENV="production")
    with pytest.raises(AppError) as refused:
        activate_agreement(db, staff_of(s.staff), agreement.id, settings=production, now=NOW)
    assert _reasons(refused.value) == ["SIMULATED_VERIFICATION"]


def test_all_reasons_are_listed_together(db: Session) -> None:
    s = scene(db)
    driver = make_driver(db, s.staff, identity="rejected", account_status="suspended")
    s = Scene(s.staff, driver, s.vehicle, s.settings)
    agreement = _draft(db, s)
    s.vehicle.status = "maintenance"
    db.flush()
    assert _reasons(_refusal(db, s, agreement)) == [
        "IDENTITY_NOT_APPROVED",
        "ACCOUNT_NOT_ACTIVE",
        "VEHICLE_NOT_AVAILABLE",
    ]


# --- The auto ------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["maintenance", "inactive", "rented"])
def test_activation_is_refused_for_an_auto_that_is_not_available(db: Session, status: str) -> None:
    s = scene(db)
    agreement = _draft(db, s)
    s.vehicle.status = status  # it changed after the draft was made
    db.flush()
    assert _reasons(_refusal(db, s, agreement)) == ["VEHICLE_NOT_AVAILABLE"]
    assert agreement.status == "draft"


@pytest.mark.parametrize("status", ["maintenance", "inactive", "rented"])
def test_a_draft_cannot_choose_an_auto_that_is_not_available(db: Session, status: str) -> None:
    s = scene(db)
    s.vehicle.status = status
    db.flush()
    with pytest.raises(AppError) as refused:
        _draft(db, s)
    assert refused.value.code == "VEHICLE_NOT_AVAILABLE"


def test_after_an_agreement_ends_the_auto_cannot_start_again_on_the_return_day(
    db: Session,
) -> None:
    s = scene(db)
    first = _activate(db, s, _draft(db, s, start=TODAY - timedelta(days=5)))
    end_agreement(db, staff_of(s.staff), first.id, AgreementEnd(end_date=TODAY), now=NOW)
    assert s.vehicle.status == "available"

    second_driver = make_driver(db, s.staff)
    s2 = Scene(s.staff, second_driver, s.vehicle, s.settings)
    on_return_day = _draft(db, s2, start=TODAY)
    error = _refusal(db, s2, on_return_day)
    assert _reasons(error) == ["VEHICLE_RETURNED_ON_START"]
    assert error.details["vehicle_available_from"] == (TODAY + timedelta(days=1)).isoformat()


def test_after_an_agreement_ends_the_auto_can_start_the_next_day(db: Session) -> None:
    s = scene(db)
    first = _activate(db, s, _draft(db, s, start=TODAY - timedelta(days=5)))
    end_agreement(
        db, staff_of(s.staff), first.id, AgreementEnd(end_date=TODAY - timedelta(days=1)), now=NOW
    )
    s2 = Scene(s.staff, make_driver(db, s.staff), s.vehicle, s.settings)
    assert _activate(db, s2, _draft(db, s2, start=TODAY)).status == "active"


# --- Dates (D51) ----------------------------------------------------------------------------------


def test_the_start_date_may_be_up_to_max_backdate_days_ago(db: Session) -> None:
    s = scene(db)  # max_backdate_days = 7
    agreement = _activate(db, s, _draft(db, s, start=TODAY - timedelta(days=7)))
    assert agreement.status == "active"


def test_a_start_date_beyond_the_backdate_limit_is_refused(db: Session) -> None:
    s = scene(db)
    with pytest.raises(AppError) as refused:
        _draft(db, s, start=TODAY - timedelta(days=8))
    assert refused.value.code == "START_DATE_TOO_EARLY"
    assert refused.value.details["max_backdate_days"] == 7


def test_the_backdate_limit_is_checked_again_at_activation(db: Session) -> None:
    s = scene(db)
    agreement = _draft(db, s, start=TODAY - timedelta(days=7))
    later = ist(TODAY + timedelta(days=2), 9)
    with pytest.raises(AppError) as refused:
        activate_agreement(db, staff_of(s.staff), agreement.id, settings=SETTINGS, now=later)
    assert _reasons(refused.value) == ["START_DATE_TOO_EARLY"]


def test_the_backdate_limit_is_a_setting(db: Session) -> None:
    s = scene(db)
    make_settings_version(db, max_backdate_days=30, effective_from=ist(TODAY, 8))
    assert _activate(db, s, _draft(db, s, start=TODAY - timedelta(days=30))).status == "active"


def test_a_draft_may_start_in_the_future_but_activates_only_from_its_start_date(
    db: Session,
) -> None:
    s = scene(db)
    agreement = _draft(db, s, start=TODAY + timedelta(days=2))
    assert _reasons(_refusal(db, s, agreement)) == ["START_DATE_IN_FUTURE"]


# --- Rent due time not set (D20) ----------------------------------------------------------------


def test_activation_is_refused_until_the_rent_due_time_is_set_and_nothing_is_written(
    db: Session,
) -> None:
    staff = make_user(db)
    driver, vehicle = make_driver(db, staff), make_vehicle(db)
    agreement = make_agreement(db, driver, vehicle, staff, start=TODAY)
    audit_before = db.scalar(select(AuditLog.id).order_by(AuditLog.id.desc()).limit(1))

    with pytest.raises(AppError) as refused:
        activate_agreement(db, staff_of(staff), agreement.id, settings=SETTINGS, now=NOW)

    assert refused.value.code == "RENT_DUE_TIME_NOT_SET"
    assert refused.value.message == "Set the rent due time in Settings"
    assert (agreement.status, vehicle.status) == ("draft", "available")
    assert db.scalar(select(AuditLog.id).order_by(AuditLog.id.desc()).limit(1)) == audit_before

    make_settings_version(db, effective_from=ist(TODAY, 8))
    activate_agreement(db, staff_of(staff), agreement.id, settings=SETTINGS, now=NOW)
    assert (agreement.status, vehicle.status) == ("active", "rented")


# --- Ending (Q2, D52) -----------------------------------------------------------------------------


def _charges(db: Session, agreement: Agreement) -> list[RentCharge]:
    return list(
        db.scalars(
            select(RentCharge)
            .where(RentCharge.agreement_id == agreement.id)
            .order_by(RentCharge.rent_date)
        )
    )


def test_ending_today_frees_the_auto_and_tomorrow_gets_no_charge(db: Session) -> None:
    s = scene(db)
    agreement = _activate(db, s, _draft(db, s, start=TODAY - timedelta(days=3)))
    accrue(db, now=NOW)
    assert len(_charges(db, agreement)) == 4  # 3 days ago to today

    result = end_agreement(
        db,
        staff_of(s.staff),
        agreement.id,
        AgreementEnd(end_date=TODAY, reason="Returned"),
        now=NOW,
    )

    assert agreement.status == "ended"
    assert agreement.end_date == TODAY
    assert s.vehicle.status == "available"
    assert result.waivers == []
    assert result.vehicle_available_from == TODAY + timedelta(days=1)
    accrue(db, now=ist(TODAY + timedelta(days=1), 9))
    assert [c.rent_date for c in _charges(db, agreement)][-1] == TODAY  # Q2: return day charged
    assert (
        db.scalars(select(AuditLog).where(AuditLog.action == "agreement.ended")).one().entity_id
        == agreement.id
    )


def test_ending_yesterday_after_todays_charge_creates_one_pending_waiver(db: Session) -> None:
    s = scene(db)
    agreement = _activate(db, s, _draft(db, s, start=TODAY - timedelta(days=3)))
    accrue(db, now=ist(TODAY, 9))
    position_before = driver_position(db, s.driver.id, now=ist(TODAY, 18))

    yesterday = TODAY - timedelta(days=1)
    result = end_agreement(
        db, staff_of(s.staff), agreement.id, AgreementEnd(end_date=yesterday), now=ist(TODAY, 17)
    )

    (waiver,) = result.waivers
    todays = _charges(db, agreement)[-1]
    assert todays.rent_date == TODAY
    assert waiver.rent_charge_id == todays.id
    assert waiver.amount_paise == -todays.amount_paise
    assert waiver.status == "pending"
    assert waiver.requested_by == s.staff.id
    assert waiver.reason == "Returned on 12 Nov 2026, recorded late"
    assert len(_charges(db, agreement)) == 4  # charges stay; nothing is deleted
    # Overdue is unchanged until the owner approves the waiver.
    assert driver_position(db, s.driver.id, now=ist(TODAY, 18)) == position_before
    assert result.vehicle_available_from == TODAY
    assert (
        db.scalars(
            select(ChargeAdjustment).where(ChargeAdjustment.rent_charge_id == todays.id)
        ).one()
        is waiver
    )


def test_an_end_date_before_the_start_date_is_refused(db: Session) -> None:
    s = scene(db)
    agreement = _activate(db, s, _draft(db, s, start=TODAY - timedelta(days=2)))
    with pytest.raises(AppError) as refused:
        end_agreement(
            db,
            staff_of(s.staff),
            agreement.id,
            AgreementEnd(end_date=TODAY - timedelta(days=3)),
            now=NOW,
        )
    assert refused.value.code == "END_DATE_NOT_ALLOWED"
    assert agreement.status == "active"


def test_a_future_end_date_is_refused(db: Session) -> None:
    s = scene(db)
    agreement = _activate(db, s, _draft(db, s))
    with pytest.raises(AppError) as refused:
        end_agreement(
            db,
            staff_of(s.staff),
            agreement.id,
            AgreementEnd(end_date=TODAY + timedelta(days=1)),
            now=NOW,
        )
    assert refused.value.code == "END_DATE_NOT_ALLOWED"
    assert s.vehicle.status == "rented"


def test_only_an_active_agreement_can_be_ended(db: Session) -> None:
    s = scene(db)
    agreement = _draft(db, s)
    with pytest.raises(AppError) as refused:
        end_agreement(db, staff_of(s.staff), agreement.id, AgreementEnd(end_date=TODAY), now=NOW)
    assert refused.value.code == "AGREEMENT_INVALID_TRANSITION"


def test_an_activated_agreement_keeps_its_rate_in_the_database(db: Session) -> None:
    s = scene(db)
    agreement = _activate(db, s, _draft(db, s))
    agreement.daily_rent_paise = rupees(250)
    with pytest.raises(Exception, match="rate are fixed"):
        db.flush()


def test_staff_who_cannot_see_the_kyc_get_one_kyc_reason(db: Session) -> None:
    """D33/D46/D56: another staff member may activate, but sees KYC_NOT_COMPLETE instead of the
    driver's KYC status."""
    s = scene(db)
    driver = make_driver(db, s.staff, identity="rejected", licence_valid_until=TODAY)
    s = Scene(s.staff, driver, s.vehicle, s.settings)
    agreement = _draft(db, s)
    other = make_user(db)
    with pytest.raises(AppError) as refused:
        activate_agreement(db, staff_of(other), agreement.id, settings=SETTINGS, now=NOW)
    assert _reasons(refused.value) == ["KYC_NOT_COMPLETE"]
    assert "IDENTITY_NOT_APPROVED" not in str(refused.value.details)


def test_another_staff_member_can_activate_an_eligible_driver(db: Session) -> None:
    s = scene(db)
    agreement = _draft(db, s)
    other = make_user(db)
    activate_agreement(db, staff_of(other), agreement.id, settings=SETTINGS, now=NOW)
    assert agreement.status == "active"
    assert agreement.activated_by == other.id
