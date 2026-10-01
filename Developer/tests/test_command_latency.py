"""Cached command counters and dispatch intervals through the real manager."""

import asyncio
from types import SimpleNamespace

import pytest

from conftest import ConfigEntryState, HomeAssistantError, bluetooth, manager_module
from test_mode_feedback import ADDRESS, KEY, advertisement, feed, manager


def control():
    value, hass, owner = manager()
    calls = []

    async def call(domain, service, data, *, blocking):
        assert domain == 'esphome' and blocking
        calls.append((service, bytes.fromhex(data['payload'])))

    hass.services = SimpleNamespace(
        has_service=lambda *_: True,
        async_services_for_domain=lambda _: {'fixture_ld2401_control_broadcast': {}},
        async_call=call,
    )
    value._configured_action = ['esphome', 'fixture_ld2401_control_broadcast']
    return value, hass, owner, calls


def counter(call):
    return int.from_bytes(call[1][16:20], 'little')


def test_unused_authenticated_cache_returns_without_frame_or_post_send_sleep(monkeypatch):
    async def scenario():
        value, _, _, calls = control()
        feed(value, 8193)
        feed(value, 8194)
        task = asyncio.create_task(value.async_select_mode(1))
        await original_sleep(0)
        assert task.done()  # no additional advertisement or cooldown needed
        await task
        assert len(calls) == 1 and counter(calls[0]) == 8194
        assert value.mode == 1 and value._request_deadline is not None
        feed(value, 8195, 1, 1)
        assert value._requested_mode is None

    original_sleep = asyncio.sleep

    async def unexpected_sleep(_delay):
        raise AssertionError('a first cached send must not sleep')

    monkeypatch.setattr(manager_module.asyncio, 'sleep', unexpected_sleep)
    asyncio.run(scenario())


