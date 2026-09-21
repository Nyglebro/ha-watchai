"""Persistent duration used on the next flash command."""
import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_DURATION, DOMAIN
from .entity import WatchAIEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([WatchAIDuration(hass.data[DOMAIN][entry.entry_id])])


class WatchAIDuration(WatchAIEntity, NumberEntity):
    _attr_name = "Flash duration"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 1800
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX

    def __init__(self, runtime):
        super().__init__(runtime, "duration")

    @property
    def native_value(self):
        return self.runtime.duration

    async def async_set_native_value(self, value):
        if not math.isfinite(value) or value != int(value) or not 1 <= value <= 1800:
            raise HomeAssistantError("Enter a whole number from 1 to 1800 seconds.")
        self.runtime.duration = int(value)
        entry = self.runtime.entry
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_DURATION: int(value)}
        )
        self.async_write_ha_state()
