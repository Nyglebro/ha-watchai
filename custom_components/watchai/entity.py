"""Shared entity metadata."""
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN


class WatchAIEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime, key):
        self.runtime = runtime
        entry = runtime.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="WatchAI / Sunell",
            configuration_url=entry.data["host"],
        )
