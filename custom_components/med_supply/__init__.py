"""Medication Supply — track tablet supply and get reminded to renew prescriptions."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from ._schema import vol
from .const import (
    ACTION_REQUESTED,
    ACTION_SNOOZE,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_REQUESTED,
    ATTR_STRENGTH_MG,
    ATTR_TABLETS,
    DOMAIN,
    EVENT_NOTIFICATION_ACTION,
    SERVICE_ADD_STOCK,
    SERVICE_SEND_REMINDER,
    SERVICE_SET_REQUESTED,
    SERVICE_SET_STOCK,
)
from .supply import MedSupply

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type MedSupplyConfigEntry = ConfigEntry[MedSupply]

_ENTRY = {vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}
_POSITIVE = vol.All(vol.Coerce(float), vol.Range(min=0))


CARD_URL = f"/{DOMAIN}/med-supply-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "med-supply-card.js"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the dashboard card and load it in every frontend session."""
    if hass.http is None:  # e.g. in tests without http
        return
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
    )
    integration = await async_get_integration(hass, DOMAIN)
    try:
        add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    except KeyError:  # frontend not loaded
        _LOGGER.warning("Frontend not loaded, med-supply-card not registered")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services, the dashboard card and the notification action listener (once)."""
    await _async_register_card(hass)

    def _supply(call: ServiceCall) -> MedSupply:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        return entry.runtime_data

    async def add_stock(call: ServiceCall) -> None:
        await _supply(call).async_add_tablets(
            call.data[ATTR_TABLETS], call.data.get(ATTR_STRENGTH_MG)
        )

    async def set_stock(call: ServiceCall) -> None:
        await _supply(call).async_set_tablets(call.data[ATTR_TABLETS])

    async def set_requested(call: ServiceCall) -> None:
        await _supply(call).async_set_requested(call.data[ATTR_REQUESTED])

    async def send_reminder(call: ServiceCall) -> None:
        supply = _supply(call)
        if not supply.notify_service:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_notify_service"
            )
        await supply.async_send_reminder(force=True)

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_STOCK,
        add_stock,
        vol.Schema(
            {
                **_ENTRY,
                vol.Required(ATTR_TABLETS): _POSITIVE,
                vol.Optional(ATTR_STRENGTH_MG): vol.All(vol.Coerce(float), vol.Range(min=0.001)),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_STOCK,
        set_stock,
        vol.Schema({**_ENTRY, vol.Required(ATTR_TABLETS): _POSITIVE}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_REQUESTED,
        set_requested,
        vol.Schema({**_ENTRY, vol.Optional(ATTR_REQUESTED, default=True): cv.boolean}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_REMINDER, send_reminder, vol.Schema(_ENTRY)
    )

    @callback
    def _handle_action(event: Event) -> None:
        action = str(event.data.get("action", ""))
        for prefix in (ACTION_REQUESTED, ACTION_SNOOZE):
            if not action.startswith(prefix):
                continue
            entry = hass.config_entries.async_get_entry(action.removeprefix(prefix))
            if entry is None or entry.state is not ConfigEntryState.LOADED:
                return
            supply: MedSupply = entry.runtime_data
            if prefix == ACTION_REQUESTED:
                hass.async_create_task(supply.async_set_requested(True))
            else:
                supply.async_snooze()
            return

    hass.bus.async_listen(EVENT_NOTIFICATION_ACTION, _handle_action)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MedSupplyConfigEntry) -> bool:
    supply = MedSupply(hass, entry)
    await supply.async_load()
    entry.runtime_data = supply
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    supply.async_start()
    entry.async_on_unload(supply.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: MedSupplyConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MedSupplyConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: MedSupplyConfigEntry) -> None:
    """Delete stored supply when the medication is removed."""
    await MedSupply(hass, entry).async_remove_store()
