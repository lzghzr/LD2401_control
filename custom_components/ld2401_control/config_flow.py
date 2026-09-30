"""User setup, reconfiguration, and BTHome mirroring flows."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import SOURCE_IMPORT, ConfigFlow, ConfigFlowResult

from .codec import normalize_address
from .const import BTHOME_DOMAIN, CONF_ACTION, CONF_ADDRESS, CONF_BINDKEY, CONF_NAME, DOMAIN
from .mirror import (
    advertised_name,
    async_get_mirror,
    carry_over_name,
    find_bthome_entry,
    format_unique_id,
    is_radar_entry,
)

ACTION_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def _validate_action(value: str) -> str:
    """Validate an entered ESPHome action name; empty means pick automatically."""
    action = value.strip().lower()
    if not action:
        return ""
    if not ACTION_RE.fullmatch(action):
        raise ValueError("invalid_action")
    return action


class LD2401ControlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Import the module from the built-in BTHome integration.

    The Bindkey always follows the built-in entry for the same address, so no
    manual input is needed; the flow only asks which device when several
    radars are configured there.
    """

    VERSION = 1

    def _own_unique_ids(self) -> set[str]:
        """Return the addresses this integration already has an entry for."""
        return {
            entry.unique_id
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        }

    def _bthome_entries(self) -> list[Any]:
        """Return built-in BTHome entries that carry a Bindkey, sorted by address."""
        return sorted(
            (
                entry
                for entry in self.hass.config_entries.async_entries(BTHOME_DOMAIN)
                if entry.domain == BTHOME_DOMAIN and entry.data.get(CONF_BINDKEY)
            ),
            key=lambda entry: entry.unique_id or "",
        )

    def _radar_candidates(self) -> list[Any]:
        """Return the radar entries recognised by name that we do not have yet."""
        own = self._own_unique_ids()
        return [
            entry
            for entry in self._bthome_entries()
            if is_radar_entry(self.hass, entry)
            and format_unique_id(entry.unique_id or "") not in own
        ]

    def _pickable_entries(self) -> list[Any]:
        """Return the BTHome entries a user may import by hand.

        Radars are recognised automatically, and a device whose advertisement we
        have heard and that is not a radar is left out, so it cannot be picked by
        mistake. Devices we have not heard yet are unknown and are offered.
        """
        own = self._own_unique_ids()
        return [
            entry
            for entry in self._bthome_entries()
            if format_unique_id(entry.unique_id or "") not in own
            and advertised_name(self.hass, entry.unique_id or "") is None
        ]

    async def _async_import_candidate(self, candidate: Any) -> ConfigFlowResult:
        """Import one built-in BTHome entry into this integration."""
        address = normalize_address(candidate.unique_id or "")
        mirror = async_get_mirror(self.hass)
        await mirror.async_setup()
        # Adding it here is an explicit decision, so forget an earlier removal.
        await mirror.removed.async_discard(address)
        return await self.async_step_import(
            {
                CONF_ADDRESS: address,
                CONF_NAME: candidate.title,
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import the radars from the built-in BTHome integration.

        Radars recognised by their advertised name are imported without any
        form (the first one through this flow so Home Assistant reports the
        integration as added, the rest through the same silent import the mirror
        uses). If nothing can be recognised — a renamed device that has not been
        heard yet — the devices are offered for manual selection instead.
        """
        candidates = self._radar_candidates()
        if candidates:
            created = await self._async_import_candidate(candidates[0])
            for candidate in candidates[1:]:
                address = normalize_address(candidate.unique_id or "")
                mirror = async_get_mirror(self.hass)
                await mirror.removed.async_discard(address)
                mirror.async_start_import_flow(
                    address,
                    str(candidate.data[CONF_BINDKEY]),
                    carry_over_name(candidate.title, address),
                )
            return created

        pickable = self._pickable_entries()
        if not pickable:
            # Nothing left to offer: either every radar is set up already, or the
            # only devices left are known not to be radars.
            own = self._own_unique_ids()
            configured = [
                entry
                for entry in self._bthome_entries()
                if format_unique_id(entry.unique_id or "") in own
            ]
            return self.async_abort(
                reason="already_configured" if configured else "no_devices_found"
            )
        if user_input is not None:
            for entry in pickable:
                if entry.unique_id == user_input[CONF_ADDRESS]:
                    return await self._async_import_candidate(entry)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            entry.unique_id: self._pick_label(entry)
                            for entry in pickable
                        }
                    )
                }
            ),
        )

    def _pick_label(self, entry: Any) -> str:
        """Describe a device in the manual selection list."""
        address = entry.unique_id or ""
        name = carry_over_name(entry.title, address)
        return f"{name} — {address}"

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the ESPHome action; the Bindkey follows the BTHome entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                action = _validate_action(user_input[CONF_ACTION])
            except ValueError as err:
                errors["base"] = str(err)
            else:
                await self.async_set_unique_id(entry.unique_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_ACTION: action},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ACTION, default=entry.data.get(CONF_ACTION, "")
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Mirror the built-in BTHome entry for this device, if there is one."""
        await self.async_set_unique_id(format_unique_id(discovery_info.address))
        self._abort_if_unique_id_configured()
        if find_bthome_entry(self.hass, discovery_info.address) is None:
            return self.async_abort(reason="no_bthome_entry")
        return await self.async_step_import(
            {
                CONF_ADDRESS: discovery_info.address,
                CONF_NAME: discovery_info.name,
            }
        )

    async def async_step_import(
        self, import_data: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create an entry from the built-in BTHome integration's data."""
        assert import_data is not None
        mirror = async_get_mirror(self.hass)
        await mirror.async_setup()
        address = normalize_address(import_data[CONF_ADDRESS])
        if mirror.removed.has(address):
            # The user removed this control entry; do not recreate it.
            return self.async_abort(reason="user_removed")
        if (bthome_entry := find_bthome_entry(self.hass, address)) is None:
            return self.async_abort(reason="no_bthome_entry")
        await self.async_set_unique_id(format_unique_id(address))
        self._abort_if_unique_id_configured()
        name = carry_over_name(
            import_data[CONF_NAME] or bthome_entry.title, address
        )
        return self.async_create_entry(
            title=name,
            data={
                CONF_ADDRESS: address,
                CONF_NAME: name,
                CONF_BINDKEY: str(bthome_entry.data[CONF_BINDKEY]),
                CONF_ACTION: "",
            },
        )
