"""Test whether every dispatched OUT command is accounted for on air.

Two facts make the question decidable without log files:

  * the ESPHome node broadcasts the control frame, whose manufacturer segment
    carries the mode and the counter, and counters increase for every send
    attempt, so decoding those frames yields Home Assistant's real dispatch
    order:

        02 01 06 | 1A FF | D6 05 | 4C 43 | 01 <mac6> <counter LE32> <mode> 00 <tag8>

  * concurrent service calls may be processed in any order, so the order of the
    HTTP requests says nothing about which selection Home Assistant registered
    last.

Two measurement rules keep the numbers honest:

  * each dispatch is broadcast repeatedly, so a round's dispatches are selected
    by *counter novelty* (counters absent from the pre-round set), never by an
    index into a list whose length came from the raw broadcast log;
  * the final state must come from feedback newer than the round's start --
    measured by counter, not by arrival -- otherwise a stale cached frame would
    be counted as this round's result.

    python -B Tester/tools/ha_dispatch_test.py --token-file local/ha-token.txt \
        --entity select.ld2401_<short>_out_mode --mac 02:00:00:00:00:01 \
        --key-file local/bindkey.txt --proxy-host <node> --apikey-file local/esphome.key \
        --rounds 6 --options hold_low hold_high hold_low --sequential
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_ble_proxy import mac_from_int, parse_ad, sample_from_raw   # noqa: E402
from decode_capture import decode_frame, read_key                        # noqa: E402
from ha_probe import HomeAssistant                                       # noqa: E402

COMPANY_ID = 0x05D6
BTHOME_UUID = '0000fcd2-0000-1000-8000-00805f9b34fb'
MODE_NAME = {0: 'hold_low', 1: 'hold_high', 2: 'auto'}
MODE_PAIR = {'hold_low': (1, 0), 'hold_high': (1, 1), 'auto': (0, None)}


def decode_control(payload):
    """Return (target mac, counter, mode) from a control manufacturer segment."""
    if len(payload) < 15 or payload[:2] != b'\x4c\x43' or payload[2] != 0x01:
        return None
    target = ':'.join('%02X' % b for b in payload[3:9])
    return target, int.from_bytes(payload[9:13], 'little'), payload[13]


class Log:
    """Raw broadcast log plus the queries that correct for repetition."""

    def __init__(self):
        self.dispatches = []      # (time, counter, mode, listener); repeats included
        self.feedback = []        # (time, counter, hold, out_high)

    def dispatched(self, when, counter, mode, listener):
        self.dispatches.append((when, counter, mode, listener))

    def fed_back(self, when, counter, fields):
        if 'hold' in fields:
            self.feedback.append((when, counter, fields.get('hold'), fields.get('out_high')))

    def counters(self):
        """Every dispatch counter seen so far (repeats collapse naturally)."""
        return {counter for _when, counter, _mode, _listener in self.dispatches}

    def sequence(self, only=None):
        """Unique dispatches in counter order (== dispatch order).

        ``only`` restricts the result to a set of counters, which is how a round
        collects its own dispatches without an index that could be invalidated by
        repeated broadcasts.
        """
        seen, rows = set(), []
        for when, counter, mode, listener in sorted(self.dispatches, key=lambda r: r[1]):
            if counter in seen:
                continue
            seen.add(counter)
            if only is not None and counter not in only:
                continue
            rows.append(dict(t=round(when, 2), counter=counter, mode=mode,
                             option=MODE_NAME.get(mode, '?'), listener=listener))
        return rows

    def feedback_max_counter(self):
        return max((counter for _w, counter, _h, _o in self.feedback), default=None)

    def final_pair(self, newer_than=None):
        """Newest observed pair as (pair, counter); pair is None when not fresh.

        Feedback with a counter at or below ``newer_than`` predates the round, so
        it cannot serve as this round's result.
        """
        if not self.feedback:
            return None, None
        _when, counter, hold, level = max(self.feedback, key=lambda r: r[1])
        if newer_than is not None and counter <= newer_than:
            return None, counter
        return (hold, level), counter


async def round_once(args, session, ha, headers, log, options, warmup):
    await asyncio.sleep(warmup)
    known_counters = log.counters()
    known_feedback = log.feedback_max_counter()

    async def select(option, index):
        started = time.monotonic()
        async with session.post(ha.base + '/api/services/select/select_option',
                                headers=headers, ssl=ha._ssl(),
                                json={'entity_id': args.entity, 'option': option}) as resp:
            await resp.text()
        return dict(index=index, option=option, http=resp.status,
                    seconds=round(time.monotonic() - started, 3))

    calls = []
    if args.sequential:
        # Sequential requests make the newest registration unambiguous, so the
        # last acknowledged request must be the module's mode if nothing is lost.
        for index, option in enumerate(options):
            calls.append(await select(option, index))
    else:
        calls = await asyncio.gather(*(select(o, i) for i, o in enumerate(options)))
    await asyncio.sleep(args.settle)

    dispatched = log.sequence(only=log.counters() - known_counters)
    final, final_counter = log.final_pair(newer_than=known_feedback)
    fresh = final is not None
    last_dispatch = dispatched[-1] if dispatched else None

    if args.sequential:
        # The reference is the last *acknowledged* selection: a rejected call
        # (HTTP 500, no usable counter) never dispatches, so expecting the module
        # to reach it would be wrong.
        acked = [c for c in sorted(calls, key=lambda c: c['index']) if c['http'] == 200]
        reference = (dict(option=acked[-1]['option'], source='last acknowledged request')
                     if acked else None)
    elif last_dispatch is not None:
        reference = last_dispatch
    else:
        reference = None

    if reference is None or not fresh:
        matched = None
    else:
        expected = MODE_PAIR[reference['option']]
        matched = final[0] == expected[0] and (expected[1] is None or final[1] == expected[1])

    return dict(send_order=[c['option'] for c in sorted(calls, key=lambda c: c['index'])],
                calls=sorted(calls, key=lambda c: c['index']),
                dispatched=dispatched, final=list(final) if final else None,
                final_counter=final_counter, feedback_max_before=known_feedback,
                fresh_feedback=fresh, reference=reference, sequential=bool(args.sequential),
                matches_last_dispatch=matched)


async def main(args):
    import aiohttp
    from aioesphomeapi import APIClient

    lines = [l.strip() for l in Path(args.token_file).read_text(encoding='utf-8').splitlines()
             if l.strip() and not l.startswith('#')]
    ha = HomeAssistant(lines[0], lines[1], verify=False)
    headers = {'Authorization': 'Bearer ' + ha.token}
    key = read_key(args.key_file)
    apikey = Path(args.apikey_file).read_text(encoding='utf-8').strip()
    target_mac = args.mac.upper()
    log = Log()

    def on_raw(response):
        for item in response.advertisements:
            address = mac_from_int(item.address)
            data = bytes(item.data)
            if address == target_mac:
                sample = sample_from_raw(item.address, item.rssi, item.address_type, data)
                hex_data = sample['service_data'].get(BTHOME_UUID)
                if hex_data is not None:
                    try:
                        record = decode_frame(key, target_mac, bytes.fromhex(hex_data))
                    except Exception:                                # noqa: BLE001
                        record = None
                    if record is not None:
                        log.fed_back(sample['time'], record['counter'], record['fields'])
            for payload in parse_ad(data).get(0xff, []):
                if len(payload) >= 2 and int.from_bytes(payload[:2], 'little') == COMPANY_ID:
                    decoded = decode_control(payload[2:])
                    if decoded and decoded[0] == target_mac:
                        log.dispatched(time.time(), decoded[1], decoded[2], 'proxy')

    async def host_scan():
        """Second listener: control frames are broadcast by the sending node, which
        any single observation point may hear only intermittently."""
        from bleak import BleakScanner

        def report(device, adv):
            payload = adv.manufacturer_data.get(COMPANY_ID)
            if payload is None:
                return
            decoded = decode_control(bytes(payload))
            if decoded and decoded[0] == target_mac:
                log.dispatched(time.time(), decoded[1], decoded[2], 'host')

        async with BleakScanner(detection_callback=report, scanning_mode='active'):
            await asyncio.sleep(args.rounds * (args.warmup + args.settle) + 120)

    client = APIClient(args.proxy_host, args.port, None, noise_psk=apikey)
    await client.connect(login=True)
    unsubscribe = client.subscribe_bluetooth_le_raw_advertisements(on_raw)
    host_task = None if args.no_host_scan else asyncio.create_task(host_scan())
    rounds = []
    try:
        async with aiohttp.ClientSession() as session:
            for index in range(args.rounds):
                result = await round_once(args, session, ha, headers, log, args.options,
                                          args.warmup)
                result['round'] = index + 1
                rounds.append(result)
                print('\n=== round %d ===' % (index + 1))
                print('   my send order   : %s' % result['send_order'])
                print('   HA dispatched   : %s'
                      % (' -> '.join('%s(c=%d)' % (d['option'], d['counter'])
                                     for d in result['dispatched']) or '(none observed)'))
                print('   module final    : %s (counter=%s, fresh=%s)'
                      % ('hold=%s out=%s' % tuple(result['final']) if result['final']
                         else 'unknown', result['final_counter'], result['fresh_feedback']))
                print('   reference       : %s' % (result['reference'] or 'none'))
                print('   final == reference mode: %s' % result['matches_last_dispatch'])
    finally:
        unsubscribe()
        if host_task is not None:
            host_task.cancel()
            await asyncio.gather(host_task, return_exceptions=True)
        await client.disconnect()

    matched = sum(1 for r in rounds if r['matches_last_dispatch'] is True)
    decided = sum(1 for r in rounds if r['matches_last_dispatch'] is not None)
    no_dispatch = sum(1 for r in rounds if not r['dispatched'])
    stale = sum(1 for r in rounds if not r['fresh_feedback'])
    print('\nrounds=%d  decided=%d  matched=%d/%d  inconclusive=%d'
          % (len(rounds), decided, matched, decided, len(rounds) - decided))
    print('rounds with no dispatch observed: %d   rounds without fresh feedback: %d'
          % (no_dispatch, stale))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(dict(rounds=rounds), ensure_ascii=False, indent=2),
                             encoding='utf-8')
        print('written', args.json)
    return 0


def main_cli():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--token-file', type=Path, default=Path('local/ha-token.txt'))
    ap.add_argument('--insecure', action='store_true')
    ap.add_argument('--entity', required=True)
    ap.add_argument('--mac', required=True)
    ap.add_argument('--key-file', type=Path, required=True)
    ap.add_argument('--proxy-host', required=True)
    ap.add_argument('--port', type=int, default=6053)
    ap.add_argument('--apikey-file', type=Path, required=True)
    ap.add_argument('--rounds', type=int, default=5)
    ap.add_argument('--options', nargs='+',
                    default=['hold_low', 'hold_high', 'hold_low', 'hold_high'])
    ap.add_argument('--warmup', type=float, default=8.0)
    ap.add_argument('--settle', type=float, default=14.0)
    ap.add_argument('--sequential', action='store_true',
                    help='await each selection so the newest registration is unambiguous')
    ap.add_argument('--no-host-scan', action='store_true',
                    help='observe control frames only through the ESPHome proxy')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    return asyncio.run(main(args))


if __name__ == '__main__':
    sys.exit(main_cli())