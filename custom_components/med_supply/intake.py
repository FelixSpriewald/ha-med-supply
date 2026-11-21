"""Intake reminders: one push per intake time, bundling all medications due then."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from . import calc
from .const import DOMAIN, SLOT_LABELS_DE
from .supply import MedSupply

INTAKE_TAG = f"{DOMAIN}_intake"


class IntakeReminders:
    """Shared across all config entries, so meds due at the same time share one push."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._supplies: dict[str, MedSupply] = {}
        self._unsubs: list[CALLBACK_TYPE] = []

    @callback
    def async_register(self, supply: MedSupply) -> CALLBACK_TYPE:
        self._supplies[supply.entry.entry_id] = supply
        self._reschedule()

        @callback
        def unregister() -> None:
            self._supplies.pop(supply.entry.entry_id, None)
            self._reschedule()

        return unregister

    def _due(self, at: time) -> list[tuple[MedSupply, calc.Slot]]:
        """Medications with an intake at `at` that want a reminder."""
        due = []
        for supply in self._supplies.values():
            if not (supply.intake_reminder and supply.notify_service):
                continue
            for slot in calc.active_slots(supply.slots):
                if slot.at == at:
                    due.append((supply, slot))
        return due

    @callback
    def _reschedule(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        times = {
            slot.at
            for supply in self._supplies.values()
            if supply.intake_reminder and supply.notify_service
            for slot in calc.active_slots(supply.slots)
        }
        for at in times:
            self._unsubs.append(
                async_track_time_change(
                    self.hass, self._fire, hour=at.hour, minute=at.minute, second=at.second
                )
            )

    async def _fire(self, now: datetime) -> None:
        at = now.time().replace(microsecond=0)
        by_service: dict[str, list[tuple[MedSupply, calc.Slot]]] = defaultdict(list)
        for supply, slot in self._due(at):
            by_service[supply.notify_service].append((supply, slot))  # type: ignore[index]
        for service, due in by_service.items():
            title, message = _compose(due)
            await self.hass.services.async_call(
                "notify",
                service,
                {"title": title, "message": message, "data": {"tag": INTAKE_TAG}},
                blocking=True,
            )

    @callback
    def async_stop(self) -> None:
        self._supplies.clear()
        self._reschedule()


def _compose(due: list[tuple[MedSupply, calc.Slot]]) -> tuple[str, str]:
    """E.g. ('Tabletten nehmen (morgens)', 'Pille A: 2× 5 mg\\nPille B: 1× 10 mg')."""
    title = f"Tabletten nehmen ({SLOT_LABELS_DE[due[0][1].key]})"
    lines = []
    hidden = 0
    for supply, slot in due:
        if not supply.show_name:
            hidden += 1
            continue
        count = calc.format_count(calc.tablets(slot.dose_mg, supply.strength_mg))
        lines.append(f"{supply.name}: {count}× {calc.format_mg(supply.strength_mg)}")
    if hidden and not lines:
        lines.append("Zeit für deine Tabletten.")
    elif hidden:
        lines.append("+ 1 weiteres Medikament" if hidden == 1 else f"+ {hidden} weitere Medikamente")
    return title, "\n".join(lines)
