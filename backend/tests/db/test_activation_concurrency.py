"""Two staff members activate the same auto for different drivers at the same moment: exactly one
succeeds (rule 2). Two real connections; the second blocks on the auto's row lock until the first
commits, then sees the auto rented and is refused."""

import threading
import time as wall_clock
from datetime import date

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.agreements.models import Agreement
from app.modules.agreements.service import activate_agreement
from app.modules.vehicles.models import Vehicle
from tests.helpers import make_settings
from tests.modules.test_activation import staff_of
from tests.rent_helpers import ist, make_agreement, make_driver, scene

TODAY = date(2026, 11, 13)
NOW = ist(TODAY, 9)
SETTINGS = make_settings()


def _waiting_on_a_lock(engine: Engine) -> bool:
    with engine.connect() as probe:
        return bool(
            probe.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
        )


def test_exactly_one_of_two_simultaneous_activations_succeeds(
    app_engine: Engine, clean_db: None
) -> None:
    with Session(app_engine, expire_on_commit=False) as setup, setup.begin():
        s = scene(setup)
        other_driver = make_driver(setup, s.staff)
        first = make_agreement(setup, s.driver, s.vehicle, s.staff, start=TODAY)
        second = make_agreement(setup, other_driver, s.vehicle, s.staff, start=TODAY)
    user = staff_of(s.staff)

    outcome: dict[str, object] = {}

    with Session(app_engine) as session_a:
        session_a.begin()
        activate_agreement(session_a, user, first.id, settings=SETTINGS, now=NOW)  # holds locks

        def second_staff_member() -> None:
            with Session(app_engine) as session_b, session_b.begin():
                try:
                    activate_agreement(session_b, user, second.id, settings=SETTINGS, now=NOW)
                    outcome["b"] = "activated"
                except AppError as exc:
                    outcome["b"] = exc.details.get("reasons", exc.code)

        thread = threading.Thread(target=second_staff_member)
        thread.start()
        deadline = wall_clock.monotonic() + 10
        while not _waiting_on_a_lock(app_engine):
            assert wall_clock.monotonic() < deadline, "the second activation never blocked"
            wall_clock.sleep(0.05)
        session_a.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert outcome["b"] == ["VEHICLE_NOT_AVAILABLE"]
    with Session(app_engine) as check:
        statuses = {r.id: r.status for r in check.execute(select(Agreement.id, Agreement.status))}
        assert statuses == {first.id: "active", second.id: "draft"}
        assert check.scalar(select(Vehicle.status).where(Vehicle.id == s.vehicle.id)) == "rented"
