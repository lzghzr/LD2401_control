"""Passive BTHome counter listener and serialized ESPHome command sender."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .bthome import BTHomeFrames
from .codec import make_control_frame, normalize_address
from .const import (
    BTHOME_SERVICE_UUID,
    CONF_BINDKEY,
    COUNTER_MAX_AGE,
    COUNTER_WAIT_TIMEOUT,
    ESP_ACTION_TIME,
    ESPHOME_ACTION_SUFFIX,
    ESPHOME_DOMAIN,
)
from .mirror import find_bthome_entry

_LOGGER = logging.getLogger(__name__)


def _normalise_node_name(value: str) -> str:
    """Normalise a node or scanner name the way ESPHome service names are built."""
    return (
        value.strip()
        .lower()
        .replace("-", "_")
        .replace(".", "_")
        .replace(" ", "_")
    )


def _control_action_candidates(
    hass: HomeAssistant,
) -> list[tuple[str, str]]:
    """Return ESPHome services that broadcast control frames, sorted by name."""
    suffix = f"_{ESPHOME_ACTION_SUFFIX}"
    services = hass.services.async_services_for_domain(ESPHOME_DOMAIN)
    return sorted(
        (ESPHOME_DOMAIN, name) for name in services if name.endswith(suffix)
    )


class LD2401ControlManager:
    """Maintain the latest authenticated BTHome counter without connecting to the radar."""

    def __init__(
        self, hass: HomeAssistant, *, address: str, bindkey: bytes, action: str, name: str
    ) -> None:
        self.hass = hass
        self.address = normalize_address(address)
        self.bindkey = bindkey
        self.name = name
        # An explicitly configured action; empty means pick automatically.
        self._configured_action = action.split(".", 1) if action else None
        self._last_source: str | None = None
        self.frames = BTHomeFrames(bindkey)
        self._last_received = 0.0
        self._last_sent_counter = 0
        self._counter_changed = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._cancel_callback: Callable[[], None] | None = None

    def _current_bindkey(self) -> bytes:
        """Return the Bindkey to use right now.

        The linked built-in BTHome entry wins, so a key rotation there is
        followed automatically; the stored key is only the fallback for setups
        without that entry.
        """
        if (entry := find_bthome_entry(self.hass, self.address)) is not None:
            return bytes.fromhex(str(entry.data[CONF_BINDKEY]))
        return self.bindkey

    @callback
    def _async_resolve_action(self) -> tuple[str, str] | None:
        """Return the ESPHome action to broadcast through.

        A configured action wins while the service exists. Otherwise the nodes
        offering the control action are ranked by who is currently hearing the
        radar, so the frame is sent from where it is received.
        """
        if self._configured_action is not None:
            domain, service = self._configured_action
            if self.hass.services.has_service(domain, service):
                return domain, service
            _LOGGER.info(
                "Configured action %s.%s is unavailable; trying auto discovery",
                domain,
                service,
            )

        candidates = _control_action_candidates(self.hass)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        heard: set[str] = set()
        for connectable in (True, False):
            for device in bluetooth.async_scanner_devices_by_address(
                self.hass, self.address, connectable
            ):
                for value in (device.scanner.name, device.scanner.source):
                    if value:
                        heard.add(_normalise_node_name(value))
        if self._last_source:
            heard.add(_normalise_node_name(self._last_source))

        for domain, service in candidates:
            node_name = _normalise_node_name(
                service[: -(len(ESPHOME_ACTION_SUFFIX) + 1)]
            )
            if node_name in heard:
                return domain, service
        return candidates[0]

    def start(self) -> None:
        """Listen to cached and live advertisements from Home Assistant's BLE manager."""
        self._cancel_callback = bluetooth.async_register_callback(
            self.hass,
            self._async_handle_advertisement,
            # Match by address and inspect service_data ourselves. Some scanners expose
            # 0xFCD2 under service_data without listing it in service_uuids.
            {"address": self.address},
            bluetooth.BluetoothScanningMode.PASSIVE,
            replay=bluetooth.BluetoothCallbackReplay.NEWEST_FIRST,
        )

    @callback
    def stop(self) -> None:
        """Remove the Bluetooth callback."""
        if self._cancel_callback is not None:
            self._cancel_callback()
            self._cancel_callback = None

    @callback
    def _async_handle_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Accept only newer BTHome counters that this Bindkey authenticates."""
        if service_info.address.upper() != self.address:
            return
        if not any(
            uuid.lower() == BTHOME_SERVICE_UUID
            for uuid in service_info.service_data
        ):
            return
        # Follow a Bindkey rotation made in the built-in BTHome integration.
        self.frames.ensure_bindkey(self._current_bindkey())
        if not self.frames.update(service_info):
            # A duplicate, replayed, malformed or unauthenticated frame.
            return
        _LOGGER.debug("Accepted fresh BTHome counter from %s", self.address)
        self._last_source = service_info.source
        self._last_received = time.monotonic()
        self._counter_changed.set()

    async def _wait_for_new_counter(self, after_counter: int) -> int:
        """Wait for a recent counter newer than the one already used or observed."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + COUNTER_WAIT_TIMEOUT
        while True:
            self._counter_changed.clear()
            counter = self.frames.counter
            age = time.monotonic() - self._last_received
            if (
                counter is not None
                and counter > after_counter
                and age <= COUNTER_MAX_AGE
            ):
                return counter

            remaining = deadline - loop.time()
            if remaining <= 0:
                raise HomeAssistantError(
                    "No fresh authenticated BTHome counter is available. "
                    "Check Bluetooth reception and the configured Bindkey."
                )
            try:
                await asyncio.wait_for(self._counter_changed.wait(), remaining)
            except TimeoutError as err:
                raise HomeAssistantError(
                    "No fresh authenticated BTHome counter is available. "
                    "Check Bluetooth reception and the configured Bindkey."
                ) from err

    async def async_send_mode(self, mode: int) -> None:
        """Send one authenticated mode command through the ESPHome broadcast action."""
        async with self._send_lock:
            # Require a counter received after this command. A cached advertisement
            # may already have authorized an earlier command before HA reloaded.
            after_counter = max(self._last_sent_counter, self.frames.counter or 0)
            counter = await self._wait_for_new_counter(after_counter)
            frame = make_control_frame(self._current_bindkey(), self.address, counter, mode)
            if (action := self._async_resolve_action()) is None:
                raise HomeAssistantError(
                    f"No ESPHome action named *_{ESPHOME_ACTION_SUFFIX} was found. "
                    "Install the broadcast action on an ESPHome node, or set a "
                    "specific action in the integration's reconfigure flow."
                )
            action_domain, action_service = action

            # Reserve the counter before handing the frame to ESPHome. If delivery becomes
            # ambiguous, skip ahead to the next authenticated BTHome frame rather than replay.
            self._last_sent_counter = counter
            try:
                await self.hass.services.async_call(
                    action_domain,
                    action_service,
                    {"payload": frame.hex()},
                    blocking=True,
                )
            except HomeAssistantError:
                # Already a translated, user-visible message — for example the
                # node reporting through api.respond that it refused the frame.
                raise
            except Exception as err:
                raise HomeAssistantError(
                    "Home Assistant could not call the ESPHome broadcast action."
                ) from err
            await asyncio.sleep(ESP_ACTION_TIME)
