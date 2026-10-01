"""Exercise sender discovery with real HA scanner display-name formatting."""

from types import SimpleNamespace
import asyncio
import logging
import time

from bluetooth_adapters import adapter_human_name
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.cmac import CMAC
import pytest
from habluetooth import BaseHaRemoteScanner, BluetoothManager
from habluetooth.central_manager import CentralBluetoothManager
from habluetooth.storage import DiscoveredDeviceAdvertisementData

from conftest import HomeAssistantError, bluetooth, manager_module, select_module
from test_mode_feedback import ADDRESS, KEY, advertisement, feed, manager


def sender(name, source, received=None):
    return SimpleNamespace(
        adapter=name, source=source, name=adapter_human_name(name, source),
        discovered_device_timestamps={ADDRESS: time.monotonic() if received is None else received},
    )


def services(hass, names):
    hass.services = SimpleNamespace(
        async_services_for_domain=lambda _domain: {name: {} for name in names},
        has_service=lambda domain, name: domain == 'esphome' and name in names,
    )


def test_auto_sender_uses_node_identity_with_decorated_scanner_name(monkeypatch):
    value, hass, _ = manager()
    services(hass, [f'{name}_ld2401_control_broadcast' for name in ('a_far', 'm_far', 'z_near')])
    near = sender('z-near', '02:00:00:00:10:01')
    monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address',
                        lambda *_args: [SimpleNamespace(scanner=near, advertisement=SimpleNamespace(rssi=-40))])
    assert value._async_resolve_action() == ('esphome', 'z_near_ld2401_control_broadcast')


def test_explicit_sender_still_wins(monkeypatch):
    value, hass, _ = manager()
    services(hass, ['a_far_ld2401_control_broadcast', 'z_near_ld2401_control_broadcast'])
    value._configured_action = ['esphome', 'a_far_ld2401_control_broadcast']
    monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address',
                        lambda *_args: (_ for _ in ()).throw(AssertionError('explicit sender must win')))
    assert value._async_resolve_action() == ('esphome', 'a_far_ld2401_control_broadcast')


def test_strongest_receiver_wins_over_aggregate_owner_and_latest_receiver(monkeypatch):
    value, hass, _ = manager()
    names = ['a_weak_ld2401_control_broadcast', 'm_strong_ld2401_control_broadcast',
             'z_latest_ld2401_control_broadcast']
    services(hass, names)
    heard = [
        SimpleNamespace(scanner=sender(name, f'02:00:00:00:10:0{index}'),
                        advertisement=SimpleNamespace(rssi=rssi))
        for index, (name, rssi) in enumerate([('a-weak', -90), ('m-strong', -40), ('z-latest', -65)])
    ]
    monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address', lambda *_args: heard)
    assert value._async_resolve_action() == ('esphome', names[1])
    value._last_source = heard[2].scanner.source  # source is a MAC, not a node name
    assert value._async_resolve_action() == ('esphome', names[1])
    value._configured_action = ['esphome', 'removed_ld2401_control_broadcast']
    assert value._async_resolve_action() == ('esphome', names[1])


def test_unmatched_receivers_fail_without_alphabetical_fallback(monkeypatch):
    value, hass, _ = manager()
    services(hass, ['a_far_ld2401_control_broadcast', 'z_far_ld2401_control_broadcast'])
    monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address', lambda *_args: [])
    with pytest.raises(HomeAssistantError, match='within the last 30 seconds'):
        value._async_resolve_action()


def test_feedback_timeout_logs_once_without_key(caplog):
    value, _, _ = manager()
    with caplog.at_level(logging.WARNING):
        feed(value, 8193)
        value._requested_mode = 1
        value._request_counter = 8193
        value._request_action = ('esphome', 'fixture_ld2401_control_broadcast')
        value._request_deadline = time.monotonic() - 1
        feed(value, 8194)
        value._runtime_tick(None)
    assert value.mode == 2
    assert caplog.text.count('OUT mode feedback did not converge') == 1
    assert 'requested=1 observed=2' in caplog.text
    assert KEY.hex() not in caplog.text


