"""Buttons: book addition, book counted supply, +1 package."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MedSupplyConfigEntry
from .const import DOMAIN
from .entity import MedSupplyEntity
from .supply import MedSupply


def _draft_value(supply: MedSupply, key: str) -> float:
    draft = supply.drafts.get(key)
    value = draft.native_value if draft is not None else None
    if value is None or (key == "addition" and value <= 0):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key=f"{key}_missing"
        )
    return float(value)


async def _book_addition(supply: MedSupply) -> None:
    await supply.async_add_tablets(_draft_value(supply, "addition"))
    supply.drafts["addition"].reset()


async def _book_count(supply: MedSupply) -> None:
    await supply.async_set_tablets(_draft_value(supply, "counted"))
    supply.drafts["counted"].reset()


async def _add_package(supply: MedSupply) -> None:
    await supply.async_add_tablets(supply.package_size)


@dataclass(frozen=True, kw_only=True)
class MedSupplyButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[MedSupply], Awaitable[None]]


BOOK_ADDITION = MedSupplyButtonDescription(
    key="book_addition", translation_key="book_addition", press_fn=_book_addition
)
BOOK_COUNT = MedSupplyButtonDescription(
    key="book_count", translation_key="book_count", press_fn=_book_count
)
ADD_PACKAGE = MedSupplyButtonDescription(
    key="add_package", translation_key="add_package", press_fn=_add_package
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MedSupplyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    supply = entry.runtime_data
    descriptions = [BOOK_ADDITION, BOOK_COUNT]
    if supply.package_size > 0:
        descriptions.append(ADD_PACKAGE)
    async_add_entities(MedSupplyButton(supply, d) for d in descriptions)


class MedSupplyButton(MedSupplyEntity, ButtonEntity):
    entity_description: MedSupplyButtonDescription

    async def async_added_to_hass(self) -> None:
        # Buttons have no state that depends on the supply.
        pass

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.supply)
