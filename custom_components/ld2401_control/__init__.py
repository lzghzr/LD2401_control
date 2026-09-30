"""Control an HLK LD2401 through authenticated manufacturer advertisements."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ACTION, CONF_BINDKEY, CONF_ADDRESS, DOMAIN
from .coordinator import LD2401ControlManager
from .mirror import async_get_mirror

PLATFORMS: list[Platform] = [Platform.BUTTON]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Watch the built-in BTHome integration so its devices can be mirrored."""
    await async_get_mirror(hass).async_setup()
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the passive listener and the OUT mode command buttons."""
    manager = LD2401ControlManager(
        hass,
        address=entry.data[CONF_ADDRESS],
        bindkey=bytes.fromhex(entry.data[CONF_BINDKEY]),
        action=entry.data.get(CONF_ACTION, ""),
        name=entry.title,
    )
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.start()
    entry.async_on_unload(manager.stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms and stop the Bluetooth listener."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remember the removal so the BTHome mirror does not recreate the entry."""
    mirror = async_get_mirror(hass)
    await mirror.async_setup()
    await mirror.removed.async_mark(entry.data[CONF_ADDRESS])
