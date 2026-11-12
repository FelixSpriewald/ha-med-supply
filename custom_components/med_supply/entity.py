"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN
from .supply import MedSupply


class MedSupplyEntity(Entity):
    """Entity bound to one medication; refreshed by the MedSupply runtime."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, supply: MedSupply, description: EntityDescription) -> None:
        self.supply = supply
        self.entity_description = description
        entry_id = supply.entry.entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=supply.name,
            manufacturer="Medication Supply",
            model=supply.plan_text(),
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.supply.async_add_listener(self.async_write_ha_state))
