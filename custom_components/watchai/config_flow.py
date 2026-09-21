"""UI setup and credential editing; validation only logs in, never flashes."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import Camera, CameraError, CannotConnect, InvalidAuth, UnsupportedProtocol, normalize_host
from .const import DEFAULT_NAME, DOMAIN


def schema(defaults=None):
    defaults = defaults or {}
    return vol.Schema({
        vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
        vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "admin")): str,
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    })


async def validate(hass, user_input):
    data = dict(user_input)
    try:
        data[CONF_HOST] = normalize_host(data[CONF_HOST])
    except ValueError:
        return None, {CONF_HOST: "invalid_host"}
    if not data[CONF_USERNAME].strip() or not data[CONF_PASSWORD]:
        return None, {"base": "invalid_auth"}
    def run():
        Camera(data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD]).execute()
    try:
        await hass.async_add_executor_job(run)
    except InvalidAuth:
        return None, {"base": "invalid_auth"}
    except CannotConnect:
        return None, {"base": "cannot_connect"}
    except UnsupportedProtocol:
        return None, {"base": "unsupported_protocol"}
    except CameraError:
        return None, {"base": "camera_error"}
    return data, {}


class WatchAIConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                host = normalize_host(user_input[CONF_HOST])
            except ValueError:
                host = None
            if any(entry.data[CONF_HOST] == host for entry in self._async_current_entries()):
                return self.async_abort(reason="already_configured")
            data, errors = await validate(self.hass, user_input)
            if data is not None:
                return self.async_create_entry(title=data[CONF_NAME], data=data)
        return self.async_show_form(step_id="user", data_schema=schema(user_input), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return WatchAIOptionsFlow(config_entry)


class WatchAIOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry):
        self._entry = entry

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                host = normalize_host(user_input[CONF_HOST])
            except ValueError:
                host = None
            if any(entry.entry_id != self._entry.entry_id and entry.data[CONF_HOST] == host
                   for entry in self.hass.config_entries.async_entries(DOMAIN)):
                errors = {CONF_HOST: "already_configured"}
            else:
                data, errors = await validate(self.hass, user_input)
                if data is not None:
                    self.hass.config_entries.async_update_entry(
                        self._entry, title=data[CONF_NAME], data=data
                    )
                    await self.hass.config_entries.async_reload(self._entry.entry_id)
                    return self.async_create_entry(title="", data=dict(self._entry.options))
        return self.async_show_form(
            step_id="init", data_schema=schema(user_input or self._entry.data), errors=errors
        )
