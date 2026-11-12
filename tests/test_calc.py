"""Pure calculation tests."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from custom_components.med_supply import calc
from custom_components.med_supply.calc import Slot

TZ = ZoneInfo("Europe/Berlin")
PLAN = [
    Slot("morning", time(8, 0), 10.0),
    Slot("noon", time(12, 0), 0.0),
    Slot("evening", time(20, 0), 10.0),
    Slot("night", time(22, 0), 0.0),
]


def at(day: int, hour: int, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


def test_daily_dose_ignores_unused_slots():
    assert calc.daily_dose_mg(PLAN) == 20.0
    assert [s.key for s in calc.active_slots(PLAN)] == ["morning", "evening"]


def test_consumed_counts_intakes_in_half_open_interval():
    # (start, end]: an intake exactly at start is not counted, at end it is.
    assert calc.consumed_mg(PLAN, at(12, 8), at(12, 20), TZ) == 10.0
    assert calc.consumed_mg(PLAN, at(12, 7), at(12, 20), TZ) == 20.0
    assert calc.consumed_mg(PLAN, at(12, 7), at(19, 7), TZ) == 140.0


def test_current_never_negative_and_ignores_future_base():
    assert calc.current_mg(15.0, at(12, 7), PLAN, at(13, 9), TZ) == 0.0
    assert calc.current_mg(15.0, at(12, 7), PLAN, at(12, 6), TZ) == 15.0


def test_projection_two_tablets_per_intake():
    # 31 tablets à 5 mg = 155 mg on 12.11. 10:00, 10 mg morning + evening.
    # 15 full intakes are covered (12.11. 20:00 … 19.11. 20:00), 20.11. 08:00 fails.
    p = calc.project(155.0, PLAN, at(12, 10), TZ)
    assert p.empty_at == at(20, 8)
    assert p.days_left == 8
    assert calc.prescription_due(p.empty_at, 14).isoformat() == "2026-11-06"


def test_projection_exact_supply_runs_out_after_last_dose():
    p = calc.project(20.0, PLAN, at(12, 7), TZ)
    assert p.empty_at == at(13, 8)
    assert p.days_left == 1


def test_projection_partial_dose_counts_as_empty():
    # 5 mg left, next dose is 10 mg → empty at the next intake.
    p = calc.project(5.0, PLAN, at(12, 7), TZ)
    assert p.empty_at == at(12, 8)
    assert p.days_left == 0


def test_projection_without_plan():
    p = calc.project(100.0, [Slot("morning", time(8), 0.0)], at(12, 7), TZ)
    assert p.empty_at is None and p.days_left is None


def test_dst_change_does_not_skip_or_double_intakes():
    # Europe/Berlin switches to summer time on 2026-03-29 and back on 2026-10-25.
    for day, month in ((29, 3), (25, 10)):
        start = datetime(2026, month, day - 1, 21, tzinfo=TZ)
        end = datetime(2026, month, day, 21, tzinfo=TZ)
        assert calc.consumed_mg(PLAN, start, end, TZ) == 20.0


def test_divisible():
    assert calc.is_divisible(10, 5)
    assert calc.is_divisible(5, 10)  # half tablet
    assert not calc.is_divisible(7.5, 10)
    assert calc.is_divisible(2.5, 5)
    assert calc.is_divisible(7.5, 2.5)


def test_status():
    assert calc.status(30, 14, False) == calc.STATUS_OK
    assert calc.status(14, 14, False) == calc.STATUS_DUE
    assert calc.status(10, 14, True) == calc.STATUS_REQUESTED
    assert calc.status(0, 14, True) == calc.STATUS_EMPTY
    assert calc.status(None, 14, False) == calc.STATUS_OK


def test_formatting():
    assert calc.format_count(2.0) == "2"
    assert calc.format_count(1.5) == "1,5"
    assert calc.format_mg(2.5) == "2,5 mg"
