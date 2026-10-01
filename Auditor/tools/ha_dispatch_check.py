"""Independent invariants for the HA command dispatch path.

The Auditor drives the real ``LD2401ControlManager`` through the public
``async_select_mode`` entry with its own stubs and checks observable outcomes:

* no authenticated counter is ever dispatched twice, and counters strictly increase;
* two ESPHome service calls never overlap in time;
* every adjacent pair of dispatches keeps the minimum interval: not less
  (pacing) and not more (no post-send sleep);
* a superseded selection returns quietly and dispatches nothing, and once a
  fresh counter arrives the **latest** selection is the one that is dispatched;
* a counter whose reception predates the startup/key epoch cannot authorize.

Task outcomes are inspected, never swallowed: an exception is a result and is
asserted explicitly. Scanner lookup is bypassed with an explicit action, so this
covers dispatch only; sender selection is checked by ``ha_routing_check.py``.
"""
import argparse
import asyncio
import json
import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import project_root, resolve_input  # noqa: E402
from ha_routing_check import ADDRESS, KEY, action, install_stubs, load_manager  # noqa: E402

ACTION = ('esphome', action('auditor'))
INTERVAL = 0.4          # larger than any scheduling jitter so a doubled gap is visible
WAIT = 0.5              # counter wait window used by the refusal scenario
PACE_TOLERANCE = 0.01   # a dispatch may start a hair before the nominal interval
PACE_MARGIN = 1.5       # a post-send sleep would double the gap


class Recorder:
    """Record service calls and detect overlapping dispatch windows."""

    def __init__(self):
        self.calls = []
        self.overlaps = 0
        self.active = 0

    def services(self):
        async def call(domain, service, data, *, blocking):
            self.active += 1
            self.overlaps += self.active > 1
            try:
                payload = bytes.fromhex(data['payload'])
                self.calls.append(dict(
                    at=time.monotonic(), service=service,
                    counter=int.from_bytes(payload[16:20], 'little'), mode=payload[20]))
                await asyncio.sleep(0)          # yield so overlap would be observable
            finally:
                self.active -= 1

        names = {ACTION[1]}
        return types.SimpleNamespace(
            has_service=lambda domain, name: domain == 'esphome' and name in names,
            async_services_for_domain=lambda _domain: {name: {} for name in names},
            async_call=call,
        )


def manager(coordinator_module, recorder):
    hass = types.SimpleNamespace(services=recorder.services())
    value = coordinator_module.LD2401ControlManager(
        hass, address=ADDRESS, bindkey=KEY, action='', name='Fixture radar')
    value._configured_action = list(ACTION)      # explicit action: no scanner lookup
    return value


def observe(value, counter, mode=2, received=None):
    """Publish one authenticated counter without going through the radio."""
    value.frames.counter = counter
    value.frames.mode = mode
    value._accepted_frame('fixture', received=time.monotonic() if received is None else received)


def outcome(result):
    """Describe a task result so an exception can never pass unnoticed."""
    return 'ok' if result is None else '%s: %s' % (type(result).__name__, result)


async def sequential(coordinator):
    """Four selections, each with a fresh counter: pacing, uniqueness, serialization."""
    recorder = Recorder()
    value = manager(coordinator, recorder)
    value._counter_epoch_started = time.monotonic()
    observe(value, 8193)                           # baseline only
    modes = [0, 1, 2, 0]
    results = []
    for index, mode in enumerate(modes):
        observe(value, 8194 + index)
        results.append(await value.async_select_mode(mode))
    gaps = [round(b['at'] - a['at'], 4) for a, b in zip(recorder.calls, recorder.calls[1:])]
    return recorder, results, gaps, [8194 + index for index in range(len(modes))], modes


async def supersede_then_serve_latest(coordinator):
    """A waits, B supersedes it, a fresh counter must serve the latest selection."""
    latest_mode = 1                                # the second selection is the latest
    latest_observed = latest_mode                  # feedback that confirms it
    recorder = Recorder()
    value = manager(coordinator, recorder)
    value._counter_epoch_started = time.monotonic()
    observe(value, 8193)                           # baseline: not itself usable
    first = asyncio.create_task(value.async_select_mode(0))
    for _ in range(3):
        await asyncio.sleep(0)
    waiting = not first.done()
    second = asyncio.create_task(value.async_select_mode(1))
    for _ in range(3):
        await asyncio.sleep(0)
    superseded_returned = first.done()
    observe(value, 8194)                           # the fresh counter both are waiting for
    results = await asyncio.gather(first, second, return_exceptions=True)
    pending = (value._requested_mode, value._request_counter)
    observe(value, 8195, mode=latest_observed)     # authenticated feedback for the new mode
    return recorder, dict(
        first_was_waiting=waiting,
        superseded_returned_early=superseded_returned,
        first_outcome=outcome(results[0]),
        second_outcome=outcome(results[1]),
        dispatched=[(call['counter'], call['mode']) for call in recorder.calls],
        pending_mode=pending[0],
        pending_counter=pending[1],
        confirmed_mode=value._requested_mode,
        shown_mode=value.mode,
    )


