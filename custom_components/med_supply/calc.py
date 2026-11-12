"""Pure supply calculations — no Home Assistant imports, unit-testable.

Supply is tracked in milligrams. A snapshot (base_mg at base_ts) is stored;
the current supply is derived by subtracting every scheduled intake that has
passed since then. That keeps the value correct across restarts and downtime.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

EPSILON = 1e-9
MAX_PROJECTION_DAYS = 3650


@dataclass(frozen=True)
class Slot:
    """One scheduled intake per day."""

    key: str
    at: time
    dose_mg: float


@dataclass(frozen=True)
class Projection:
    """Result of projecting the supply into the future."""

    empty_at: datetime | None
    """First intake that can no longer be taken in full (None: no intakes planned)."""

    days_left: int | None
    """Calendar days from today until empty_at's date."""


def active_slots(slots: Sequence[Slot]) -> list[Slot]:
    """Slots with a dose, ordered by time of day."""
    return sorted((s for s in slots if s.dose_mg > EPSILON), key=lambda s: s.at)


def daily_dose_mg(slots: Sequence[Slot]) -> float:
    """Total milligrams per day."""
    return sum(s.dose_mg for s in active_slots(slots))


def iter_intakes(
    slots: Sequence[Slot], after: datetime, tz: tzinfo
) -> Iterator[tuple[datetime, Slot]]:
    """Yield scheduled intakes strictly after `after`, in chronological order."""
    plan = active_slots(slots)
    if not plan:
        return
    after = after.astimezone(tz)
    day = after.date()
    last_day = day + timedelta(days=MAX_PROJECTION_DAYS)
    while day <= last_day:
        for slot in plan:
            at = datetime.combine(day, slot.at, tzinfo=tz)
            if at > after:
                yield at, slot
        day += timedelta(days=1)


def consumed_mg(
    slots: Sequence[Slot], start: datetime, end: datetime, tz: tzinfo
) -> float:
    """Milligrams taken by intakes in the interval (start, end]."""
    total = 0.0
    for at, slot in iter_intakes(slots, start, tz):
        if at > end:
            break
        total += slot.dose_mg
    return total


def current_mg(
    base_mg: float,
    base_ts: datetime,
    slots: Sequence[Slot],
    now: datetime,
    tz: tzinfo,
) -> float:
    """Current supply in mg, never below zero."""
    if now <= base_ts:
        return max(base_mg, 0.0)
    return max(base_mg - consumed_mg(slots, base_ts, now, tz), 0.0)


def project(
    stock_mg: float, slots: Sequence[Slot], now: datetime, tz: tzinfo
) -> Projection:
    """Find the first intake the supply cannot cover."""
    if daily_dose_mg(slots) <= EPSILON:
        return Projection(empty_at=None, days_left=None)
    remaining = stock_mg
    today = now.astimezone(tz).date()
    first = True
    for at, slot in iter_intakes(slots, now, tz):
        if remaining + EPSILON < slot.dose_mg:
            if first:
                # Not even the next intake is covered: empty right now.
                return Projection(empty_at=now.astimezone(tz), days_left=0)
            return Projection(empty_at=at, days_left=(at.date() - today).days)
        remaining -= slot.dose_mg
        first = False
    return Projection(empty_at=None, days_left=None)


def prescription_due(empty_at: datetime | None, lead_days: int) -> date | None:
    """Latest day to get a new prescription."""
    if empty_at is None:
        return None
    return empty_at.date() - timedelta(days=lead_days)


@dataclass(frozen=True)
class Lot:
    """Tablets of one strength, in booking order (oldest first)."""

    strength_mg: float
    mg: float

    @property
    def tablets(self) -> float:
        return self.mg / self.strength_mg


def consume_fifo(lots: Sequence[Lot], amount_mg: float) -> list[Lot]:
    """Take `amount_mg` from the oldest lots first; drop lots that are used up."""
    remaining = amount_mg
    result: list[Lot] = []
    for lot in lots:
        if remaining <= EPSILON:
            result.append(lot)
            continue
        taken = min(lot.mg, remaining)
        remaining -= taken
        if lot.mg - taken > EPSILON:
            result.append(Lot(lot.strength_mg, lot.mg - taken))
    return result


def add_lot(lots: Sequence[Lot], strength_mg: float, mg: float) -> list[Lot]:
    """Append tablets; merge into the newest lot if it has the same strength."""
    result = list(lots)
    if result and abs(result[-1].strength_mg - strength_mg) < EPSILON:
        result[-1] = Lot(strength_mg, result[-1].mg + mg)
    elif mg > EPSILON:
        result.append(Lot(strength_mg, mg))
    return result


def total_mg(lots: Sequence[Lot]) -> float:
    return sum(lot.mg for lot in lots)


def tablets(dose_mg: float, strength_mg: float) -> float:
    """Number of tablets of the given strength for a dose."""
    return dose_mg / strength_mg


def is_divisible(dose_mg: float, strength_mg: float, step: float = 0.5) -> bool:
    """True if the dose can be taken with whole/half (by `step`) tablets."""
    units = tablets(dose_mg, strength_mg) / step
    return abs(units - round(units)) < 1e-6


def format_count(value: float) -> str:
    """Format a tablet count: 2, 1.5, 0.25 — German decimal comma."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def format_mg(value: float) -> str:
    """Format a milligram value: 10 mg, 2,5 mg."""
    return f"{format_count(value)} mg"


STATUS_OK = "ok"
STATUS_DUE = "due"
STATUS_REQUESTED = "requested"
STATUS_EMPTY = "empty"
STATUSES = [STATUS_OK, STATUS_DUE, STATUS_REQUESTED, STATUS_EMPTY]


def status(days_left: int | None, lead_days: int, requested: bool) -> str:
    """Derive the prescription status."""
    if days_left is not None and days_left <= 0:
        return STATUS_EMPTY
    if requested:
        return STATUS_REQUESTED
    if days_left is not None and days_left <= lead_days:
        return STATUS_DUE
    return STATUS_OK
