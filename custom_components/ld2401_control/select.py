"""OUT mode selection with immediate feedback and broadcast synchronization."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import OUT_MODE_AUTO, OUT_MODE_HIGH, OUT_MODE_LOW
from .coordinator import LD2401ControlManager

PARALLEL_UPDATES = 1
OPTIONS = {"auto": OUT_MODE_AUTO, "hold_low": OUT_MODE_LOW, "hold_high": OUT_MODE_HIGH}
MODE_OPTIONS = {value: key for key, value in OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the mode selector to the existing radar device."""
    async_add_entities([LD2401OutModeSelect(entry.runtime_data)])


class LD2401OutModeSelect(SelectEntity):
    """An immediately selected mode reconciled with authenticated feedback."""

    _attr_has_entity_name = True
    _attr_translation_key = "out_mode"
    _attr_options = list(OPTIONS)

    def __init__(self, manager: LD2401ControlManager) -> None:
        self._manager = manager
        address = manager.address.replace(":", "").lower()
        self._attr_unique_id = f"{address}_out_mode"
        self.entity_id = f"select.ld2401_{address[-4:]}_out_mode"
        self._attr_device_info = DeviceInfo(
            connections={(dr.CONNECTION_BLUETOOTH, manager.address)},
            manufacturer="HLK", model="LD2401", name=manager.name,
        )

    @property
    def available(self) -> bool:
        return self._manager.available

    @property
    def current_option(self) -> str | None:
        return MODE_OPTIONS.get(self._manager.mode)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._manager.add_listener(self.async_write_ha_state))

    async def async_select_option(self, option: str) -> None:
        await self._manager.async_select_mode(OPTIONS[option])
