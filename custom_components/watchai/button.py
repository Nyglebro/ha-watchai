"""Flash and stop controls; neither pretends to report live LED state."""
from homeassistant.components.button import ButtonEntity

from .const import DOMAIN
from .entity import WatchAIEntity


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WatchAIButton(runtime, True), WatchAIButton(runtime, False)])


class WatchAIButton(WatchAIEntity, ButtonEntity):
    def __init__(self, runtime, enabled):
        key = "flash" if enabled else "stop"
        super().__init__(runtime, key)
        self._enable_lights = enabled
        self._attr_name = "Flash lights" if enabled else "Stop flashing"
        self._attr_icon = "mdi:alarm-light" if enabled else "mdi:stop-circle-outline"

    async def async_press(self):
        await self.runtime.async_control(self._enable_lights)
