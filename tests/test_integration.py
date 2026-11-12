"""End-to-end tests against a real Home Assistant test instance."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.med_supply.const import DOMAIN

TZ = ZoneInfo("Europe/Berlin")
START = datetime(2026, 11, 12, 10, 0, tzinfo=TZ)

USER_INPUT = {
    "name": "Pille A",
    "initial_tablets": 31,
    "strength_mg": 5,
    "package_size": 50,
    "plan": {
        "morning_time": "08:00:00",
        "morning_dose_mg": 10,
        "noon_time": "12:00:00",
        "noon_dose_mg": 0,
        "evening_time": "20:00:00",
        "evening_dose_mg": 10,
        "night_time": "22:00:00",
        "night_dose_mg": 0,
    },
    "reminder": {
        "lead_days": 14,
        "reminder_time": "09:00:00",
        "notify_service": "mobile_app_iphone",
        "show_name": False,
    },
}


@pytest.fixture
async def setup(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(START)
    notify_calls = async_mock_service(hass, "notify", "mobile_app_iphone")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    return entry, notify_calls


def eid(hass: HomeAssistant, entry, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"{platform}.{key} missing"
    return entity_id


def state(hass: HomeAssistant, entry, platform: str, key: str):
    return hass.states.get(eid(hass, entry, platform, key))


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, to: datetime) -> None:
    freezer.move_to(to)
    async_fire_time_changed(hass, to)
    await hass.async_block_till_done()


async def test_initial_state(hass: HomeAssistant, setup) -> None:
    entry, _ = setup
    assert float(state(hass, entry, "sensor", "stock").state) == 31
    assert state(hass, entry, "sensor", "stock").attributes["stock_mg"] == 155
    assert state(hass, entry, "sensor", "days_left").state == "8"
    assert state(hass, entry, "sensor", "empty_on").state == "2026-11-20"
    assert state(hass, entry, "sensor", "prescription_due").state == "2026-11-06"
    assert state(hass, entry, "sensor", "status").state == "due"
    dose = state(hass, entry, "sensor", "daily_dose")
    assert float(dose.state) == 20
    assert dose.attributes["plan"] == "morgens 10 mg (2× 5 mg), abends 10 mg (2× 5 mg)"
    assert dose.attributes["tablets_per_day"] == 4
    assert state(hass, entry, "switch", "requested").state == "off"
    assert float(state(hass, entry, "number", "addition").state) == 50
    assert state(hass, entry, "button", "add_package") is not None


async def test_supply_decreases_at_intake_times(
    hass: HomeAssistant, setup, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = setup
    await tick(hass, freezer, START.replace(hour=19, minute=59))
    assert float(state(hass, entry, "sensor", "stock").state) == 31
    await tick(hass, freezer, START.replace(hour=20, minute=0, second=1))
    assert float(state(hass, entry, "sensor", "stock").state) == 29
    await tick(hass, freezer, START + timedelta(days=1, hours=-1, seconds=1))  # 13.11. 09:00
    assert float(state(hass, entry, "sensor", "stock").state) == 27


async def test_survives_reload(hass: HomeAssistant, setup, freezer: FrozenDateTimeFactory) -> None:
    entry, _ = setup
    await hass.config_entries.async_unload(entry.entry_id)
    freezer.move_to(START + timedelta(days=2))  # downtime over 4 intakes
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert float(state(hass, entry, "sensor", "stock").state) == 23


async def test_book_addition_and_count(hass: HomeAssistant, setup) -> None:
    entry, _ = setup
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": eid(hass, entry, "switch", "requested")}, blocking=True
    )
    assert state(hass, entry, "sensor", "status").state == "requested"

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": eid(hass, entry, "number", "addition"), "value": 100},
        blocking=True,
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, entry, "button", "book_addition")}, blocking=True
    )
    assert float(state(hass, entry, "sensor", "stock").state) == 131
    assert state(hass, entry, "switch", "requested").state == "off"
    assert state(hass, entry, "sensor", "status").state == "ok"
    assert float(state(hass, entry, "number", "addition").state) == 50  # reset to package size

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "button", "press", {"entity_id": eid(hass, entry, "button", "book_count")}, blocking=True
        )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": eid(hass, entry, "number", "counted"), "value": 120},
        blocking=True,
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, entry, "button", "book_count")}, blocking=True
    )
    assert float(state(hass, entry, "sensor", "stock").state) == 120
    assert state(hass, entry, "number", "counted").state == "unknown"

    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, entry, "button", "add_package")}, blocking=True
    )
    assert float(state(hass, entry, "sensor", "stock").state) == 170


async def test_services(hass: HomeAssistant, setup) -> None:
    entry, _ = setup
    await hass.services.async_call(
        DOMAIN,
        "add_stock",
        {"config_entry_id": entry.entry_id, "tablets": 10, "strength_mg": 10},
        blocking=True,
    )
    # 155 mg + 100 mg = 255 mg = 51 tablets à 5 mg
    assert float(state(hass, entry, "sensor", "stock").state) == 51
    await hass.services.async_call(
        DOMAIN, "set_stock", {"config_entry_id": entry.entry_id, "tablets": 4}, blocking=True
    )
    assert float(state(hass, entry, "sensor", "stock").state) == 4
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_stock", {"config_entry_id": "nope", "tablets": 4}, blocking=True
        )


async def test_options_change_rebases(
    hass: HomeAssistant, setup, freezer: FrozenDateTimeFactory
) -> None:
    entry, _ = setup
    await tick(hass, freezer, START.replace(hour=20, minute=0, second=1))
    assert float(state(hass, entry, "sensor", "stock").state) == 29

    # New plan: only 5 mg in the morning, and 10 mg tablets now.
    options = {k: v for k, v in USER_INPUT.items() if k not in ("name", "initial_tablets")}
    options = {
        **options,
        "strength_mg": 10,
        "plan": {**USER_INPUT["plan"], "morning_dose_mg": 5, "evening_dose_mg": 0},
    }
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], options)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # 145 mg left, now shown as 14.5 tablets à 10 mg; 5 mg/day → 29 intakes
    # (13.11. … 11.12.), empty on 12.12. = 30 days from 12.11.
    assert float(state(hass, entry, "sensor", "stock").state) == 14.5
    assert state(hass, entry, "sensor", "daily_dose").attributes["plan"] == (
        "morgens 5 mg (0,5× 10 mg)"
    )
    assert state(hass, entry, "sensor", "empty_on").state == "2026-12-12"
    assert state(hass, entry, "sensor", "days_left").state == "30"


async def test_flow_rejects_indivisible_dose(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    bad = {**USER_INPUT, "plan": {**USER_INPUT["plan"], "morning_dose_mg": 7.5}, "strength_mg": 10}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], bad)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "dose_not_divisible"}
    assert result["description_placeholders"]["slot"] == "morgens"


async def test_reminder_push_and_action(
    hass: HomeAssistant, setup, freezer: FrozenDateTimeFactory
) -> None:
    entry, notify_calls = setup
    await tick(hass, freezer, START + timedelta(days=1, hours=-1))  # 13.11. 09:00
    assert len(notify_calls) == 1
    call = notify_calls[0]
    assert call.data["title"] == "Rezept holen"
    assert "Pille A" not in call.data["message"]
    assert "Ein Medikament reicht noch 7 Tage" in call.data["message"]
    actions = [a["action"] for a in call.data["data"]["actions"]]
    assert actions[0] == f"MED_SUPPLY_REQUESTED_{entry.entry_id}"

    hass.bus.async_fire("mobile_app_notification_action", {"action": actions[0]})
    await hass.async_block_till_done()
    assert state(hass, entry, "switch", "requested").state == "on"
    assert notify_calls[-1].data["message"] == "clear_notification"

    # Requested: no further reminder until only 3 days are left …
    count = len(notify_calls)
    await tick(hass, freezer, START + timedelta(days=2, hours=-1))  # 14.11., 6 days left
    assert len(notify_calls) == count
    await tick(hass, freezer, START + timedelta(days=5, hours=-1))  # 17.11., 3 days left
    assert notify_calls[-1].data["title"] == "Packung abholen"


async def test_snooze_resends(hass: HomeAssistant, setup, freezer: FrozenDateTimeFactory) -> None:
    entry, notify_calls = setup
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": f"MED_SUPPLY_SNOOZE_{entry.entry_id}"}
    )
    await hass.async_block_till_done()
    assert len(notify_calls) == 0
    await tick(hass, freezer, START + timedelta(hours=3, seconds=1))
    assert len(notify_calls) == 1
    assert notify_calls[0].data["title"] == "Rezept holen"


async def test_send_reminder_service_when_ok(hass: HomeAssistant, setup) -> None:
    entry, notify_calls = setup
    await hass.services.async_call(
        DOMAIN, "add_stock", {"config_entry_id": entry.entry_id, "tablets": 100}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "send_reminder", {"config_entry_id": entry.entry_id}, blocking=True
    )
    assert notify_calls[-1].data["title"] == "Vorrat ok"


async def test_remove_entry(hass: HomeAssistant, setup) -> None:
    entry, _ = setup
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.config_entries.async_entries(DOMAIN)
