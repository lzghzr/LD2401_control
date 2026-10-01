"""Developer checks using encrypted public fixtures and HA runtime boundaries."""

import asyncio
import time
from types import SimpleNamespace

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bthome_ble.parser import BTHomeBluetoothDeviceData
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from habluetooth import BluetoothServiceInfoBleak
import pytest

from conftest import (
    ConfigEntryState, HomeAssistantError, coordinator, frames_module,
    manager_module, shared_module,
)

KEY = bytes(range(16))
ADDRESS = "02:00:00:00:00:01"
UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"


def advertisement(counter, hold=False, level=False, *, key=KEY, legacy=False, corrupt=False):
    plain = bytes.fromhex("05000100")
    if not legacy:
        plain += bytes([0x0F, hold])
    plain += bytes([0x10, level, 0x21, 0, 0x23, 0, 0x40, 100, 0])
    count = counter.to_bytes(4, "little")
    nonce = bytes.fromhex(ADDRESS.replace(":", "")) + bytes.fromhex("d2fc41") + count
    encrypted = AESCCM(key, tag_length=4).encrypt(nonce, plain, None)
    payload = b"\x41" + encrypted[:-4] + count + encrypted[-4:]
    if corrupt:
        payload = payload[:-1] + bytes([payload[-1] ^ 1])
    adv = AdvertisementData(
        local_name="HLK-LD2401_0001", manufacturer_data={},
        service_data={UUID: payload}, service_uuids=[UUID],
        tx_power=None, rssi=-50, platform_data=(),
    )
    return BluetoothServiceInfoBleak(
        name=adv.local_name, address=ADDRESS, rssi=-50,
        manufacturer_data={}, service_data=adv.service_data, service_uuids=[UUID],
        source="fixture", device=BLEDevice(ADDRESS, adv.local_name, {}),
        advertisement=adv, connectable=False, time=time.monotonic(), tx_power=None,
    )


@pytest.mark.parametrize("hold,level,mode", [(0, 0, 2), (0, 1, 2), (1, 0, 0), (1, 1, 1)])
def test_authenticated_modes(hold, level, mode):
    frames = frames_module.BTHomeFrames(KEY)
    assert frames.update(advertisement(8193, hold, level))
    assert frames.mode == mode
    assert not frames.update(advertisement(8193, hold, level))
    assert not frames.update(advertisement(8192, hold, level))
    assert not frames.update(advertisement(8194, not hold, not level, corrupt=True))
    assert frames.counter == 8193 and frames.mode == mode


def test_key_epoch_and_legacy_feedback():
    frames = frames_module.BTHomeFrames(KEY)
    assert frames.update(advertisement(50000, 1, 1))
    other = bytes(range(16, 32))
    frames.ensure_bindkey(other)
    assert frames.counter is None and frames.mode is None
    assert frames.update(advertisement(8193, 1, 0, key=other))
    assert frames.mode == 0
    assert frames.update(advertisement(8194, key=other, legacy=True))
    assert frames.mode is None


def test_shared_updates_use_authenticated_parser():
    parser = BTHomeBluetoothDeviceData(bindkey=KEY)
    owner = coordinator(parser)
    frames = frames_module.BTHomeFrames(KEY)
    accepted = []
    cancel = shared_module.subscribe_updates(owner, lambda p, u: accepted.append(frames.accept(p, u)))
    owner._process_update(parser.update(advertisement(8193, 1, 1)))
    assert parser.bindkey_verified and not parser.decryption_failed
    assert accepted == [True] and frames.mode == 1
    assert frames.counter == parser.encryption_counter == 8193
    assert frames._parser is None  # sharing never creates a fallback parser
    owner._process_update(parser.update(advertisement(8194, 1, 0, corrupt=True)))
    assert parser.decryption_failed
    assert accepted == [True, False]
    assert frames.counter == 8193 and frames.mode == 1
    owner._process_update(parser.update(advertisement(8195, 1, 0)))
    assert parser.bindkey_verified and not parser.decryption_failed
    assert accepted == [True, False, True]
    assert frames.counter == parser.encryption_counter == 8195 and frames.mode == 0
    assert frames._parser is None
    cancel()
    assert not owner._processors


def manager():
    parser = BTHomeBluetoothDeviceData(bindkey=KEY)
    owner = coordinator(parser)
    entry = SimpleNamespace(
        data={"bindkey": KEY.hex()}, state=ConfigEntryState.LOADED, runtime_data=owner,
    )
    hass = SimpleNamespace(bthome_entry=entry)
    value = manager_module.LD2401ControlManager(
        hass, address=ADDRESS, bindkey=KEY, action="", name="Fixture radar",
    )
    return value, hass, owner


def feed(value, counter, hold=0, level=0):
    assert value.frames.update(advertisement(counter, hold, level))
    value._accepted_frame()


