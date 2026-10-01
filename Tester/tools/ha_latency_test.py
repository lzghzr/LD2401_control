"""Measure the live latency of an OUT mode command through Home Assistant.

Reports the intervals that answer different questions:

  * ``ack``    - the service call returns.  This is what an automation waits for:
                 the counter wait plus the ESPHome dispatch;
  * ``air``    - the module's decrypted broadcast first shows the *new* mode pair.
                 This is how long the physical OUT actually took;
  * ``stable`` - the entity still shows the requested option once the settling
                 window has passed.  A revert means the command did not converge,
                 which is how a failed send shows up.

Two details keep the numbers honest:

  * ``hold_low`` and ``hold_high`` both report ``hold=1``, so the target is the
    ``(hold, out_high)`` pair, never ``hold`` alone;
  * each iteration requests the mode *opposite* to the module's current on-air
    pair, so a matching frame proves a change rather than a coincidence.

The BLE observation uses an ESPHome proxy and runs continuously, so ``air`` is
timed from the same clock as the service call.

Credentials stay local: ``--token-file`` is the two-line HA credential file and
``--key-file`` is the module Bindkey file.

    python -B Tester/tools/ha_latency_test.py --token-file local/ha-token.txt --insecure \
        --entity select.ld2401_<short>_out_mode --mac 02:00:00:00:00:01 \
        --key-file local/bindkey.txt --proxy-host <node> --apikey-file local/esphome.key \
        --iterations 10 --json local/latency.json
"""
import argparse
import asyncio
import json
from pathlib import Path
import statistics
import ssl
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_ble_proxy import mac_from_int, sample_from_raw          # noqa: E402
from decode_capture import decode_frame, read_key                    # noqa: E402

BTHOME_UUID = '0000fcd2-0000-1000-8000-00805f9b34fb'
# Target (hold, out_high) pairs; None means "any level".
TARGET = {'hold_low': (1, 0), 'hold_high': (1, 1), 'auto': (0, None)}
OPTION_FOR = {(1, 0): 'hold_high', (1, 1): 'hold_low', (0, None): 'hold_low'}


class Observer:
    """Continuous decrypted view of the module's broadcasts."""

    def __init__(self):
        self.frames = []          # (wall time, hold, out_high)

    def add(self, when, fields):
        if fields is not None and 'hold' in fields:
            self.frames.append((when, fields.get('hold'), fields.get('out_high')))

    def last_pair(self):
        for _when, hold, level in reversed(self.frames):
            return (hold, level)
        return None

    def pair_before(self, start):
        for when, hold, level in reversed(self.frames):
            if when <= start:
                return (hold, level)
        return None

    def first_target_after(self, start, target):
        hold, level = target
        for when, seen_hold, seen_level in self.frames:
            if when > start and seen_hold == hold and (level is None or seen_level == level):
                return when
        return None


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