@pytest.mark.parametrize('age,selected', [(29.999, 'strong'), (30.0, 'strong'), (30.001, 'fresh')])
def test_stale_strong_signal_is_filtered_before_rssi(monkeypatch, age, selected):
    value, hass, _ = manager()
    services(hass, [f'{name}_ld2401_control_broadcast' for name in ('strong', 'fresh')])
    monkeypatch.setattr(manager_module.time, 'monotonic', lambda: 100.0)
    heard = [
        SimpleNamespace(scanner=sender('strong', '02:00:00:00:10:01', 100 - age),
                        advertisement=SimpleNamespace(rssi=-35)),
        SimpleNamespace(scanner=sender('fresh', '02:00:00:00:10:02', 99.0),
                        advertisement=SimpleNamespace(rssi=-65)),
    ]
    # Even the previous sender and aggregate owner must pass the age filter.
    value._last_source = heard[0].scanner.source
    value._last_sender_action = ('esphome', 'strong_ld2401_control_broadcast')
    monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address', lambda *_args: heard)
    assert value._async_resolve_action() == ('esphome', f'{selected}_ld2401_control_broadcast')


@pytest.mark.parametrize('rssi,received', [(-40, None), (-40, 69.9), (-40, 100.1),
                                         (-40, float('nan')), (None, 99.0), (float('nan'), 99.0)])
def test_single_sender_needs_valid_recent_radar_observation(monkeypatch, rssi, received):
    value, hass, _ = manager()
    services(hass, ['only_ld2401_control_broadcast'])
    monkeypatch.setattr(manager_module.time, 'monotonic', lambda: 100.0)
    scanner = sender('only', '02:00:00:00:10:01')
    scanner.discovered_device_timestamps = {ADDRESS: received, '02:00:00:00:FF:FF': 100.0}
    # A fresh sighting of a different device cannot make this radar fresh.
    heard = [SimpleNamespace(scanner=scanner, advertisement=SimpleNamespace(rssi=rssi))]
    monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address', lambda *_args: heard)
    with pytest.raises(HomeAssistantError, match='within the last 30 seconds'):
        value._async_resolve_action()


@pytest.mark.parametrize('signal_gain,time_gain,previous,chosen', [
    (2, 1, False, 'newer'),   # initial choice: close signals favour newest reception
    (3, 5, True, 'previous'),  # inclusive RSSI and time hysteresis boundaries
    (4, 1, True, 'newer'),   # clearly stronger reception overrides history
    (2, 5.001, True, 'newer'),  # previous sender has fallen behind on reception
    (0, 0, False, 'newer'),  # fully equal candidates: stable action-name order
])
def test_near_equal_signals_use_reception_time_and_sender_hysteresis(
    monkeypatch, signal_gain, time_gain, previous, chosen,
):
    value, hass, _ = manager()
    services(hass, ['previous_ld2401_control_broadcast', 'newer_ld2401_control_broadcast'])
    monkeypatch.setattr(manager_module.time, 'monotonic', lambda: 100.0)
    heard = [
        SimpleNamespace(scanner=sender('previous', '02:00:00:00:10:01', 99 - time_gain),
                        advertisement=SimpleNamespace(rssi=-50)),
        SimpleNamespace(scanner=sender('newer', '02:00:00:00:10:02', 99),
                        advertisement=SimpleNamespace(rssi=-50 + signal_gain)),
    ]
    if previous:
        value._last_sender_action = ('esphome', 'previous_ld2401_control_broadcast')
    monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address', lambda *_args: heard)
    expected = ('esphome', f'{chosen}_ld2401_control_broadcast')
    assert value._async_resolve_action() == expected
    heard.reverse()
    assert value._async_resolve_action() == expected


def test_no_control_actions_remains_distinct_from_no_fresh_receiver():
    value, hass, _ = manager()
    services(hass, [])
    assert value._async_resolve_action() is None


