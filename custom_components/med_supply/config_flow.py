"""Config and options flow: one entry per medication."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)

from . import calc
from ._schema import vol
from .const import (
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
    SLOT_DEFAULT_TIMES,
    SLOT_KEYS,
    SLOT_LABELS_DE,
    slot_dose_key,
    slot_time_key,
)

MG = NumberSelector(
    NumberSelectorConfig(min=0, max=10000, step="any", mode=NumberSelectorMode.BOX, unit_of_measurement="mg")
)
TABLETS = NumberSelector(
    NumberSelectorConfig(min=0, max=10000, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="Tbl.")
)
DAYS = NumberSelector(
    NumberSelectorConfig(min=1, max=90, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="d")
)


def _notify_selector(hass: HomeAssistant) -> Any:
    services = sorted(
        name
        for name in hass.services.async_services_for_domain("notify")
        if name.startswith("mobile_app_")
    )
    if not services:
        return TextSelector()
    return SelectSelector(
        SelectSelectorConfig(options=services, mode=SelectSelectorMode.DROPDOWN, custom_value=True)
    )


def _settings_schema(hass: HomeAssistant) -> dict[Any, Any]:
    """Fields shared by setup and options (everything except name/initial supply)."""
    plan: dict[Any, Any] = {}
    for key in SLOT_KEYS:
        plan[vol.Required(slot_time_key(key), default=SLOT_DEFAULT_TIMES[key])] = TimeSelector()
        plan[vol.Required(slot_dose_key(key), default=0)] = MG
    return {
        vol.Required(CONF_STRENGTH_MG): MG,
        vol.Optional(CONF_PACKAGE_SIZE): TABLETS,
        vol.Required(CONF_PLAN): section(vol.Schema(plan)),
        vol.Required(CONF_REMINDER): section(
            vol.Schema(
                {
                    vol.Required(CONF_LEAD_DAYS, default=DEFAULT_LEAD_DAYS): DAYS,
                    vol.Required(CONF_REMINDER_TIME, default=DEFAULT_REMINDER_TIME): TimeSelector(),
                    vol.Optional(CONF_NOTIFY_SERVICE): _notify_selector(hass),
                    vol.Required(CONF_SHOW_NAME, default=False): BooleanSelector(),
                }
            )
        ),
    }


def _validate(user_input: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (errors, description placeholders)."""
    strength = float(user_input.get(CONF_STRENGTH_MG) or 0)
    if strength <= 0:
        return {CONF_STRENGTH_MG: "strength_invalid"}, {}
    plan = user_input.get(CONF_PLAN, {})
    for key in SLOT_KEYS:
        dose = float(plan.get(slot_dose_key(key)) or 0)
        if dose > 0 and not calc.is_divisible(dose, strength):
            return {"base": "dose_not_divisible"}, {
                "slot": SLOT_LABELS_DE[key],
                "dose": calc.format_mg(dose),
                "strength": calc.format_mg(strength),
            }
    return {}, {}


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    """Drop the optional notify target when cleared."""
    data = dict(user_input)
    reminder = dict(data.get(CONF_REMINDER, {}))
    if not reminder.get(CONF_NOTIFY_SERVICE):
        reminder.pop(CONF_NOTIFY_SERVICE, None)
    data[CONF_REMINDER] = reminder
    return data


class MedSupplyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a medication."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"slot": "", "dose": "", "strength": ""}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            await self.async_set_unique_id(name.casefold())
            self._abort_if_unique_id_configured()
            errors, found = _validate(user_input)
            placeholders.update(found)
            if not errors:
                options = _normalize(
                    {k: v for k, v in user_input.items() if k not in (CONF_NAME, CONF_INITIAL_TABLETS)}
                )
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_NAME: name,
                        CONF_INITIAL_TABLETS: float(user_input.get(CONF_INITIAL_TABLETS) or 0),
                    },
                    options=options,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_INITIAL_TABLETS, default=0): TABLETS,
                **_settings_schema(self.hass),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors, description_placeholders=placeholders
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MedSupplyOptionsFlow()


class MedSupplyOptionsFlow(OptionsFlow):
    """Change plan, strength and reminder settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"slot": "", "dose": "", "strength": ""}
        if user_input is not None:
            errors, found = _validate(user_input)
            placeholders.update(found)
            if not errors:
                # Freeze the supply consumed under the old plan before it changes.
                if self.config_entry.state is ConfigEntryState.LOADED:
                    await self.config_entry.runtime_data.async_rebase()
                return self.async_create_entry(data=_normalize(user_input))

        schema = self.add_suggested_values_to_schema(
            vol.Schema(_settings_schema(self.hass)),
            user_input if user_input is not None else self.config_entry.options,
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors, description_placeholders=placeholders
        )
