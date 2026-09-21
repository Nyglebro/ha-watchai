"""WatchAI Deterrence integration."""
from __future__ import annotations

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import Camera, CameraError
from .const import CONF_DURATION, DEFAULT_DURATION, DOMAIN, PLATFORMS


class WatchAIRuntime:
    """Serialize requests and move all blocking work off Home Assistant's event loop."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.lock = asyncio.Lock()
        self.duration = entry.options.get(CONF_DURATION, DEFAULT_DURATION)

    async def async_control(self, enabled: bool) -> None:
        async with self.lock:
            # Construction also creates the TLS context, so it belongs in the executor.
            def run():
                Camera(
                    self.entry.data[CONF_HOST], self.entry.data[CONF_USERNAME],
                    self.entry.data[CONF_PASSWORD],
                ).execute(enabled, self.duration)

            # Keep serialization even if a caller cancels its action during I/O.
            task = self.hass.async_add_executor_job(run)
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                try:
                    await task
                except CameraError:
                    pass
                raise
            except CameraError as exc:
                raise HomeAssistantError(str(exc)) from None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register controls without activating lights or polling the camera."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = WatchAIRuntime(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        runtime = hass.data[DOMAIN][entry.entry_id]
        async with runtime.lock:
            hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
