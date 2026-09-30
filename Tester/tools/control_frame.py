"""Generate a signed control frame for the ESPHome sender; no device operations."""
import argparse
import json
from pathlib import Path
import sys
import time

from capture_ble import address
from decode_capture import decode_records, read_key

ROOT = Path(__file__).resolve().parents[2]


def latest_counter(capture, key, mac, now):
    valid, _errors = decode_records(capture, key, mac)
    recent = [record for record in valid if 0 <= now - record['time'] <= 50]
    if not recent:
        raise ValueError('no authenticated frame from the last 50 seconds; capture again')
    return max(recent, key=lambda record: record['time'])['counter']


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mac', type=address, required=True)
    ap.add_argument('--key-file', type=Path, required=True)
    ap.add_argument('--mode', type=int, choices=(0, 1, 2), required=True,
                    help='0=low, 1=high, 2=automatic')
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--capture', type=Path, help='use a recent authenticated captured counter')
    group.add_argument('--counter', type=lambda value: int(value, 0),
                       help='explicit counter (decimal or 0x-prefixed); caller verifies freshness')
    args = ap.parse_args()
    key = read_key(args.key_file)
    count = args.counter
    if args.capture:
        captured = json.loads(args.capture.read_text(encoding='utf-8'))
        count = latest_counter(captured, key, args.mac, time.time())
    sys.path.insert(0, str(ROOT / 'Developer/src'))
    from control_protocol import make_control_advertisement
    print(make_control_advertisement(key, args.mac, count, args.mode).hex())


if __name__ == '__main__':
    main()
