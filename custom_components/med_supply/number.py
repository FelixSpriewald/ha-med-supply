"""Input fields for booking: addition (Zugang) and counted supply (Korrektur).

The value is only a draft; the matching button books it. That avoids a typo
in a number field silently changing the supply.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MedSupplyConfigEntry
from .entity import MedSupplyEntity
from .supply import MedSupply

ADDITION = NumberEntityDescription(
    key="addition",
    translation_key="addition",
    native_min_value=0,
    native_max_value=10000,
    native_step=0.5,
    native_unit_of_measurement="Tbl.",
    mode=NumberMode.BOX,
)
COUNTED = NumberEntityDescription(
    key="counted",
    translation_key="counted",
    native_min_value=0,
    native_max_value=10000,
    native_step=0.5,
    native_unit_of_measurement="Tbl.",
    mode=NumberMode.BOX,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MedSupplyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    supply = entry.runtime_data
    async_add_entities(
        [
            DraftNumber(supply, ADDITION, default=supply.package_size or None),
            DraftNumber(supply, COUNTED, default=None),
        ]
    )


class DraftNumber(MedSupplyEntity, NumberEntity):
    """Holds a value until the corresponding button books it."""

    def __init__(
        self, supply: MedSupply, description: NumberEntityDescription, default: float | None
    ) -> None:
        super().__init__(supply, description)
        self._default = default
        self._attr_native_value = default

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.supply.drafts[self.entity_description.key] = self

    async def async_will_remove_from_hass(self) -> None:
        self.supply.drafts.pop(self.entity_description.key, None)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

    def reset(self) -> None:
        self._attr_native_value = self._default
        self.async_write_ha_state()
