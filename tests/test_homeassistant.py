"""Exercise the real Home Assistant flow and entity platforms with camera I/O mocked."""
import asyncio
from pathlib import Path
import shutil
import sys
import threading
from unittest.mock import patch

import pytest
import pytest_asyncio

from homeassistant import loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import frame
from homeassistant.helpers import entity_registry as er, device_registry as dr
from homeassistant.helpers import area_registry as ar, floor_registry as fr, label_registry as lr

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.watchai.api import InvalidAuth


@pytest_asyncio.fixture
async def hass(tmp_path):
    shutil.copytree(ROOT / "custom_components", tmp_path / "custom_components")
    instance = HomeAssistant(str(tmp_path))
    frame.async_setup(instance)
    loader.async_setup(instance)
    instance.config_entries = ConfigEntries(instance, {})
    await instance.config_entries.async_initialize()
    dr.async_setup(instance)
    for registry in (dr, er, ar, fr, lr):
        await registry.async_load(instance)
    yield instance
    await instance.async_stop(force=True)


DATA = {"name": "Test camera", "host": "camera.test", "username": "admin", "password": "test-only"}


async def add_camera(hass):
    with patch("custom_components.watchai.config_flow.Camera") as camera:
        result = await hass.config_entries.flow.async_init(
            "watchai", context={"source": "user"}, data=DATA.copy()
        )
        await hass.async_block_till_done()
        camera.return_value.execute.assert_called_once_with()
    assert result["type"] == "create_entry", result
    return result["result"]


@pytest.mark.asyncio
async def test_setup_buttons_duration_reload_and_unload(hass):
    entry = await add_camera(hass)
    states = hass.states.async_all()
    assert sorted(s.entity_id for s in states) == [
        "button.test_camera_flash_lights", "button.test_camera_stop_flashing",
        "number.test_camera_flash_duration",
    ]
    assert hass.states.get("number.test_camera_flash_duration").state == "5"
    await hass.services.async_call("number", "set_value", {
        "entity_id": "number.test_camera_flash_duration", "value": 12,
    }, blocking=True)
    assert entry.options["duration"] == 12
    with patch("custom_components.watchai.Camera") as camera:
        await hass.services.async_call("button", "press", {
            "entity_id": "button.test_camera_flash_lights",
        }, blocking=True)
        camera.return_value.execute.assert_called_once_with(True, 12)
        camera.reset_mock()
        await hass.services.async_call("button", "press", {
            "entity_id": "button.test_camera_stop_flashing",
        }, blocking=True)
        camera.return_value.execute.assert_called_once_with(False, 12)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("number.test_camera_flash_duration").state == "12"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.entry_id not in hass.data["watchai"]


@pytest.mark.asyncio
async def test_config_errors_and_duplicate(hass):
    with patch("custom_components.watchai.config_flow.Camera") as camera:
        camera.return_value.execute.side_effect = InvalidAuth("rejected")
        result = await hass.config_entries.flow.async_init(
            "watchai", context={"source": "user"}, data=DATA.copy()
        )
        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_auth"}
        assert camera.return_value.execute.call_count == 1
        hass.config_entries.flow.async_abort(result["flow_id"])
    await add_camera(hass)
    with patch("custom_components.watchai.config_flow.Camera") as camera:
        result = await hass.config_entries.flow.async_init(
            "watchai", context={"source": "user"}, data=DATA.copy()
        )
        assert result["type"] == "abort"
        assert result["reason"] == "already_configured"
        camera.assert_not_called()


@pytest.mark.asyncio
async def test_options_update_credentials_and_preserve_duration(hass):
    entry = await add_camera(hass)
    await hass.services.async_call("number", "set_value", {
        "entity_id": "number.test_camera_flash_duration", "value": 20,
    }, blocking=True)
    with patch("custom_components.watchai.config_flow.Camera") as camera:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == "form"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={**DATA, "password": "new-test-password"}
        )
        assert result["type"] == "create_entry", result
        camera.return_value.execute.assert_called_once_with()
    assert entry.data["password"] == "new-test-password"
    assert entry.options["duration"] == 20


@pytest.mark.asyncio
async def test_camera_actions_are_serialized(hass):
    entry = await add_camera(hass)
    runtime = hass.data["watchai"][entry.entry_id]
    first_started = threading.Event()
    release = threading.Event()
    calls = []
    def execute(enabled, duration):
        calls.append(enabled)
        if enabled:
            first_started.set()
            assert release.wait(5)
    with patch("custom_components.watchai.Camera") as camera:
        camera.return_value.execute.side_effect = execute
        first = asyncio.create_task(runtime.async_control(True))
        assert await asyncio.to_thread(first_started.wait, 5)
        second = asyncio.create_task(runtime.async_control(False))
        await asyncio.sleep(0)
        assert calls == [True]
        release.set()
        await asyncio.gather(first, second)
    assert calls == [True, False]


@pytest.mark.asyncio
async def test_action_rejection_reaches_home_assistant(hass):
    await add_camera(hass)
    with patch("custom_components.watchai.Camera") as camera:
        camera.return_value.execute.side_effect = InvalidAuth("Camera rejected authentication")
        with pytest.raises(HomeAssistantError, match="rejected authentication"):
            await hass.services.async_call("button", "press", {
                "entity_id": "button.test_camera_flash_lights",
            }, blocking=True)
        assert camera.return_value.execute.call_count == 1


@pytest.mark.asyncio
async def test_cancellation_does_not_allow_overlapping_camera_requests(hass):
    entry = await add_camera(hass)
    runtime = hass.data["watchai"][entry.entry_id]
    started = threading.Event()
    release = threading.Event()
    calls = []
    def execute(enabled, duration):
        calls.append(enabled)
        if enabled:
            started.set()
            assert release.wait(5)
    with patch("custom_components.watchai.Camera") as camera:
        camera.return_value.execute.side_effect = execute
        first = asyncio.create_task(runtime.async_control(True))
        assert await asyncio.to_thread(started.wait, 5)
        first.cancel()
        await asyncio.sleep(0)
        second = asyncio.create_task(runtime.async_control(False))
        await asyncio.sleep(0)
        assert calls == [True]
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second
    assert calls == [True, False]
