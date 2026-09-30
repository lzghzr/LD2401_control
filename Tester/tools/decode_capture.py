"""Authenticate and decode LD2401 encrypted BTHome captures, offline."""
import argparse
import json
from pathlib import Path

from capture_ble import BTHOME_UUID, address

OBJECTS = {
    0x05: ('illuminance_lx', 3, 100),
    0x0C: ('voltage_v', 2, 1000),
    0x10: ('out_high', 1, 1),
    0x21: ('motion', 1, 1),
    0x23: ('occupancy', 1, 1),
    0x40: ('distance_mm', 2, 1),
}


def read_key(path):
    key = bytes.fromhex(Path(path).read_text(encoding='utf-8').strip())
    if len(key) != 16:
        raise ValueError('key file must contain exactly 32 hexadecimal characters')
    return key


def decode_frame(key, mac, service_data):
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
    data = bytes(service_data)
    if len(key) != 16 or len(data) < 11 or data[0] != 0x41:
        raise ValueError('expected encrypted BTHome v2 data (41) and a 16-byte key')
    count_bytes = data[-8:-4]
    nonce = bytes.fromhex(address(mac).replace(':', '')) + bytes.fromhex('d2fc41') + count_bytes
    plain = AESCCM(key, tag_length=4).decrypt(nonce, data[1:-8] + data[-4:], None)
    fields = {}
    at = 0
    while at < len(plain):
        ident = plain[at]
        if ident not in OBJECTS:
            raise ValueError('unsupported object 0x%02x at plaintext offset %d' % (ident, at))
        name, width, scale = OBJECTS[ident]
        end = at + 1 + width
        if end > len(plain):
            raise ValueError('truncated object 0x%02x' % ident)
        if name in fields:
            raise ValueError('duplicate object 0x%02x' % ident)
        value = int.from_bytes(plain[at + 1:end], 'little')
        fields[name] = value / scale if scale != 1 else value
        at = end
    return dict(counter=int.from_bytes(count_bytes, 'little'), fields=fields,
                plaintext=plain.hex())


def decode_records(capture, key, mac):
    """Return authenticated samples and per-sample errors; never trust failed MICs."""
    valid, errors = [], []
    for index, sample in enumerate(capture['samples']):
        if sample.get('address', '').upper() != mac:
            continue
        hex_data = sample.get('service_data', {}).get(BTHOME_UUID)
        if hex_data is None:
            continue
        try:
            record = decode_frame(key, mac, bytes.fromhex(hex_data))
            record.update(time=sample['time'], rssi=sample.get('rssi'))
            valid.append(record)
        except Exception as exc:
            errors.append(dict(index=index, error=type(exc).__name__))
    return valid, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--capture', type=Path, required=True)
    ap.add_argument('--key-file', type=Path, required=True, help='local 32-hex Bindkey file')
    ap.add_argument('--mac', type=address, help='default: capture address')
    ap.add_argument('--output', type=Path, help='new local decoded JSON file; otherwise stdout')
    args = ap.parse_args()
    captured = json.loads(args.capture.read_text(encoding='utf-8'))
    mac = args.mac or address(captured['address'])
    valid, errors = decode_records(captured, read_key(args.key_file), mac)
    unique = {record['counter'] for record in valid}
    duration = captured['ended'] - captured['started']
    result = dict(address=mac, authenticated_reports=len(valid), unique_counters=len(unique),
                  duplicate_reports=len(valid) - len(unique), capture_seconds=duration,
                  unique_counter_rate_hz=len(unique) / duration if duration > 0 else None,
                  errors=errors, samples=valid)
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(text)
    else:
        print(text, end='')
    return 0 if valid and not errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
