"""Drive the HA OUT-mode select entity and verify the module really changed.

This is the real-instance round trip that no offline test can cover:

    Home Assistant service call -> integration -> ESPHome broadcast -> firmware OUT
                                                                          |
    HA entity state  <-  integration feedback  <-  encrypted BTHome frame <-+

For each requested mode the tool records the HA state before/after the call, the
mode reported right after the call (optimistic selection), the module's decrypted
`hold`/`out_high` from the air, and the settled HA state once the integration's
setting window has passed.  Disagreements are reported instead of hidden.

Credentials and the module Bindkey stay local: `--token-file` is the two-line HA
file and `--key-file` is the local Bindkey file.

    python -B Tester/tools/ha_out_test.py --token-file local/ha-token.txt --insecure \
        --entity select.ld2401_09fb_out_mode --mac 02:00:00:00:00:01 \
        --key-file local/bindkey.txt --proxy-host <node> --apikey-file local/esphome.key
"""
import argparse
import asyncio
import json
from pathlib import Path
import ssl
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_ble_proxy import capture as proxy_capture          # noqa: E402
from decode_capture import decode_frame, read_key               # noqa: E402

BTHOME_UUID = '0000fcd2-0000-1000-8000-00805f9b34fb'
EXPECTED = {
    'auto': (0, None),        # hold must be 0; level is whatever the radar drives
    'hold_low': (1, 0),
    'hold_high': (1, 1),
}


class HA:
    def __init__(self, base, token, verify):
        self.base = base.rstrip('/')
        self.token = token
        self.ssl = None if verify else ssl._create_unverified_context()

    async def state(self, session, entity_id):
        async with session.get(self.base + '/api/states/' + entity_id,
                               headers={'Authorization': 'Bearer ' + self.token},
                               ssl=self.ssl) as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            return await response.json()

    async def call_select(self, session, entity_id, option):
        payload = {'entity_id': entity_id, 'option': option}
        async with session.post(self.base + '/api/services/select/select_option',
                                headers={'Authorization': 'Bearer ' + self.token},
                                json=payload, ssl=self.ssl) as response:
            body = await response.text()
            return response.status, body.strip()[:400]

    async def errors(self, session, after):
        """Integration-related log records, for failure diagnosis."""
        async with session.post(self.base + '/api/template',
                                headers={'Authorization': 'Bearer ' + self.token},
                                json={'template': '{{ 1 }}'}, ssl=self.ssl):
            pass
        return []


async def observe(proxy_host, apikey, mac, key, seconds):
    data = await proxy_capture(proxy_host, 6053, apikey, mac, seconds)
    records, errors = [], 0
    for sample in data['samples']:
        hex_data = sample['service_data'].get(BTHOME_UUID)
        if hex_data is None:
            continue
        try:
            record = decode_frame(key, mac, bytes.fromhex(hex_data))
        except Exception:                                       # noqa: BLE001
            errors += 1
            continue
        records.append(record)
    settled = records[-1]['fields'] if records else None
    return dict(frames=len(records), mic_errors=errors, settled=settled,
                pairs=sorted({(r['fields'].get('hold'), r['fields'].get('out_high'))
                              for r in records}))


async def main(args):
    import aiohttp
    lines = [line.strip() for line in Path(args.token_file).read_text(encoding='utf-8').splitlines()
             if line.strip() and not line.startswith('#')]
    base, token = lines[0], lines[1]
    key = read_key(args.key_file)
    apikey = Path(args.apikey_file).read_text(encoding='utf-8').strip()
    ha = HA(base, token, verify=not args.insecure)

    rows = []
    async with aiohttp.ClientSession() as session:
        before = await ha.state(session, args.entity)
        if before is None:
            print('entity %s does not exist on this instance' % args.entity)
            return 2
        print('entity    %s' % args.entity)
        print('state     %s (available=%s)' % (before['state'], before['state'] != 'unavailable'))
        print('options   %s' % before['attributes'].get('options'))
        for option in args.modes:
            print('\n=== select_option %s ===' % option)
            base_air = await observe(args.proxy_host, apikey, args.mac, key, args.baseline)
            print('  before: HA=%-9s air hold/out=%s'
                  % (before['state'], (base_air['settled'] or {}).get('hold')))
            moment = time.monotonic()
            status, body = await ha.call_select(session, args.entity, option)
            print('  service call: HTTP %s %s' % (status, body if status >= 400 else ''))
            immediate = await ha.state(session, args.entity)
            print('  right after call: HA=%s (%.2fs)' % (immediate['state'], time.monotonic() - moment))
            air = await observe(args.proxy_host, apikey, args.mac, key, args.settle)
            settled_state = await ha.state(session, args.entity)
            hold, level = EXPECTED[option]
            air_hold = (air['settled'] or {}).get('hold')
            air_level = (air['settled'] or {}).get('out_high')
            ok_air = air_hold == hold and (level is None or air_level == level)
            ok_ha = settled_state['state'] == option
            print('  after:  HA=%-9s air hold=%s out=%s frames=%d mic_errors=%d'
                  % (settled_state['state'], air_hold, air_level, air['frames'], air['mic_errors']))
            print('  verdict: air=%s ha=%s' % (
                'OK' if ok_air else 'MISMATCH', 'OK' if ok_ha else 'MISMATCH'))
            rows.append(dict(option=option, http=status, before=before['state'],
                             immediate=immediate['state'], settled=settled_state['state'],
                             air_hold=air_hold, air_level=air_level,
                             air_pairs=air['pairs'], frames=air['frames'],
                             mic_errors=air['mic_errors'],
                             ok=bool(ok_air and ok_ha)))
            before = settled_state

    out = args.json or Path('local/ha-out-test.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    passed = sum(1 for row in rows if row['ok'])
    print('\n%d/%d modes matched (written %s)' % (passed, len(rows), out))
    return 0 if passed == len(rows) else 1


def main_cli():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--token-file', type=Path, default=Path('local/ha-token.txt'))
    ap.add_argument('--insecure', action='store_true')
    ap.add_argument('--entity', required=True)
    ap.add_argument('--mac', required=True)
    ap.add_argument('--key-file', type=Path, required=True)
    ap.add_argument('--proxy-host', required=True, help='ESPHome BLE proxy used for observation')
    ap.add_argument('--apikey-file', type=Path, required=True)
    ap.add_argument('--modes', nargs='+', default=['hold_low', 'hold_high', 'auto'])
    ap.add_argument('--baseline', type=float, default=8.0, help='seconds observed before each call')
    ap.add_argument('--settle', type=float, default=14.0, help='seconds observed after each call')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    return asyncio.run(main(args))


if __name__ == '__main__':
    sys.exit(main_cli())