async def main(args):
    import aiohttp
    from aioesphomeapi import APIClient

    lines = [l.strip() for l in Path(args.token_file).read_text(encoding='utf-8').splitlines()
             if l.strip() and not l.startswith('#')]
    base, token = lines[0], lines[1]
    headers = {'Authorization': 'Bearer ' + token}
    ctx = None if not args.insecure else ssl._create_unverified_context()
    key = read_key(args.key_file)
    apikey = Path(args.apikey_file).read_text(encoding='utf-8').strip()
    mac = args.mac.upper()

    observer = Observer()
    client = APIClient(args.proxy_host, args.port, None, noise_psk=apikey)
    await client.connect(login=True)

    def on_raw(response):
        for item in response.advertisements:
            if mac_from_int(item.address) != mac:
                continue
            sample = sample_from_raw(item.address, item.rssi, item.address_type,
                                     bytes(item.data))
            hex_data = sample['service_data'].get(BTHOME_UUID)
            if hex_data is None:
                continue
            try:
                record = decode_frame(key, mac, bytes.fromhex(hex_data))
            except Exception:                                        # noqa: BLE001
                continue
            observer.add(sample['time'], record['fields'])

    unsubscribe = client.subscribe_bluetooth_le_raw_advertisements(on_raw)
    rows = []
    try:
        async with aiohttp.ClientSession() as session:
            async def state():
                async with session.get(base + '/api/states/' + args.entity,
                                       headers=headers, ssl=ctx) as response:
                    response.raise_for_status()
                    return (await response.json())['state']

            async def select(option):
                async with session.post(base + '/api/services/select/select_option',
                                        headers=headers, ssl=ctx,
                                        json={'entity_id': args.entity, 'option': option}) as resp:
                    return resp.status, (await resp.text()).strip()[:120]

            await asyncio.sleep(args.warmup)
            for index in range(args.iterations):
                await asyncio.sleep(args.gap)
                current = observer.last_pair()
                if current is None:
                    rows.append(dict(iteration=index + 1, skipped='no observed frames'))
                    print('#%-2d skipped: no observed frames' % (index + 1))
                    continue
                option = OPTION_FOR.get((current[0], current[1]), 'hold_low')
                target = TARGET[option]
                before = await state()
                start = time.time()
                status, body = await select(option)
                ack = time.time() - start
                # The call can return before the frame has reached the module, so
                # the air change has to be awaited rather than read once.
                air_at = None
                air_deadline = time.monotonic() + args.air_timeout
                while time.monotonic() < air_deadline:
                    air_at = observer.first_target_after(start, target)
                    if air_at is not None:
                        break
                    await asyncio.sleep(0.2)
                air = None if air_at is None else air_at - start

                # The optimistic state equals the option at once; what matters is
                # whether it survives the settling window.
                await asyncio.sleep(args.settle)
                settled = await state()
                rows.append(dict(iteration=index + 1, option=option, air_before=list(current),
                                 entity_before=before, http=status, ack=round(ack, 3),
                                 air=None if air is None else round(air, 3),
                                 entity_after=settled, stable=settled == option))
                print('#%-2d %-10s air_before=%-10s http=%s  ack=%5.2fs  air=%-7s stable=%s'
                      % (index + 1, option, '%s/%s' % current, status, ack,
                         'n/a' if air is None else '%.2fs' % air, settled == option))
                if status != 200:
                    print('      service error: %s' % body)
    finally:
        unsubscribe()
        await client.disconnect()

    acknowledged = [r for r in rows if r.get('http') == 200]
    usable = [r for r in acknowledged if r['air'] is not None]
    summary = {
        'iterations': len(rows),
        'acknowledged': len(acknowledged),
        'stable': sum(1 for r in acknowledged if r['stable']),
        'ack_seconds': [r['ack'] for r in acknowledged],
        'air_seconds': [r['air'] for r in usable],
    }
    print()
    for label, values in (('ack', summary['ack_seconds']), ('air', summary['air_seconds'])):
        if values:
            print('%-5s n=%-3d min=%.2f median=%.2f p90=%.2f max=%.2f'
                  % (label, len(values), min(values), statistics.median(values),
                     percentile(values, 0.9), max(values)))
        else:
            print('%-5s no samples' % label)
    print('acknowledged %d/%d, stable after settle %d/%d'
          % (summary['acknowledged'], summary['iterations'],
             summary['stable'], summary['acknowledged']))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(dict(rows=rows, summary=summary),
                                        ensure_ascii=False, indent=2), encoding='utf-8')
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
    ap.add_argument('--iterations', type=int, default=10)
    ap.add_argument('--warmup', type=float, default=8.0, help='seconds of BLE observation first')
    ap.add_argument('--gap', type=float, default=3.0, help='seconds between selections')
    ap.add_argument('--settle', type=float, default=8.0,
                    help='seconds after the call before judging the entity')
    ap.add_argument('--air-timeout', type=float, default=10.0,
                    help='seconds to wait for the on-air change after the call')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    return asyncio.run(main(args))


if __name__ == '__main__':
    sys.exit(main_cli())