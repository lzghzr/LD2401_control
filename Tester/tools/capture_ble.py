"""Capture one device's BLE reports to a local JSON file, without connecting."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import time

BTHOME_UUID = '0000fcd2-0000-1000-8000-00805f9b34fb'


def address(value):
    value = value.upper()
    if not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', value):
        raise argparse.ArgumentTypeError('expected a six-byte MAC in display order')
    return value


async def capture(mac, seconds):
    from bleak import BleakScanner
    samples = []
    started = time.time()

    def report(device, adv):
        if device.address.upper() != mac:
            return
        samples.append(dict(time=time.time(), address=device.address.upper(),
                            name=adv.local_name or device.name, rssi=adv.rssi,
                            service_uuids=adv.service_uuids,
                            service_data={str(k).lower(): v.hex() for k, v in adv.service_data.items()},
                            manufacturer_data={str(k): v.hex() for k, v in adv.manufacturer_data.items()}))

    async with BleakScanner(detection_callback=report, scanning_mode='active'):
        await asyncio.sleep(seconds)
    return dict(schema=1, address=mac, started=started, ended=time.time(), samples=samples)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mac', type=address, required=True)
    ap.add_argument('--seconds', type=float, default=30)
    ap.add_argument('--output', type=Path, required=True, help='new local capture path')
    args = ap.parse_args()
    if not 0 < args.seconds <= 3600:
        ap.error('--seconds must be in (0, 3600]')
    if args.output.exists():
        ap.error('output already exists; choose a new capture path')
    data = asyncio.run(capture(args.mac, args.seconds))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    bthome = sum(BTHOME_UUID in sample['service_data'] for sample in data['samples'])
    print('Captured %d reports (%d with BTHome service data): %s' %
          (len(data['samples']), bthome, args.output))


if __name__ == '__main__':
    main()
