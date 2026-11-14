"""Two approvals that together over-fill the same day: one succeeds, the other is refused with a
reason (docs/rent-and-payments.md §5). Two real connections; the second blocks on the agreement
row lock (D53) until the first commits, then re-checks and no longer fits."""

import threading
import time as wall_clock

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.payments.allocation import confirm_days
from app.modules.payments.approval import approve_payments
from app.modules.payments.models import Payment
from app.modules.payments.schemas import ApprovalResult
from app.modules.rent.adjustments import decide_adjustment, request_adjustment
from app.modules.rent.schemas import AdjustmentCreate, AdjustmentDecision
from tests.payment_helpers import AT_SIX_THU, as_owner, as_staff, charges, items, record, world
from tests.rent_helpers import rupees


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


def test_two_approvals_that_over_fill_one_day_one_is_refused(
    app_engine: Engine, clean_db: None, test_settings: Settings
) -> None:
    app_settings = test_settings
    with Session(app_engine, expire_on_commit=False) as setup, setup.begin():
        w = world(setup)
        c2, *_ = charges(setup, w.agreement.id)
        staff = as_staff(w.manager)
        owner = as_owner(w.owner)
        first = record(setup, app_settings, staff, w.driver, rupees(200))
        confirm_days(setup, staff, first.id, items((c2, rupees(200))), now=AT_SIX_THU)
        second = record(setup, app_settings, staff, w.driver, rupees(100))
        confirm_days(setup, staff, second.id, items((c2, rupees(100))), now=AT_SIX_THU)
        # The owner waives ₹100 of 2 Nov: the day now costs ₹200, and together the two waiting
        # payments (₹200 + ₹100) over-fill it.
        adjustment = request_adjustment(
            setup,
            staff,
            c2.id,
            AdjustmentCreate(amount_paise=-rupees(100), reason="Auto in repair"),
            now=AT_SIX_THU,
        )
        decide_adjustment(
            setup, owner, adjustment.id, AdjustmentDecision(decision="approve"), now=AT_SIX_THU
        )

    outcome: dict[str, list[ApprovalResult]] = {}
    with Session(app_engine) as session_a:
        session_a.begin()
        outcome["a"] = approve_payments(
            session_a, owner, [second.id], now=AT_SIX_THU, commit_each=False
        )  # holds the locks

        def the_other_approval() -> None:
            with Session(app_engine) as session_b, session_b.begin():
                outcome["b"] = approve_payments(session_b, owner, [first.id], now=AT_SIX_THU)

        thread = threading.Thread(target=the_other_approval)
        thread.start()
        deadline = wall_clock.monotonic() + 10
        while not _waiting_on_a_lock(app_engine):
            assert wall_clock.monotonic() < deadline, "the second approval never blocked"
            wall_clock.sleep(0.05)
        session_a.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert [r.outcome for r in outcome["a"]] == ["approved"]
    (refused,) = outcome["b"]
    assert (refused.outcome, refused.code) == ("refused", "PAYMENT_NO_LONGER_FITS")
    assert refused.message
    with Session(app_engine) as check:
        statuses = dict(check.execute(select(Payment.id, Payment.status)).all())
        assert statuses == {first.id: "awaiting_approval", second.id: "approved"}
