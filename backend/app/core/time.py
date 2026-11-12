"""Business time is Asia/Kolkata; timestamps are stored in UTC.

Rent dates are local calendar dates. Every function here works only with timezone-aware
datetimes, so a naive value can never be stored by mistake.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Loaded from the IANA database (the `tzdata` package on Windows). Never a fixed offset.
BUSINESS_TZ = ZoneInfo("Asia/Kolkata")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required.")


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc(value: datetime) -> datetime:
    _require_aware(value)
    return value.astimezone(UTC)


def business_now(now: datetime | None = None) -> datetime:
    """The current time (or `now`) in Asia/Kolkata."""
    current = utc_now() if now is None else now
    _require_aware(current)
    return current.astimezone(BUSINESS_TZ)


def business_date(now: datetime | None = None) -> date:
    """The business calendar date for `now` (default: the current time)."""
    return business_now(now).date()


def due_at(rent_date: date, due_time: time, day_offset: int = 0) -> datetime:
    """When a day's rent is due: `rent_date + day_offset` at `due_time` IST, returned in UTC."""
    if day_offset < 0:
        raise ValueError("The due day offset cannot be negative.")
    local = datetime.combine(rent_date + timedelta(days=day_offset), due_time, tzinfo=BUSINESS_TZ)
    return local.astimezone(UTC)