@pytest.mark.parametrize('elapsed,wait', [(1.5, 0.6), (2.1, 0.0), (3.0, 0.0)])
def test_next_dispatch_waits_only_remaining_interval(monkeypatch, elapsed, wait):
    async def scenario():
        value, _, _, calls = control()
        feed(value, 8193)
        feed(value, 8194)
        await value.async_select_mode(0)
        assert not sleeps and counter(calls[0]) == 8194
        now[0] += elapsed
        feed(value, 8195)
        await value.async_select_mode(1)
        assert sleeps == pytest.approx([wait] if wait else [])
        assert now[0] == pytest.approx(100 + max(elapsed, 2.1))
        assert [counter(call) for call in calls] == [8194, 8195]

    now, sleeps = [100.0], []
    original_sleep = asyncio.sleep

    async def advance(delay):
        sleeps.append(delay)
        now[0] += delay
        await original_sleep(0)

    monkeypatch.setattr(manager_module.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(manager_module.asyncio, 'sleep', advance)
    asyncio.run(scenario())


def test_reload_first_cached_counter_is_only_a_baseline(monkeypatch):
    async def scenario():
        previous, _, _, sent = control()
        feed(previous, 8193)
        feed(previous, 8194)
        await previous.async_select_mode(0)
        assert counter(sent[0]) == 8194
        value, _, _, calls = control()  # HA integration reload loses local send history
        feed(value, 8194)  # replayed HA advertisement already used by the old manager
        task = asyncio.create_task(value.async_select_mode(1))
        await asyncio.sleep(0)
        assert not calls and not task.done()
        feed(value, 8195)
        await task
        assert counter(calls[0]) == 8195

    monkeypatch.setattr(manager_module, 'ESP_ACTION_TIME', 0)
    asyncio.run(scenario())


@pytest.mark.parametrize('shared', [False, True])
def test_actual_reception_age_is_preserved_for_cached_parser_updates(monkeypatch, shared):
    value, hass, owner, _ = control()
    monkeypatch.setattr(manager_module.time, 'monotonic', lambda: 100.0)
    if shared:
        value._ensure_shared()
    else:
        hass.bthome_entry.state = ConfigEntryState.NOT_LOADED
    for count, received in [(8193, 99.0), (8194, 50.0)]:
        info = advertisement(count)
        info.time = received
        if shared:
            owner._process_update(owner.device_data.update(info))
        else:
            value._async_handle_advertisement(info, None)
    assert value.frames.counter == 8194
    assert value._last_received == 50.0 and not value.available
    info = advertisement(8195)
    info.time = 101.0  # a timestamp from another monotonic epoch cannot authorize a send
    if shared:
        owner._process_update(owner.device_data.update(info))
    else:
        value._async_handle_advertisement(info, None)
    assert not value.available


def test_ambiguous_failed_send_consumes_counter_and_retry_needs_new_frame(monkeypatch):
    async def scenario():
        value, hass, _, calls = control()
        feed(value, 8193)
        feed(value, 8194)
        normal_call = hass.services.async_call

        async def fail(*args, **kwargs):
            await normal_call(*args, **kwargs)
            raise HomeAssistantError('Ambiguous transport failure')

        hass.services.async_call = fail
        with pytest.raises(HomeAssistantError, match='Ambiguous'):
            await value.async_select_mode(0)
        hass.services.async_call = normal_call
        with pytest.raises(HomeAssistantError, match='No fresh authenticated'):
            await value.async_select_mode(1)
        assert len(calls) == 1 and value._last_sent_counter == 8194
        feed(value, 8195)
        await value.async_select_mode(1)
        assert [counter(call) for call in calls] == [8194, 8195]

    monkeypatch.setattr(manager_module, 'ESP_ACTION_TIME', 0)
    monkeypatch.setattr(manager_module, 'COUNTER_WAIT_TIMEOUT', 0)
    asyncio.run(scenario())


def test_key_rotation_requires_new_baseline_and_new_key_counter(monkeypatch):
    async def scenario():
        value, hass, _, calls = control()
        feed(value, 50000)
        feed(value, 50001)
        await value.async_select_mode(0)
        other = bytes(range(16, 32))
        hass.bthome_entry.data['bindkey'] = other.hex()
        value._refresh_bindkey()
        assert value._counter_baseline is None and value._last_received is None

        def broadcast(count):
            info = advertisement(count, key=other)
            assert value.frames.update(info)
            value._accepted_frame(info.source, received=info.time)

        broadcast(8193)
        task = asyncio.create_task(value.async_select_mode(1))
        await asyncio.sleep(0)
        assert len(calls) == 1 and not task.done()
        broadcast(8194)
        await task
        assert calls[1][1] == manager_module.make_control_frame(other, ADDRESS, 8194, 1)

    monkeypatch.setattr(manager_module, 'ESP_ACTION_TIME', 0)
    asyncio.run(scenario())


def test_counter_is_rechecked_after_cooldown_and_sender_is_resolved_at_dispatch(monkeypatch):
    async def scenario():
        value, hass, _, calls = control()
        now[0] = 100.0
        value._configured_action = None
        hass.services.async_services_for_domain = lambda _: {
            f'{name}_ld2401_control_broadcast': {} for name in ('near_a', 'near_b')
        }
        feed(value, 8193)
        feed(value, 8194)
        await value.async_select_mode(0)
        assert calls[0][0] == 'near_a_ld2401_control_broadcast'
        now[0] = 101.5
        feed(value, 8195)
        value._last_received = now[0] - 44.8  # expires during the remaining cooldown
        with pytest.raises(HomeAssistantError, match='No fresh authenticated'):
            await value.async_select_mode(1)
        assert len(calls) == 1 and len(lookups) == 1
        feed(value, 8196)
        await value.async_select_mode(1)
        assert counter(calls[1]) == 8196
        assert calls[1][0] == 'near_b_ld2401_control_broadcast'
        assert len(lookups) == 2

    now, lookups, current_node = [50.0], [], ['near_a']
    original_sleep = asyncio.sleep

    async def advance(delay):
        now[0] += delay
        current_node[0] = 'near_b'
        await original_sleep(0)

    def receivers(*_args):
        lookups.append(now[0])
        scanner = SimpleNamespace(
            adapter=current_node[0], name=current_node[0], source='fixture',
            discovered_device_timestamps={ADDRESS: now[0]},
        )
        return [SimpleNamespace(scanner=scanner, advertisement=SimpleNamespace(rssi=-40))]

    monkeypatch.setattr(manager_module.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(manager_module.asyncio, 'sleep', advance)
    monkeypatch.setattr(manager_module, 'COUNTER_WAIT_TIMEOUT', 0)
    monkeypatch.setattr(bluetooth, 'async_scanner_devices_by_address', receivers)
    asyncio.run(scenario())


def test_multiple_pre_start_cached_updates_cannot_enable_fast_send(monkeypatch):
    async def scenario():
        value, _, owner, calls = control()
        value._ensure_shared()
        for count, received in [(8193, 90.0), (8194, 99.0)]:
            info = advertisement(count)
            info.time = received
            owner._process_update(owner.device_data.update(info))
        assert value.available  # recent observed mode, but no post-start counter yet
        task = asyncio.create_task(value.async_select_mode(1))
        await asyncio.sleep(0)
        assert not calls and not task.done()
        now[0] += 0.1
        info = advertisement(8195)
        owner._process_update(owner.device_data.update(info))
        await task
        assert counter(calls[0]) == 8195

    now = [100.0]
    monkeypatch.setattr(manager_module.time, 'monotonic', lambda: now[0])
    asyncio.run(scenario())


def test_new_selection_wakes_superseded_counter_wait(monkeypatch):
    async def scenario():
        value, _, _, calls = control()
        feed(value, 8193)
        old = asyncio.create_task(value.async_select_mode(0))
        await asyncio.sleep(0)
        latest = asyncio.create_task(value.async_select_mode(1))
        await asyncio.wait_for(old, 0.5)
        assert not calls
        feed(value, 8194)
        await old
        await latest
        assert len(calls) == 1 and calls[0][1][20] == 1

    monkeypatch.setattr(manager_module, 'ESP_ACTION_TIME', 0)
    asyncio.run(scenario())


def test_key_change_during_interval_wait_aborts_old_key_command(monkeypatch):
    async def scenario():
        value, hass, _, calls = control()
        active_hass[0] = hass
        feed(value, 8193)
        feed(value, 8194)
        await value.async_select_mode(0)
        now[0] = 101.5
        feed(value, 8195)
        with pytest.raises(HomeAssistantError, match='Bindkey changed'):
            await value.async_select_mode(1)
        assert len(calls) == 1 and value._counter_baseline is None
        assert value._requested_mode is None and not value.available

    now, active_hass = [100.0], [None]
    original_sleep = asyncio.sleep

    async def advance(delay):
        now[0] += delay
        active_hass[0].bthome_entry.data['bindkey'] = bytes(range(16, 32)).hex()
        await original_sleep(0)

    monkeypatch.setattr(manager_module.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(manager_module.asyncio, 'sleep', advance)
    asyncio.run(scenario())
