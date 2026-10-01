"""Mirror encrypted devices from the built-in BTHome integration.

The built-in BTHome integration owns the measurement parser. The control
integration subscribes to its authenticated updates when the runtime supports
sharing, and uses a local parser as fallback. Both paths follow the same Bindkey.
This module creates control entries and remembers deliberately removed entries.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components import bluetooth
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import EVENT_DEVICE_REGISTRY_UPDATED
from homeassistant.helpers.storage import Store

from .const import BTHOME_DOMAIN, CONF_ADDRESS, CONF_BINDKEY, CONF_NAME, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1

# Devices are recognised by the name their firmware advertises ("HLK-LD2401_ABCD"),
# which cannot be changed from Home Assistant. The entry title is the same name
# with the short address appended, so it only serves as a fallback for devices
# that have not been heard yet; when neither is conclusive the setup flow offers
# a manual selection instead of failing.
RADAR_NAME_PREFIX = "HLK-LD24"


def _is_radar_name(name: str | None) -> bool:
    """Return True if a Bluetooth name identifies one of these radars."""
    return bool(name) and name.strip().upper().startswith(RADAR_NAME_PREFIX)


def advertised_name(hass: HomeAssistant, address: str) -> str | None:
    """Return the name the device itself advertises, if it has been heard."""
    if not address:
        return None
    for connectable in (True, False):
        info = bluetooth.async_last_service_info(hass, address, connectable)
        if info is None:
            continue
        for candidate in (info.name, info.advertisement.local_name):
            if candidate and candidate != info.address:
                return str(candidate)
    return None


def is_radar_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Return True if a built-in BTHome entry belongs to one of these radars.

    The advertised name decides: it comes from the firmware, so renaming the
    device or the config entry in Home Assistant does not hide it. The entry
    title is only consulted for devices that have not been heard yet.
    """
    if _is_radar_name(advertised_name(hass, entry.unique_id or "")):
        return True
    return _is_radar_name(entry.title)


def carry_over_name(title: str, address: str) -> str:
    """Return the device name to reuse, without the duplicated short address.

    The built-in BTHome integration titles its entries "<name> <short address>",
    e.g. "HLK-LD2401_ABCD ABCD"; the name alone is what we carry over. A name
    that merely ends in the same four characters without the separator (such as
    the advertised name "HLK-LD2401_ABCD") is left untouched.
    """
    name = title.strip()
    short_address = address.replace(":", "")[-4:].upper()
    suffix = f" {short_address}"
    if short_address and name.upper().endswith(suffix):
        name = name[: -len(suffix)].rstrip()
    return name or title.strip()


def format_unique_id(address: str) -> str:
    """Return the unique id this integration uses for an address."""
    return address.replace(":", "").lower()


def find_bthome_entry(hass: HomeAssistant, address: str) -> ConfigEntry | None:
    """Return the built-in BTHome entry for an address, if it has a Bindkey."""
    unique_id = format_unique_id(address)
    for entry in hass.config_entries.async_entries(BTHOME_DOMAIN):
        if entry.domain != BTHOME_DOMAIN:
            continue
        if format_unique_id(entry.unique_id or "") != unique_id:
            continue
        if entry.data.get(CONF_BINDKEY):
            return entry
    return None


@callback
def async_get_mirror(hass: HomeAssistant) -> BTHomeMirror:
    """Return the mirror, creating it on first use.

    Config flows run before the component is set up (first discovery or a
    manual add), so nothing may depend on async_setup having run.
    """
    if (mirror := hass.data.get(DOMAIN)) is None:
        mirror = hass.data[DOMAIN] = BTHomeMirror(hass)
    return mirror


class RemovedAddresses:
    """Addresses whose control entry the user removed on purpose."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.removed.json")
        self._addresses: set[str] = set()

    async def async_load(self) -> None:
        """Load the stored list."""
        if isinstance(data := await self._store.async_load(), dict):
            self._addresses = {str(item) for item in data.get("removed", [])}

    def has(self, address: str) -> bool:
        """Return True if the user removed the entry for this address."""
        return format_unique_id(address) in self._addresses

    async def async_mark(self, address: str) -> None:
        """Remember that the entry for this address was removed by the user."""
        self._addresses.add(format_unique_id(address))
        await self._store.async_save({"removed": sorted(self._addresses)})

    async def async_discard(self, address: str) -> None:
        """Forget a removal, typically because the entry was added again."""
        if not self.has(address):
            return
        self._addresses.discard(format_unique_id(address))
        await self._store.async_save({"removed": sorted(self._addresses)})


class BTHomeMirror:
    """Add a control entry when the built-in BTHome integration adds the module."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.removed = RemovedAddresses(hass)
        self._setup_done = False

    async def async_setup(self) -> None:
        """Load the removal list and follow the built-in integration (idempotent).

        Flows can run before the component is set up, so this may be the first
        and only place where the mirror gets wired.
        """
        if self._setup_done:
            return
        self._setup_done = True
        await self.removed.async_load()
        for entry in self.hass.config_entries.async_entries(BTHOME_DOMAIN):
            if is_radar_entry(self.hass, entry):
                self._async_mirror_entry(entry)
        self.hass.bus.async_listen(
            EVENT_DEVICE_REGISTRY_UPDATED, self._async_handle_device_registry_event
        )

    @callback
    def _async_handle_device_registry_event(self, event: Event) -> None:
        """Follow devices the built-in integration registers while we are loaded.

        A BTHome device is created when its entry is set up, and updated when
        entries are linked to or unlinked from it, so both actions are checked.
        """
        if event.data.get("action") not in ("create", "update"):
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get(event.data["device_id"])
        if device is None:
            return
        for entry_id in device.config_entries:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if (
                entry is not None
                and entry.domain == BTHOME_DOMAIN
                and is_radar_entry(self.hass, entry)
            ):
                self._async_mirror_entry(entry)

    @callback
    def async_start_import_flow(self, address: str, bindkey: str, name: str) -> None:
        """Create a control entry through a silent import flow."""
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={
                    CONF_ADDRESS: address,
                    CONF_BINDKEY: bindkey,
                    CONF_NAME: name,
                },
            )
        )

    @callback
    def _async_mirror_entry(self, entry: ConfigEntry) -> None:
        """Create a control entry for a BTHome entry, unless the user removed it."""
        address = entry.unique_id or ""
        bindkey = entry.data.get(CONF_BINDKEY)
        if not address or not bindkey or self.removed.has(address):
            return
        unique_id = format_unique_id(address)
        for own_entry in self.hass.config_entries.async_entries(DOMAIN):
            if own_entry.unique_id == unique_id:
                return
        _LOGGER.debug("Mirroring BTHome entry %s (%s)", entry.title, address)
        self.async_start_import_flow(
            address, str(bindkey), carry_over_name(entry.title, address)
        )
