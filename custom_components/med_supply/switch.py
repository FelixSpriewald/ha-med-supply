"""Switch: prescription requested."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MedSupplyConfigEntry
from .entity import MedSupplyEntity

REQUESTED = SwitchEntityDescription(key="requested", translation_key="requested")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MedSupplyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([RequestedSwitch(entry.runtime_data, REQUESTED)])


class RequestedSwitch(MedSupplyEntity, SwitchEntity):
    """On while a prescription is requested but the new package is not booked yet."""

    @property
    def is_on(self) -> bool:
        return self.supply.requested

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.supply.async_set_requested(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.supply.async_set_requested(False)
