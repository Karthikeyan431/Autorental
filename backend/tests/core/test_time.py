"""Business time is Asia/Kolkata; stored timestamps are UTC."""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.core.time import (
    BUSINESS_TZ,
    ISO_MONDAY,
    ISO_SUNDAY,
    business_date,
    business_now,
    due_at,
    iso_weekday,
    to_utc,
    utc_now,
)
from app.modules.settings.schemas import SettingsChanges

IST_OFFSET = timedelta(hours=5, minutes=30)


def test_business_zone_is_kolkata() -> None:
    assert str(BUSINESS_TZ) == "Asia/Kolkata"


def test_business_date_at_2359_ist_is_the_same_day() -> None:
    # 23:59 IST on 12 Nov 2026 is 18:29 UTC on 12 Nov.
    assert business_date(datetime(2026, 11, 12, 18, 29, tzinfo=UTC)) == date(2026, 11, 12)


def test_business_date_at_0001_ist_is_the_next_day() -> None:
    # 00:01 IST on 13 Nov 2026 is 18:31 UTC on 12 Nov.
    assert business_date(datetime(2026, 11, 12, 18, 31, tzinfo=UTC)) == date(2026, 11, 13)


def test_business_date_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone"):
        business_date(datetime(2026, 11, 12, 10, 0))  # noqa: DTZ001


def test_business_now_is_aware_and_in_ist() -> None:
    now = business_now()
    assert now.utcoffset() == IST_OFFSET


def test_utc_now_is_aware_utc() -> None:
    assert utc_now().utcoffset() == timedelta(0)


def test_due_time_same_day_is_stored_as_utc() -> None:
    result = due_at(date(2026, 11, 2), time(10, 0))
    assert result == datetime(2026, 11, 2, 4, 30, tzinfo=UTC)
    assert result.utcoffset() == timedelta(0)


def test_due_time_with_next_day_offset() -> None:
    assert due_at(date(2026, 11, 2), time(10, 0), day_offset=1) == datetime(
        2026, 11, 3, 4, 30, tzinfo=UTC
    )


def test_early_morning_due_time_falls_on_the_previous_utc_day() -> None:
    assert due_at(date(2026, 11, 5), time(2, 0)) == datetime(2026, 11, 4, 20, 30, tzinfo=UTC)


def test_due_time_across_month_end() -> None:
    assert due_at(date(2026, 11, 30), time(10, 0), day_offset=1) == datetime(
        2026, 12, 1, 4, 30, tzinfo=UTC
    )


def test_negative_day_offset_is_refused() -> None:
    with pytest.raises(ValueError, match="offset"):
        due_at(date(2026, 11, 2), time(10, 0), day_offset=-1)


def test_to_utc_converts_ist() -> None:
    ist = datetime(2026, 11, 12, 10, 0, tzinfo=BUSINESS_TZ)
    assert to_utc(ist) == datetime(2026, 11, 12, 4, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 11, 2), 1),  # Monday
        (date(2026, 11, 3), 2),
        (date(2026, 11, 7), 6),  # Saturday
        (date(2026, 11, 8), 7),  # Sunday
        (date(2028, 2, 29), 2),  # leap day, a Tuesday
    ],
)
def test_weekdays_are_iso_monday_1_to_sunday_7(day: date, expected: int) -> None:
    assert iso_weekday(day) == expected


def test_iso_weekday_is_not_python_weekday() -> None:
    monday, sunday = date(2026, 11, 2), date(2026, 11, 8)
    assert (iso_weekday(monday), monday.weekday()) == (ISO_MONDAY, 0)
    assert (iso_weekday(sunday), sunday.weekday()) == (ISO_SUNDAY, 6)


def test_weekly_pay_day_setting_uses_the_same_numbering() -> None:
    assert SettingsChanges(weekly_pay_day=ISO_MONDAY).weekly_pay_day == iso_weekday(
        date(2026, 11, 2)
    )
    assert SettingsChanges(weekly_pay_day=ISO_SUNDAY).weekly_pay_day == iso_weekday(
        date(2026, 11, 8)
    )


def test_to_utc_rejects_naive() -> None:
    with pytest.raises(ValueError, match="timezone"):
        to_utc(datetime(2026, 11, 12, 10, 0))  # noqa: DTZ001
