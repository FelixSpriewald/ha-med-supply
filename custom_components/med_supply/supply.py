"""Runtime state of one medication (one config entry)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import calc
from .const import (
    ACTION_REQUESTED,
    ACTION_SNOOZE,
    CONF_INITIAL_TABLETS,
    CONF_LEAD_DAYS,
    CONF_NAME,
    CONF_NOTIFY_SERVICE,
    CONF_PACKAGE_SIZE,
    CONF_PLAN,
    CONF_REMINDER,
    CONF_REMINDER_TIME,
    CONF_SHOW_NAME,
    CONF_STRENGTH_MG,
    DEFAULT_LEAD_DAYS,
    DEFAULT_REMINDER_TIME,
    DOMAIN,
    PICKUP_WARNING_DAYS,
    SLOT_DEFAULT_TIMES,
    SLOT_KEYS,
    SLOT_LABELS_DE,
    SNOOZE_HOURS,
    STORAGE_VERSION,
    slot_dose_key,
    slot_time_key,
)

_LOGGER = logging.getLogger(__name__)

KEY_BASE_MG = "base_mg"  # v0.1/0.2 storage, migrated to KEY_LOTS
KEY_LOTS = "lots"
KEY_BASE_TS = "base_ts"
KEY_REQUESTED = "requested"
KEY_LAST_STRENGTH = "last_strength_mg"


@dataclass(frozen=True)
class Snapshot:
    """Derived values, recomputed on every change and at every intake."""

    stock_mg: float
    stock_tablets: float
    lots: list[calc.Lot]
    strength_mg: float
    """Strength currently being used up (oldest lot), shown in the plan."""
    daily_dose_mg: float
    days_left: int | None
    empty_at: datetime | None
    prescription_due: date | None
    next_intake: datetime | None
    status: str


def _parse_time(value: str) -> time:
    return time.fromisoformat(value)


def _plural_days(days: int) -> str:
    return "1 Tag" if days == 1 else f"{days} Tage"


class MedSupply:
    """One medication: stored snapshot + plan from options."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._data: dict[str, Any] = {}
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._snooze_unsub: CALLBACK_TYPE | None = None
        self.snapshot: Snapshot | None = None
        # Draft number entities ("addition", "counted"), registered by number.py
        self.drafts: dict[str, Any] = {}

    # ------------------------------------------------------------------ config

    @property
    def name(self) -> str:
        return self.entry.data[CONF_NAME]

    @property
    def default_strength_mg(self) -> float:
        return float(self.entry.options[CONF_STRENGTH_MG])

    @property
    def booking_strength_mg(self) -> float:
        """Default strength for the next booking: the last one booked."""
        return float(self._data.get(KEY_LAST_STRENGTH) or self.default_strength_mg)

    @property
    def strength_mg(self) -> float:
        """Strength currently being used up."""
        if self.snapshot is not None:
            return self.snapshot.strength_mg
        return self.default_strength_mg

    @property
    def package_size(self) -> float:
        return float(self.entry.options.get(CONF_PACKAGE_SIZE) or 0)

    @property
    def _reminder(self) -> dict[str, Any]:
        return self.entry.options.get(CONF_REMINDER, {})

    @property
    def lead_days(self) -> int:
        return int(self._reminder.get(CONF_LEAD_DAYS, DEFAULT_LEAD_DAYS))

    @property
    def reminder_time(self) -> time:
        return _parse_time(
            self._reminder.get(CONF_REMINDER_TIME) or DEFAULT_REMINDER_TIME
        )

    @property
    def notify_service(self) -> str | None:
        return self._reminder.get(CONF_NOTIFY_SERVICE) or None

    @property
    def show_name(self) -> bool:
        return bool(self._reminder.get(CONF_SHOW_NAME, False))

    @property
    def slots(self) -> list[calc.Slot]:
        plan = self.entry.options.get(CONF_PLAN, {})
        return [
            calc.Slot(
                key=key,
                at=_parse_time(plan.get(slot_time_key(key)) or SLOT_DEFAULT_TIMES[key]),
                dose_mg=float(plan.get(slot_dose_key(key)) or 0),
            )
            for key in SLOT_KEYS
        ]

    @property
    def requested(self) -> bool:
        return bool(self._data.get(KEY_REQUESTED, False))

    def plan_text(self) -> str:
        """Human readable plan, e.g. 'morgens 10 mg (2× 5 mg), abends 10 mg (2× 5 mg)'."""
        parts = []
        for slot in calc.active_slots(self.slots):
            count = calc.format_count(calc.tablets(slot.dose_mg, self.strength_mg))
            parts.append(
                f"{SLOT_LABELS_DE[slot.key]} {calc.format_mg(slot.dose_mg)} "
                f"({count}× {calc.format_mg(self.strength_mg)})"
            )
        return ", ".join(parts) or "kein Einnahmeplan"

    # --------------------------------------------------------------- lifecycle

    @property
    def _tz(self):
        return dt_util.get_time_zone(self.hass.config.time_zone) or dt_util.UTC

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data is None:
            initial = float(self.entry.data.get(CONF_INITIAL_TABLETS) or 0)
            strength = self.default_strength_mg
            data = {
                KEY_LOTS: [{"strength_mg": strength, "mg": initial * strength}] if initial else [],
                KEY_BASE_TS: dt_util.now().isoformat(),
                KEY_REQUESTED: False,
            }
            await self._store.async_save(data)
        if KEY_LOTS not in data:  # migrate single-strength storage
            base_mg = float(data.pop(KEY_BASE_MG, 0) or 0)
            strength = self.default_strength_mg
            data[KEY_LOTS] = [{"strength_mg": strength, "mg": base_mg}] if base_mg > 0 else []
            await self._store.async_save(data)
        self._data = data
        self._recompute()

    @callback
    def async_start(self) -> None:
        """Refresh at every intake, after midnight and at reminder time."""
        for slot in calc.active_slots(self.slots):
            self._unsubs.append(
                async_track_time_change(
                    self.hass,
                    self._handle_tick,
                    hour=slot.at.hour,
                    minute=slot.at.minute,
                    second=slot.at.second,
                )
            )
        self._unsubs.append(
            async_track_time_change(self.hass, self._handle_tick, hour=0, minute=0, second=5)
        )
        reminder = self.reminder_time
        self._unsubs.append(
            async_track_time_change(
                self.hass,
                self._handle_reminder_time,
                hour=reminder.hour,
                minute=reminder.minute,
                second=reminder.second,
            )
        )

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_snooze()

    async def async_remove_store(self) -> None:
        await self._store.async_remove()

    # ------------------------------------------------------------- listeners

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> Callable[[], None]:
        self._listeners.append(update)

        @callback
        def remove() -> None:
            self._listeners.remove(update)

        return remove

    @callback
    def _notify_listeners(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def _handle_tick(self, _now: datetime) -> None:
        self._recompute()
        self._notify_listeners()

    async def _handle_reminder_time(self, _now: datetime) -> None:
        self._recompute()
        self._notify_listeners()
        await self.async_send_reminder()

    # -------------------------------------------------------------- the math

    def _base_lots(self) -> list[calc.Lot]:
        return [calc.Lot(float(x["strength_mg"]), float(x["mg"])) for x in self._data[KEY_LOTS]]

    def _store_lots(self, lots: list[calc.Lot], now: datetime) -> None:
        self._data[KEY_LOTS] = [{"strength_mg": lot.strength_mg, "mg": lot.mg} for lot in lots]
        self._data[KEY_BASE_TS] = now.isoformat()

    def _current_lots(self, now: datetime) -> list[calc.Lot]:
        base_ts = dt_util.parse_datetime(self._data[KEY_BASE_TS])
        assert base_ts is not None
        lots = self._base_lots()
        if now <= base_ts:
            return lots
        return calc.consume_fifo(lots, calc.consumed_mg(self.slots, base_ts, now, self._tz))

    @callback
    def _recompute(self) -> None:
        now = dt_util.now()
        slots = self.slots
        lots = self._current_lots(now)
        stock_mg = calc.total_mg(lots)
        strength = lots[0].strength_mg if lots else self.booking_strength_mg
        projection = calc.project(stock_mg, slots, now, self._tz)
        next_intake = next(iter(calc.iter_intakes(slots, now, self._tz)), None)
        self.snapshot = Snapshot(
            stock_mg=stock_mg,
            stock_tablets=sum(lot.tablets for lot in lots),
            lots=lots,
            strength_mg=strength,
            daily_dose_mg=calc.daily_dose_mg(slots),
            days_left=projection.days_left,
            empty_at=projection.empty_at,
            prescription_due=calc.prescription_due(projection.empty_at, self.lead_days),
            next_intake=next_intake[0] if next_intake else None,
            status=calc.status(projection.days_left, self.lead_days, self.requested),
        )

    # -------------------------------------------------------------- mutations

    async def _async_save_and_update(self) -> None:
        await self._store.async_save(self._data)
        self._recompute()
        self._notify_listeners()

    async def async_rebase(self) -> None:
        """Freeze the current supply as new base (call before changing the plan)."""
        now = dt_util.now()
        self._store_lots(self._current_lots(now), now)
        await self._store.async_save(self._data)

    def _clear_request_if_covered(self) -> None:
        self._recompute()
        assert self.snapshot is not None
        days_left = self.snapshot.days_left
        if days_left is None or days_left > self.lead_days:
            self._data[KEY_REQUESTED] = False

    async def async_add_tablets(self, tablets: float, strength_mg: float | None = None) -> None:
        """Book an addition (new package). Clears a pending prescription request."""
        now = dt_util.now()
        strength = strength_mg or self.booking_strength_mg
        self._store_lots(calc.add_lot(self._current_lots(now), strength, tablets * strength), now)
        self._data[KEY_LAST_STRENGTH] = strength
        self._data[KEY_REQUESTED] = False
        self._cancel_snooze()
        await self._async_save_and_update()

    async def async_set_tablets(self, tablets: float, strength_mg: float | None = None) -> None:
        """Correct the supply after counting: replaces everything with one strength."""
        strength = strength_mg or self.strength_mg
        self._store_lots(calc.add_lot([], strength, tablets * strength), dt_util.now())
        self._data[KEY_LAST_STRENGTH] = strength
        self._clear_request_if_covered()
        await self._async_save_and_update()

    async def async_set_requested(self, requested: bool) -> None:
        self._data[KEY_REQUESTED] = requested
        if requested:
            self._cancel_snooze()
            await self._async_clear_notification()
        await self._async_save_and_update()

    # ---------------------------------------------------------- notifications

    def _label(self) -> str:
        return self.name if self.show_name else "Ein Medikament"

    async def async_send_reminder(self, force: bool = False) -> bool:
        """Send the push that fits the current status. Returns True if sent."""
        if not self.notify_service:
            return False
        self._recompute()
        snap = self.snapshot
        assert snap is not None
        label = self._label()
        tag = f"{DOMAIN}_{self.entry.entry_id}"
        snooze = {"action": f"{ACTION_SNOOZE}{self.entry.entry_id}", "title": f"In {SNOOZE_HOURS} h erinnern"}

        if self.requested:
            if snap.days_left is None or (snap.days_left > PICKUP_WARNING_DAYS and not force):
                return False
            title = "Packung abholen"
            if snap.days_left is not None and snap.days_left <= 0:
                message = f"{label} ist leer. Rezept ist angefragt – Packung abholen!"
            else:
                message = (
                    f"{label} reicht nur noch {_plural_days(snap.days_left or 0)}. "
                    "Rezept ist angefragt – Packung abholen."
                )
            actions = [snooze]
        elif snap.status in (calc.STATUS_DUE, calc.STATUS_EMPTY):
            title = "Rezept holen"
            if snap.status == calc.STATUS_EMPTY:
                message = f"{label} ist leer – Rezept dringend besorgen."
            else:
                assert snap.empty_at is not None and snap.prescription_due is not None
                if snap.prescription_due > dt_util.now().date():
                    when = f"Rezept bis {snap.prescription_due:%d.%m.} besorgen."
                else:
                    when = "Rezept jetzt besorgen."
                message = (
                    f"{label} reicht noch {_plural_days(snap.days_left or 0)} "
                    f"(leer am {snap.empty_at:%d.%m.}). {when}"
                )
            actions = [
                {"action": f"{ACTION_REQUESTED}{self.entry.entry_id}", "title": "Rezept angefragt"},
                snooze,
            ]
        elif force:
            title = "Vorrat ok"
            if snap.days_left is None:
                message = f"{label}: kein Einnahmeplan hinterlegt."
            else:
                message = f"{label} reicht noch {_plural_days(snap.days_left)}."
            actions = []
        else:
            return False

        await self.hass.services.async_call(
            "notify",
            self.notify_service,
            {"title": title, "message": message, "data": {"tag": tag, "actions": actions}},
            blocking=True,
        )
        return True

    async def _async_clear_notification(self) -> None:
        if not self.notify_service:
            return
        try:
            await self.hass.services.async_call(
                "notify",
                self.notify_service,
                {
                    "message": "clear_notification",
                    "data": {"tag": f"{DOMAIN}_{self.entry.entry_id}"},
                },
                blocking=True,
            )
        except Exception:
            _LOGGER.debug("Could not clear notification", exc_info=True)

    @callback
    def async_snooze(self) -> None:
        self._cancel_snooze()

        async def _fire(_now: datetime) -> None:
            self._snooze_unsub = None
            await self.async_send_reminder()

        self._snooze_unsub = async_call_later(
            self.hass, timedelta(hours=SNOOZE_HOURS), _fire
        )

    @callback
    def _cancel_snooze(self) -> None:
        if self._snooze_unsub:
            self._snooze_unsub()
            self._snooze_unsub = None
