"""Exercise sender discovery with real HA scanner display-name formatting."""

from types import SimpleNamespace
import asyncio
import logging
import time

from bluetooth_adapters import adapter_human_name
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.cmac import CMAC
import pytest

from conftest import bluetooth, manager_module, select_module
from test_mode_feedback import ADDRESS, KEY, advertisement, feed, manager


def sender(name, source):
    return SimpleNamespace(
        adapter=name, source=source, name=adapter_human_name(name, source),
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


def test_sender_prefers_authenticated_source_then_strongest_receiver(monkeypatch):
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
    assert value._async_resolve_action() == ('esphome', names[2])
    value._configured_action = ['esphome', 'removed_ld2401_control_broadcast']
    assert value._async_resolve_action() == ('esphome', names[2])


def test_unmatched_receivers_log_fallback_and_feedback_timeout(monkeypatch, caplog):
    value, hass, _ = manager()
    services(hass, ['a_far_ld2401_control_broadcast', 'z_far_ld2401_control_broadcast'])
    monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address', lambda *_args: [])
    with caplog.at_level(logging.WARNING):
        action = value._async_resolve_action()
        assert action == ('esphome', 'a_far_ld2401_control_broadcast')
        feed(value, 8193)
        value._requested_mode = 1
        value._request_counter = 8193
        value._request_action = action
        value._request_deadline = time.monotonic() - 1
        feed(value, 8194)
        value._runtime_tick(None)
    assert value.mode == 2
    assert 'using fallback action esphome.a_far_' in caplog.text
    assert caplog.text.count('OUT mode feedback did not converge') == 1
    assert 'requested=1 observed=2' in caplog.text
    assert KEY.hex() not in caplog.text


@pytest.mark.parametrize('option,mode', [('hold_low', 0), ('hold_high', 1), ('auto', 2)])
def test_select_entity_routes_authenticated_command_and_consumes_feedback(monkeypatch, option, mode):
    async def scenario():
        value, hass, owner = manager()
        names = [f'{name}_ld2401_control_broadcast' for name in ('a_far', 'm_far', 'z_near')]
        services(hass, names)
        near = sender('z-near', '02:00:00:00:10:01')
        monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address',
                            lambda *_args: [SimpleNamespace(scanner=near, advertisement=SimpleNamespace(rssi=-40))])
        value._ensure_shared()
        entity = select_module.LD2401OutModeSelect(value)
        entity.written_states = []
        await entity.async_added_to_hass()

        def broadcast(count, hold, level):
            info = advertisement(count, hold, level)
            info.source = near.source
            value._async_handle_advertisement(info, None)
            owner._process_update(owner.device_data.update(info))

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
        assert entity.current_option == option and entity.available
        assert value._requested_mode is None and value.frames._parser is None
        assert entity.written_states[-1] == (option, True)
        value.stop()
        entity.cancel_listener()

    monkeypatch.setattr(manager_module, 'ESP_ACTION_TIME', 0)
    asyncio.run(scenario())
