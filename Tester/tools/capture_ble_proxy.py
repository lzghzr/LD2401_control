"""Capture one device's BLE reports through an ESPHome BLE proxy, without connecting.

The host adapter may deliver only a fraction of a 500 ms advertisement stream, so
this backend uses a proxy node instead: the node hears the module and forwards the
raw advertising data over its API.  Raw bytes are recorded verbatim as well as
parsed, which is what makes the on-air legacy-AD length measurable (the firmware
targets exactly 31 bytes for the 15-byte plaintext).

Output uses the same schema as `capture_ble.py`, so `decode_capture.py` reads it
unchanged; each sample additionally carries `raw` (the whole AD structure) and
`address_type`.  Node host names and API keys are private: keep them in the
ignored local/ directory.

Scanning mode matters for what this backend can see.  ESPHome's `bluetooth_proxy`
is a **passive** scanner by default (`active: false`): it never sends SCAN_REQ, so
the module's scan response -- where the stock firmware keeps its `HLK-LD24...` name
and the version manufacturer field -- is not observable here and no `ad_bytes` is
inflated by it.  An active proxy does request the scan response, and the node then
appends it to the same raw buffer, so `ad_bytes` covers both sections and the name
appears; use `capture_ble.py` when the advertisement alone is what must be measured.

    python -B Tester/tools/capture_ble_proxy.py --host <node> --apikey-file local/esphome.key \
        --mac 02:00:00:00:00:01 --seconds 30 --output local/capture.json
"""
import argparse
import asyncio
import json
from pathlib import Path
import re
import time
import sys

BTHOME_UUID = '0000fcd2-0000-1000-8000-00805f9b34fb'
PORT = 6053


def address(value):
    value = value.upper()
    if not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', value):
        raise argparse.ArgumentTypeError('expected a six-byte MAC in display order')
    return value


def mac_from_int(value):
    """ESPHome reports the BLE address as a 48-bit integer in display byte order."""
    return ':'.join('%02X' % byte for byte in int(value).to_bytes(6, 'big'))


def parse_ad(data):
    """Split a raw AD structure into {type: [payload...]}."""
    out, at = {}, 0
    while at < len(data):
        length = data[at]
        if length == 0:
            break
        end = at + 1 + length
        if end > len(data):
            break
        kind, payload = data[at + 1], data[at + 2:end]
        out.setdefault(kind, []).append(payload)
        at = end
    return out


def sample_from_raw(address_int, rssi, address_type, data):
    """Build a capture_ble-shaped sample from one raw advertisement."""
    header = parse_ad(data)
    service_data, name = {}, None
    for payload in header.get(0x16, []):
        # The 16-bit UUID is on air in little-endian order: d2 fc == 0xFCD2.
        if payload[:2] == b'\xd2\xfc':
            service_data[BTHOME_UUID] = payload[2:].hex()
    for kind in (0x09, 0x08):
        if header.get(kind):
            name = header[kind][0].decode('utf-8', 'replace')
            break
    return dict(time=time.time(), address=mac_from_int(address_int), name=name,
                rssi=rssi, address_type=address_type,
                service_uuids=[BTHOME_UUID] if service_data else [],
                service_data=service_data, manufacturer_data={},
                raw=data.hex(), ad_bytes=len(data))


async def capture(host, port, apikey, mac, seconds):
    try:
        from aioesphomeapi import APIClient
    except ImportError:
        raise SystemExit('aioesphomeapi is missing: pip install -r Tester/requirements.txt')
    samples = []
    started = time.time()
    client = APIClient(host, port, None, noise_psk=apikey)
    await client.connect(login=True)
    try:
        def on_advertisements(response):
            for item in response.advertisements:
                if mac_from_int(item.address) != mac:
                    continue
                samples.append(sample_from_raw(item.address, item.rssi,
                                               item.address_type, bytes(item.data)))

        unsubscribe = client.subscribe_bluetooth_le_raw_advertisements(on_advertisements)
        await asyncio.sleep(seconds)
        unsubscribe()
    finally:
        await client.disconnect()
    return dict(schema=1, address=mac, started=started, ended=time.time(),
                backend='esphome-ble-proxy', samples=samples)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', required=True, help='ESPHome proxy node host or address')
    ap.add_argument('--port', type=int, default=PORT)
    ap.add_argument('--apikey', help='node API key (prefer --apikey-file)')
    ap.add_argument('--apikey-file', type=Path, help='local file holding the API key')
    ap.add_argument('--mac', type=address, required=True)
    ap.add_argument('--seconds', type=float, default=30)
    ap.add_argument('--output', type=Path, required=True, help='new local capture path')
    args = ap.parse_args()
    if not 0 < args.seconds <= 3600:
        ap.error('--seconds must be in (0, 3600]')
    if args.output.exists():
        ap.error('output already exists; choose a new capture path')
    apikey = args.apikey
    if args.apikey_file:
        apikey = Path(args.apikey_file).read_text(encoding='utf-8').strip()
    if not apikey:
        ap.error('pass --apikey or --apikey-file (local file, never committed)')
    data = asyncio.run(capture(args.host, args.port, apikey, args.mac, args.seconds))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    bthome = sum(BTHOME_UUID in sample['service_data'] for sample in data['samples'])
    unique = len({sample['service_data'][BTHOME_UUID] for sample in data['samples']
                  if BTHOME_UUID in sample['service_data']})
    print('Proxy captured %d reports (%d with BTHome service data, %d distinct): %s'
          % (len(data['samples']), bthome, unique, args.output))
    return 0


if __name__ == '__main__':
    sys.exit(main())