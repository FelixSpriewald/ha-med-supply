"""Sensors: supply, days left, empty date, prescription due date, status, plan."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MedSupplyConfigEntry, calc
from .entity import MedSupplyEntity
from .supply import MedSupply


@dataclass(frozen=True, kw_only=True)
class MedSupplySensorDescription(SensorEntityDescription):
    value_fn: Callable[[MedSupply], Any]
    attrs_fn: Callable[[MedSupply], dict[str, Any]] | None = None


def _snap(supply: MedSupply):
    assert supply.snapshot is not None
    return supply.snapshot


SENSORS: tuple[MedSupplySensorDescription, ...] = (
    MedSupplySensorDescription(
        key="stock",
        translation_key="stock",
        native_unit_of_measurement="Tbl.",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: round(_snap(s).stock_tablets, 2),
        attrs_fn=lambda s: {
            "stock_mg": round(_snap(s).stock_mg, 3),
            "strength_mg": s.strength_mg,
            "package_size": s.package_size or None,
        },
    ),
    MedSupplySensorDescription(
        key="days_left",
        translation_key="days_left",
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda s: _snap(s).days_left,
        attrs_fn=lambda s: {"lead_days": s.lead_days},
    ),
    MedSupplySensorDescription(
        key="empty_on",
        translation_key="empty_on",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda s: _snap(s).empty_at.date() if _snap(s).empty_at else None,
    ),
    MedSupplySensorDescription(
        key="prescription_due",
        translation_key="prescription_due",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda s: _snap(s).prescription_due,
    ),
    MedSupplySensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=calc.STATUSES,
        value_fn=lambda s: _snap(s).status,
    ),
    MedSupplySensorDescription(
        key="daily_dose",
        translation_key="daily_dose",
        native_unit_of_measurement="mg",
        value_fn=lambda s: _snap(s).daily_dose_mg,
        attrs_fn=lambda s: {
            "plan": s.plan_text(),
            "tablets_per_day": round(calc.tablets(_snap(s).daily_dose_mg, s.strength_mg), 2),
            **{
                slot.key: {
                    "time": slot.at.strftime("%H:%M"),
                    "dose_mg": slot.dose_mg,
                    "tablets": round(calc.tablets(slot.dose_mg, s.strength_mg), 2),
                }
                for slot in calc.active_slots(s.slots)
            },
        },
    ),
    MedSupplySensorDescription(
        key="next_intake",
        translation_key="next_intake",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: _snap(s).next_intake,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MedSupplyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    supply = entry.runtime_data
    async_add_entities(MedSupplySensor(supply, d) for d in SENSORS)


class MedSupplySensor(MedSupplyEntity, SensorEntity):
    entity_description: MedSupplySensorDescription

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.supply)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.supply)