def test_real_remote_scanners_expose_independent_timestamp_and_rssi(monkeypatch):
    value, hass, _ = manager()
    services(hass, ['old_ld2401_control_broadcast', 'near_ld2401_control_broadcast'])
    monkeypatch.setattr(CentralBluetoothManager, 'manager', BluetoothManager())
    now = time.monotonic()
    heard = []
    for index, (name, rssi, age) in enumerate([('old', -30, 31), ('near', -50, 0)]):
        scanner = BaseHaRemoteScanner(f'02:00:00:00:10:0{index}', name)
        device = BLEDevice(ADDRESS, 'HLK-LD2401', {})
        adv = AdvertisementData('HLK-LD2401', {}, {}, [], None, rssi, ())
        scanner.restore_discovered_devices(DiscoveredDeviceAdvertisementData(
            False, 120, {ADDRESS: (device, adv)}, {ADDRESS: now - age},
        ))
        assert scanner.discovered_device_timestamps[ADDRESS] == now - age
        device, adv = scanner.get_discovered_device_advertisement_data(ADDRESS)
        heard.append(SimpleNamespace(scanner=scanner, ble_device=device, advertisement=adv))
    monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address', lambda *_args: heard)
    assert value._async_resolve_action() == ('esphome', 'near_ld2401_control_broadcast')


@pytest.mark.parametrize('option,mode', [('hold_low', 0), ('hold_high', 1), ('auto', 2)])
def test_select_entity_routes_authenticated_command_and_consumes_feedback(monkeypatch, option, mode):
    async def scenario():
        value, hass, owner = manager()
        names = [f'{name}_ld2401_control_broadcast' for name in ('a_far', 'm_far', 'z_near')]
        services(hass, names)
        near = sender('z-near', '02:00:00:00:10:01')
        far = sender('a-far', '02:00:00:00:10:02')
        monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address',
                            lambda *_args: [SimpleNamespace(scanner=far, advertisement=SimpleNamespace(rssi=-75)),
                                            SimpleNamespace(scanner=near, advertisement=SimpleNamespace(rssi=-40))])
        value._ensure_shared()
        entity = select_module.LD2401OutModeSelect(value)
        entity.written_states = []
        await entity.async_added_to_hass()

        def broadcast(count, hold, level):
            info = advertisement(count, hold, level)
            info.source = near.source
            near.discovered_device_timestamps[ADDRESS] = time.monotonic()
            value._async_handle_advertisement(info, None)
            owner._process_update(owner.device_data.update(info))
            value._last_source = far.source  # HA's aggregate owner must not override RSSI

        # Begin with a different mode so optimistic state must survive until feedback.
        broadcast(8193, mode == 2, mode == 2)
        calls = []

        async def call(domain, service, data, *, blocking):
            calls.append((domain, service, data, blocking))
            assert domain == 'esphome' and service == names[2] and blocking
            frame = bytes.fromhex(data['payload'])
            assert len(frame) == 30 and frame[:10] == bytes.fromhex('0201061affd6054c4301')
            assert frame[10:16] == bytes.fromhex(ADDRESS.replace(':', ''))
            assert int.from_bytes(frame[16:20], 'little') == 8194
            assert frame[20:22] == bytes([mode, 0])
            encryptor = Cipher(algorithms.AES(KEY), modes.ECB()).encryptor()
            command_key = encryptor.update(b'LD24-CTRL-KEY-v1') + encryptor.finalize()
            cmac = CMAC(algorithms.AES(command_key))
            cmac.update(frame[9:22])
            assert cmac.finalize()[:8] == frame[22:]
            # Only the in-range endpoint generates the synthetic target feedback.
            broadcast(8195, mode != 2, mode == 1)

        hass.services.async_call = call
        task = asyncio.create_task(entity.async_select_option(option))
        await asyncio.sleep(0)
        assert entity.current_option == option
        broadcast(8194, mode == 2, mode == 2)
        await asyncio.wait_for(task, 1)
        assert len(calls) == 1 and value.frames.mode == mode
        assert value._last_sender_action == ('esphome', names[2])
        assert entity.current_option == option and entity.available
        assert value._requested_mode is None and value.frames._parser is None
        assert entity.written_states[-1] == (option, True)
        value.stop()
        entity.cancel_listener()

    monkeypatch.setattr(manager_module, 'ESP_ACTION_TIME', 0)
    asyncio.run(scenario())
