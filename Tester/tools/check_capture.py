"""Verify capture decoding and sender tool paths with synthetic public fixtures."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from capture_ble import BTHOME_UUID
from control_frame import latest_counter
from decode_capture import decode_frame, decode_records

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
    if not __debug__:
        raise SystemExit('Run without -O')
    key, mac = bytes(range(16)), '02:00:00:00:00:01'
    plain = bytes.fromhex('050001000c800c100121012301')
    count = (8192).to_bytes(4, 'little')
    nonce = bytes.fromhex(mac.replace(':', '')) + bytes.fromhex('d2fc41') + count
    encrypted = AESCCM(key, tag_length=4).encrypt(nonce, plain, None)
    frame = b'\x41' + encrypted[:-4] + count + encrypted[-4:]
    decoded = decode_frame(key, mac, frame)
    assert decoded['fields'] == dict(illuminance_lx=2.56, voltage_v=3.2,
                                    out_high=1, motion=1, occupancy=1)
    odd_count = (8193).to_bytes(4, 'little')
    odd_plain = bytes.fromhex('05000100100021002300402c01')
    odd_enc = AESCCM(key, tag_length=4).encrypt(nonce[:-4] + odd_count, odd_plain, None)
    odd = b'\x41' + odd_enc[:-4] + odd_count + odd_enc[-4:]
    assert decode_frame(key, mac, odd)['fields']['distance_mm'] == 300
    try:
        decode_frame(key, mac, frame[:-1] + bytes([frame[-1] ^ 1]))
    except InvalidTag:
        pass
    else:
        raise AssertionError('invalid MIC accepted')
    sample = dict(address=mac, time=1000, rssi=-60, service_data={BTHOME_UUID: frame.hex()})
    capture = dict(schema=1, address=mac, started=999, ended=1001, samples=[sample, sample])
    valid, errors = decode_records(capture, key, mac)
    assert len(valid) == 2 and not errors
    assert latest_counter(capture, key, mac, 1049) == 8192
    for now in (999, 1051):
        try:
            latest_counter(capture, key, mac, now)
        except ValueError:
            pass
        else:
            raise AssertionError('stale/future capture accepted')
    with tempfile.TemporaryDirectory(prefix='tester tools ') as directory:
        folder = Path(directory)
        key_file, capture_file = folder / 'key.txt', folder / 'capture.json'
        key_file.write_text(key.hex(), encoding='utf-8')
        capture_file.write_text(json.dumps(capture), encoding='utf-8')
        subprocess.run([sys.executable, '-B', str(HERE / 'decode_capture.py'), '--capture',
                        str(capture_file), '--key-file', str(key_file)], cwd=directory,
                       check=True, stdout=subprocess.DEVNULL)
        result = subprocess.check_output([sys.executable, '-B', str(HERE / 'control_frame.py'),
                                          '--mac', mac, '--key-file', str(key_file),
                                          '--counter', '8192', '--mode', '1'], cwd=directory,
                                         text=True).strip()
        sys.path.insert(0, str(ROOT / 'Developer/src'))
        from control_protocol import make_control_advertisement
        assert bytes.fromhex(result) == make_control_advertisement(key, mac, 8192, 1)
    print('PASS: Tester even/odd frame decode, MIC rejection, freshness, offline CLI fixtures')


if __name__ == '__main__':
    main()
