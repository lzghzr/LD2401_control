"""Stateless authenticated OUT control buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import OUT_MODE_AUTO, OUT_MODE_HIGH, OUT_MODE_LOW
from .coordinator import LD2401ControlManager

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add low, high, and automatic command buttons."""
    manager: LD2401ControlManager = entry.runtime_data
    async_add_entities(
        [
            LD2401OutButton(manager, mode=OUT_MODE_LOW, key="out_low"),
            LD2401OutButton(manager, mode=OUT_MODE_HIGH, key="out_high"),
            LD2401OutButton(manager, mode=OUT_MODE_AUTO, key="out_auto"),
        ]
    )


class LD2401OutButton(ButtonEntity):
    """A stateless command; the physical OUT level is reported by BTHome."""

    _attr_has_entity_name = True

    def __init__(self, manager: LD2401ControlManager, *, mode: int, key: str) -> None:
        self._manager = manager
        self._mode = mode
        self._attr_translation_key = key
        self._attr_unique_id = f"{manager.address.replace(':', '').lower()}_{key}"
        # Suggest the entity id: it is anchored on the module address, so it
        # stays put when the device is renamed or a translation changes. Home
        # Assistant only uses this while creating the entity; renaming it later
        # in the UI still wins.
        short_address = manager.address.replace(":", "").lower()[-4:]
        self.entity_id = f"button.ld2401_{short_address}_{key}"
        self._attr_device_info = DeviceInfo(
            connections={(dr.CONNECTION_BLUETOOTH, manager.address)},
            manufacturer="HLK",
            model="LD2401",
            name=manager.name,
        )

    async def async_press(self) -> None:
        """Publish an authenticated OUT mode command through ESPHome."""
        await self._manager.async_send_mode(self._mode)
