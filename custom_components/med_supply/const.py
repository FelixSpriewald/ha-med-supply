"""Constants for Medication Supply."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "med_supply"

STORAGE_VERSION: Final = 1

# Config entry data (fixed at creation)
CONF_NAME: Final = "name"
CONF_INITIAL_TABLETS: Final = "initial_tablets"

# Config entry options (editable)
CONF_STRENGTH_MG: Final = "strength_mg"
CONF_PACKAGE_SIZE: Final = "package_size"
CONF_PLAN: Final = "plan"
CONF_REMINDER: Final = "reminder"
CONF_LEAD_DAYS: Final = "lead_days"
CONF_REMINDER_TIME: Final = "reminder_time"
CONF_NOTIFY_SERVICE: Final = "notify_service"
CONF_SHOW_NAME: Final = "show_name"

SLOT_KEYS: Final = ("morning", "noon", "evening", "night")
SLOT_DEFAULT_TIMES: Final = {
    "morning": "08:00:00",
    "noon": "12:00:00",
    "evening": "20:00:00",
    "night": "22:00:00",
}
SLOT_LABELS_DE: Final = {
    "morning": "morgens",
    "noon": "mittags",
    "evening": "abends",
    "night": "nachts",
}


def slot_time_key(slot: str) -> str:
    """Option key for a slot's time."""
    return f"{slot}_time"


def slot_dose_key(slot: str) -> str:
    """Option key for a slot's dose in mg."""
    return f"{slot}_dose_mg"


DEFAULT_LEAD_DAYS: Final = 14
DEFAULT_REMINDER_TIME: Final = "09:00:00"
PICKUP_WARNING_DAYS: Final = 3
SNOOZE_HOURS: Final = 3

# Mobile app actionable notifications
ACTION_REQUESTED: Final = "MED_SUPPLY_REQUESTED_"
ACTION_SNOOZE: Final = "MED_SUPPLY_SNOOZE_"
EVENT_NOTIFICATION_ACTION: Final = "mobile_app_notification_action"

# Services
SERVICE_ADD_STOCK: Final = "add_stock"
SERVICE_SET_STOCK: Final = "set_stock"
SERVICE_SET_REQUESTED: Final = "set_requested"
SERVICE_SEND_REMINDER: Final = "send_reminder"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_TABLETS: Final = "tablets"
ATTR_STRENGTH_MG: Final = "strength_mg"
ATTR_REQUESTED: Final = "requested"