def test_shared_reload_fallback_and_rotation():
    value, hass, owner = manager()
    value._ensure_shared()
    assert len(owner._processors) == 1
    value._async_handle_advertisement(advertisement(8193), None)
    assert value.frames._parser is None
    owner._process_update(owner.device_data.update(advertisement(8193)))
    assert value.available and value.mode == 2
    hass.bthome_entry.state = ConfigEntryState.NOT_LOADED
    value._async_handle_advertisement(advertisement(8194, 1, 1), None)
    assert not owner._processors and value.mode == 1
    replacement = coordinator(BTHomeBluetoothDeviceData(bindkey=KEY))
    hass.bthome_entry.runtime_data = replacement
    hass.bthome_entry.state = ConfigEntryState.LOADED
    value._ensure_shared()
    assert len(replacement._processors) == 1
    # Once sharing resumes there is no local parser work on the raw callback.
    fallback = value.frames._parser
    value._async_handle_advertisement(advertisement(8195), None)
    assert fallback.encryption_counter == 8194
    replacement._process_update(replacement.device_data.update(advertisement(8195)))
    assert value.frames.counter == 8195
    other = bytes(range(16, 32))
    hass.bthome_entry.data["bindkey"] = other.hex()
    value._async_handle_advertisement(advertisement(8193, 1, 0, key=other), None)
    assert value.mode == 0 and value.frames.counter == 8193
    assert value._last_sent_counter == 0 and not replacement._processors
    value.stop()
    assert not value.available


def test_incompatible_runtime_and_notification_filtering():
    value, hass, _owner = manager()
    hass.bthome_entry.runtime_data = SimpleNamespace()
    changes = []
    value.add_listener(lambda: changes.append((value.mode, value.available)))
    value._async_handle_advertisement(advertisement(8193), None)
    value._async_handle_advertisement(advertisement(8194), None)
    assert value._shared_coordinator is None
    assert changes == [(2, True)]
    value._last_received -= 46
    value._runtime_tick(None)
    assert changes[-1] == (2, False)


def test_immediate_selection_and_broadcast_reconciliation():
    async def scenario():
        value, _, _ = manager()
        feed(value, 8193)
        sending = asyncio.Event()
        finish = asyncio.Event()

        async def send(_mode):
            value._request_counter = 8193
            sending.set()
            await finish.wait()

        value.async_send_mode = send
        task = asyncio.create_task(value.async_select_mode(1))
        await sending.wait()
        assert value.mode == 1
        feed(value, 8194)  # stale module mode cannot flash the selection back
        assert value.mode == 1
        feed(value, 8195, 1, 1)
        assert value.mode == 1 and value._requested_mode is None
        finish.set()
        await task
        assert value._request_deadline is None

    asyncio.run(scenario())


def test_failed_and_unconfirmed_selection_reconciles():
    async def scenario():
        value, _, _ = manager()
        feed(value, 8193)

        async def fail(_mode):
            assert value.mode == 0
            raise HomeAssistantError("Fixture transport failure")

        value.async_send_mode = fail
        with pytest.raises(HomeAssistantError):
            await value.async_select_mode(0)
        assert value.mode == 2

        async def send(_mode):
            value._request_counter = 8193

        value.async_send_mode = send
        await value.async_select_mode(1)
        value._request_deadline = time.monotonic() - 1
        feed(value, 8194)
        assert value.mode == 2

    asyncio.run(scenario())


def test_real_sender_uses_fresh_counter_and_skips_superseded_commands(monkeypatch):
    async def scenario():
        value, hass, _ = manager()
        calls = []
        transmitting = asyncio.Event()
        finish = asyncio.Event()

        async def call(domain, service, data, *, blocking):
            calls.append((domain, service, data, blocking))
            transmitting.set()
            await finish.wait()

        hass.services = SimpleNamespace(
            async_services_for_domain=lambda _domain: {"fixture_ld2401_control_broadcast": {}},
            has_service=lambda domain, service: domain == 'esphome' and service == 'fixture_ld2401_control_broadcast',
            async_call=call,
        )
        value._configured_action = ['esphome', 'fixture_ld2401_control_broadcast']
        feed(value, 8193)
        first = asyncio.create_task(value.async_select_mode(0))
        await asyncio.sleep(0)
        feed(value, 8194)
        await transmitting.wait()
        assert value.mode == 0
        obsolete = asyncio.create_task(value.async_select_mode(1))
        await asyncio.sleep(0)
        last = asyncio.create_task(value.async_select_mode(2))
        await asyncio.sleep(0)
        assert value.mode == 2
        finish.set()
        await first
        await obsolete
        await asyncio.sleep(0)
        feed(value, 8195, 1, 0)
        await last
        assert len(calls) == 2
        assert calls[0][2]["payload"] == manager_module.make_control_frame(KEY, ADDRESS, 8194, 0).hex()
        assert calls[1][2]["payload"] == manager_module.make_control_frame(KEY, ADDRESS, 8195, 2).hex()
        assert value.mode == 2
        feed(value, 8196)
        assert value._requested_mode is None and value.mode == 2

    monkeypatch.setattr(manager_module, "ESP_ACTION_TIME", 0)
    asyncio.run(scenario())
