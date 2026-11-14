"""The pay request job (N4): nothing before pay_request_time; accrues, then generates; refuses
without a UPI ID."""

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.jobs.pay_requests import NOT_YET, run_pay_requests
from app.modules.pay_requests.models import PayRequest
from tests.payment_helpers import world
from tests.rent_helpers import ist

FRI = date(2026, 11, 6)


def _count(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(PayRequest)) or 0)


def test_nothing_before_the_pay_request_time(db: Session) -> None:
    world(db)
    assert run_pay_requests(db, ist(FRI, 7, 59)) == NOT_YET
    assert _count(db) == 0


def test_after_the_time_it_accrues_and_generates_once(db: Session) -> None:
    w = world(db)
    result = run_pay_requests(db, ist(FRI, 8, 0))
    assert not isinstance(result, str) and result.created == 1
    again = run_pay_requests(db, ist(FRI, 8, 15))
    assert not isinstance(again, str) and (again.created, again.unchanged) == (0, 1)
    request = db.scalars(select(PayRequest).where(PayRequest.driver_id == w.driver.id)).one()
    assert request.amount_paise == 5 * 30_000  # 2 to 6 November, Friday accrued by the job


def test_without_a_upi_id_it_refuses(db: Session) -> None:
    world(db, upi_id=None)
    with pytest.raises(AppError) as exc:
        run_pay_requests(db, ist(FRI, 9))
    assert exc.value.code == "UPI_ID_NOT_SET"
