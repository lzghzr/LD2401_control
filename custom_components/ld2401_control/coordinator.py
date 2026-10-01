"""Shared BTHome feedback and serialized ESPHome mode commands."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
import time

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval

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
    MODE_SETTLE_TIME,
    RUNTIME_CHECK_INTERVAL,
)
from .mirror import find_bthome_entry
from .shared import subscribe_updates

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
        self._cancel_timer: Callable[[], None] | None = None
        self._shared_coordinator = None
        self._cancel_shared: Callable[[], None] | None = None
        self._unsupported_coordinator = None
        self._listeners: set[Callable[[], None]] = set()
        self._last_state: tuple[int | None, bool] = (None, False)
        self._requested_mode: int | None = None
        self._request_counter: int | None = None
        self._request_deadline: float | None = None
        self._selection_id = 0
        self._stopped = False

    @property
    def mode(self) -> int | None:
        return self._requested_mode if self._requested_mode is not None else self.frames.mode

    @property
    def available(self) -> bool:
        return (
            not self._stopped
            and self.frames.mode is not None
            and time.monotonic() - self._last_received <= COUNTER_MAX_AGE
        )

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @callback
    def _notify_state(self) -> None:
        state = (self.mode, self.available)
        if state != self._last_state:
            self._last_state = state
            for listener in tuple(self._listeners):
                listener()

    @callback
    def _refresh_bindkey(self) -> bytes:
        key = self._current_bindkey()
        if key != self.frames.bindkey:
            self.frames.ensure_bindkey(key)
            self._last_sent_counter = 0
            self._last_received = 0.0
            self._clear_request()
            self._counter_changed.set()
            self._notify_state()
        return key

    @callback
    def _clear_request(self) -> None:
        self._requested_mode = None
        self._request_counter = None
        self._request_deadline = None

    @callback
    def _accepted_frame(self, source: str | None = None) -> None:
        if source:
            self._last_source = source
        self._last_received = time.monotonic()
        self._counter_changed.set()
        if (
            self._requested_mode is not None
            and self._request_counter is not None
            and self.frames.counter is not None
            and self.frames.counter > self._request_counter
            and self.frames.mode == self._requested_mode
        ):
            self._clear_request()
        elif self._request_deadline is not None and time.monotonic() >= self._request_deadline:
            self._clear_request()
        self._notify_state()

    @callback
    def _shared_update(self, parser, update) -> None:
        self._refresh_bindkey()
        try:
            accepted = self.frames.accept(parser, update)
        except (AttributeError, TypeError, ValueError):
            self._unsupported_coordinator = self._shared_coordinator
            self._detach_shared()
            _LOGGER.warning("BTHome runtime changed; using local parsing for %s", self.address)
            return
        if accepted:
            info = getattr(parser, "last_service_info", None)
            self._accepted_frame(getattr(info, "source", None))

    @callback
    def _detach_shared(self) -> None:
        if self._cancel_shared is not None:
            self._cancel_shared()
        self._cancel_shared = None
        self._shared_coordinator = None

    @callback
    def _ensure_shared(self) -> None:
        entry = find_bthome_entry(self.hass, self.address)
        coordinator = getattr(entry, "runtime_data", None)
        if (
            getattr(entry, "state", None) is not ConfigEntryState.LOADED
            or getattr(getattr(coordinator, "device_data", None), "bindkey", None) != self.frames.bindkey
        ):
            coordinator = None
        if coordinator is self._shared_coordinator:
            return
        self._detach_shared()
        if coordinator is None or coordinator is self._unsupported_coordinator:
            return
        try:
            cancel = subscribe_updates(coordinator, self._shared_update)
        except (ImportError, AttributeError, TypeError, ValueError):
            self._unsupported_coordinator = coordinator
            _LOGGER.warning("BTHome sharing is unavailable; using local parsing for %s", self.address)
            return
        self._cancel_shared = cancel
        self._shared_coordinator = coordinator
        self._unsupported_coordinator = None

    @callback
    def _runtime_tick(self, _now) -> None:
        self._refresh_bindkey()
        self._ensure_shared()
        if self._request_deadline is not None and time.monotonic() >= self._request_deadline:
            if self.frames.mode != self._requested_mode:
                _LOGGER.warning("OUT mode feedback did not converge for %s", self.address)
            self._clear_request()
        self._notify_state()

    def _current_bindkey(self) -> bytes:
        """Return the Bindkey to use right now.

        The linked built-in BTHome entry wins, so a key rotation there is
        followed automatically; the stored key is only the fallback for setups
        without that entry.
        """
        if (entry := find_bthome_entry(self.hass, self.address)) is not None:
            self.bindkey = bytes.fromhex(str(entry.data[CONF_BINDKEY]))
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
        self._stopped = False
        self._ensure_shared()
        self._cancel_timer = async_track_time_interval(
            self.hass, self._runtime_tick, timedelta(seconds=RUNTIME_CHECK_INTERVAL)
        )
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
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None
        self._detach_shared()
        self._stopped = True
        self._counter_changed.set()
        self._notify_state()

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
        self._refresh_bindkey()
        self._ensure_shared()
        if self._shared_coordinator is not None:
            # The built-in coordinator performs authentication and invokes our
            # processor afterwards. This raw callback does no second parsing.
            return
        if not self.frames.update(service_info):
            # A duplicate, replayed, malformed or unauthenticated frame.
            return
        _LOGGER.debug("Accepted fresh BTHome counter from %s", self.address)
        self._accepted_frame(service_info.source)

    async def _wait_for_new_counter(self, after_counter: int) -> int:
        """Wait for a recent counter newer than the one already used or observed."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + COUNTER_WAIT_TIMEOUT
        while True:
            if self._stopped:
                raise HomeAssistantError("LD2401 control was unloaded.")
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
        selection = self._selection_id
        async with self._send_lock:
            if selection != self._selection_id:
                return
            # Require a counter received after this command. A cached advertisement
            # may already have authorized an earlier command before HA reloaded.
            after_counter = max(self._last_sent_counter, self.frames.counter or 0)
            counter = await self._wait_for_new_counter(after_counter)
            if selection != self._selection_id:
                return
            key = self._refresh_bindkey()
            if self.frames.counter != counter:
                raise HomeAssistantError("The Bindkey changed while preparing the command; try again.")
            frame = make_control_frame(key, self.address, counter, mode)
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
            if self._requested_mode == mode:
                self._request_counter = counter
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

    async def async_select_mode(self, mode: int) -> None:
        """Display the selected mode immediately and reconcile future feedback."""
        if not self.available:
            raise HomeAssistantError("No recent OUT mode feedback is available. Firmware 26092431 is required.")
        self._selection_id += 1
        selection = self._selection_id
        self._requested_mode = mode
        self._request_counter = None
        self._request_deadline = None
        self._notify_state()
        try:
            await self.async_send_mode(mode)
        except (Exception, asyncio.CancelledError):
            if selection == self._selection_id:
                self._clear_request()
                self._notify_state()
            raise
        if selection == self._selection_id and self._requested_mode is not None:
            self._request_deadline = time.monotonic() + MODE_SETTLE_TIME
