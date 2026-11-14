"""The development scheduler: off unless APP_ENV=development and DEV_SCHEDULER_ENABLED=true, and
an accrual it cannot run (no rent due time, D20) is logged, never raised into the API."""

import logging

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.scheduler import run_accrual, start_dev_scheduler
from app.modules.rent.models import RentCharge
from tests.helpers import make_settings


def test_off_outside_development_or_without_the_flag(app_engine: Engine) -> None:
    factory = sessionmaker(bind=app_engine)
    assert (
        start_dev_scheduler(make_settings(APP_ENV="test", DEV_SCHEDULER_ENABLED=True), factory)
        is None
    )
    assert start_dev_scheduler(make_settings(APP_ENV="development"), factory) is None


def test_on_in_development_with_the_flag(app_engine: Engine, clean_db: None) -> None:
    factory = sessionmaker(bind=app_engine)
    scheduler = start_dev_scheduler(
        make_settings(APP_ENV="development", DEV_SCHEDULER_ENABLED=True), factory
    )
    assert scheduler is not None
    try:
        assert [job.id for job in scheduler.get_jobs()] == ["rent-accrual"]
    finally:
        scheduler.shutdown(wait=False)


def test_an_accrual_without_a_due_time_is_logged_not_raised(
    app_engine: Engine, clean_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="arms.scheduler"):
        run_accrual(sessionmaker(bind=app_engine))
    assert "RENT_DUE_TIME_NOT_SET" in caplog.text
    with Session(app_engine) as check:
        assert check.scalar(select(func.count()).select_from(RentCharge)) == 0