async def pre_epoch(coordinator):
    """A recent but pre-epoch counter must not authorize a command."""
    recorder = Recorder()
    value = manager(coordinator, recorder)
    value._counter_baseline = None
    value._counter_epoch_started = time.monotonic()
    observe(value, 8193, received=time.monotonic() - 10.0)
    available = value.available
    refusal = None
    try:
        await value.async_select_mode(0)
    except Exception as exc:                       # the refusal is inspected, not ignored
        refusal = '%s: %s' % (type(exc).__name__, exc)
    return recorder, available, refusal


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--integration-dir', type=Path,
                    default=Path('custom_components/ld2401_control'))
    ap.add_argument('--expect-fixed', action='store_true')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()

    _bluetooth, _state = install_stubs()
    coordinator = load_manager(args.integration_dir, "ld2401_dispatch_audit")
    coordinator.ESP_ACTION_TIME = INTERVAL
    coordinator.COUNTER_WAIT_TIMEOUT = WAIT
    rows = []

    def add(ident, ok, detail):
        rows.append(dict(id=ident, status='ok' if ok else 'FAIL', detail=detail))

    recorder, results, gaps, want_counters, want_modes = asyncio.run(sequential(coordinator))
    got = [(call['counter'], call['mode']) for call in recorder.calls]
    counters = [call['counter'] for call in recorder.calls]
    expected_pairs = list(zip(want_counters, want_modes))
    add('dispatch.counters_strictly_increase',
        counters == sorted(set(counters)) and counters == want_counters,
        'dispatched %s, expected %s' % (counters, want_counters))
    add('dispatch.mode_matches_selection', got == expected_pairs,
        'dispatched %s, expected %s' % (got, expected_pairs))
    add('dispatch.no_unexpected_exception',
        all(result is None for result in results),
        'task outcomes %s' % [outcome(result) for result in results])
    add('dispatch.no_overlap', recorder.overlaps == 0,
        'overlapping service calls: %d' % recorder.overlaps)
    add('dispatch.interval_each_pair',
        bool(gaps) and all(INTERVAL - PACE_TOLERANCE <= gap <= INTERVAL * PACE_MARGIN
                           for gap in gaps),
        'gaps %s (interval %.2fs, allowed %.2f-%.2fs)'
        % (gaps, INTERVAL, INTERVAL - PACE_TOLERANCE, INTERVAL * PACE_MARGIN))

    racing, info = asyncio.run(supersede_then_serve_latest(coordinator))
    latest_mode = 1                                # the second selection is the latest
    add('dispatch.superseded_sends_nothing',
        info['first_was_waiting'] and info['first_outcome'] == 'ok'
        and len(info['dispatched']) == 1 and info['dispatched'][0][1] == latest_mode,
        'waited=%s superseded outcome=%s dispatched=%s (latest mode %d)'
        % (info['first_was_waiting'], info['first_outcome'], info['dispatched'], latest_mode))
    add('dispatch.latest_selection_is_served',
        info['second_outcome'] == 'ok' and info['dispatched'] == [(8194, latest_mode)]
        and info['pending_mode'] == latest_mode and info['pending_counter'] == 8194,
        'dispatched %s, latest outcome=%s, pending=(%s, %s), superseded returned early=%s'
        % (info['dispatched'], info['second_outcome'], info['pending_mode'],
           info['pending_counter'], info['superseded_returned_early']))
    add('dispatch.latest_selection_confirms',
        info['confirmed_mode'] is None and info['shown_mode'] == latest_mode,
        'after matching feedback pending=%s, shown mode=%s'
        % (info['confirmed_mode'], info['shown_mode']))
    add('dispatch.supersede_no_overlap', racing.overlaps == 0,
        'overlapping service calls: %d' % racing.overlaps)

    pre, available, refusal = asyncio.run(pre_epoch(coordinator))
    add('dispatch.pre_epoch_cannot_authorize',
        available and not pre.calls and refusal is not None
        and refusal.startswith('HomeAssistantError'),
        'mode shown=%s calls=%d refusal=%s' % (available, len(pre.calls), refusal))

    print('dispatch check: %s' % resolve_input(args.integration_dir, project_root(HERE)))
    for row in rows:
        print('  %-4s %-36s %s' % (row['status'], row['id'], row['detail']))
    failed = [row for row in rows if row['status'] == 'FAIL']
    print('\n  %d ok, %d failed' % (len(rows) - len(failed), len(failed)))
    if args.json:
        args.json.write_text(json.dumps(dict(
            integration_dir=str(resolve_input(args.integration_dir, project_root(HERE))),
            checks=rows), ensure_ascii=False, indent=2), encoding='utf-8')
    if args.expect_fixed and failed:
        print('DISPATCH CHECK FAILED: ' + ', '.join(row['id'] for row in failed))
        return 1
    print('DISPATCH CHECK PASSED' if args.expect_fixed else 'DISPATCH CHECKS REPORTED')
    return 0


if __name__ == '__main__':
    sys.exit(main())