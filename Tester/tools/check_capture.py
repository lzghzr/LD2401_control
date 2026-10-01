"""Verify capture decoding and sender tool paths with synthetic public fixtures.

Fixtures follow the firmware plaintext layouts exactly: 13 bytes on 26092430 and
the 11/15-byte layouts that 26092431 emits once the 0x0F manual-hold object is
inserted ahead of 0x10.  The 31-byte legacy AD limit is checked on the wire frame.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from capture_ble import BTHOME_UUID
from control_frame import latest_counter
from decode_capture import OBJECTS, counter_timeline, decode_frame, decode_records

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# counter parity selects the layout; the trailing 0x0F insert position follows.
PLAINTEXTS = {
    # 26092430 reference: 13 bytes, no 0x0F.
    'legacy-even': ('050001000c800c100121012301', 8192),
    'legacy-odd': ('05000100100021002300402c01', 8193),
    # 26092431 with a radar snapshot: 15 bytes, 0x0F ahead of 0x10.
    'status-even': ('050001000c800c0f01100121012301', 8192),
    'status-odd': ('050001000f00100121012301402c01', 8193),
    # 26092431 without a snapshot: 11 bytes, voltage stays continuous.
    'status-nosnap': ('050001000c800c0f001001', 8194),
}


def object_ids(plain):
    """Walk a plaintext with the decoder's table and return the object-id sequence."""
    ids, at = [], 0
    while at < len(plain):
        ident = plain[at]
        assert ident in OBJECTS, 'unknown object 0x%02x at %d' % (ident, at)
        ids.append(ident)
        at += 1 + OBJECTS[ident][1]
    assert at == len(plain), 'objects overrun the plaintext'
    return ids


def wire_frame(key, mac, plain_hex, counter):
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
    count = counter.to_bytes(4, 'little')
    nonce = bytes.fromhex(mac.replace(':', '')) + bytes.fromhex('d2fc41') + count
    encrypted = AESCCM(key, tag_length=4).encrypt(nonce, bytes.fromhex(plain_hex), None)
    return b'\x41' + encrypted[:-4] + count + encrypted[-4:]


def main():
    from cryptography.exceptions import InvalidTag
    if not __debug__:
        raise SystemExit('Run without -O')
    key, mac = bytes(range(16)), '02:00:00:00:00:01'
    frames = {name: wire_frame(key, mac, plain, counter)
              for name, (plain, counter) in PLAINTEXTS.items()}
    for name, (plain_hex, counter) in PLAINTEXTS.items():
        plain = bytes.fromhex(plain_hex)
        ids = object_ids(plain)
        assert ids == sorted(ids) and len(set(ids)) == len(ids), \
            '%s object order not ascending: %s' % (name, ids)
        assert len(frames[name]) == len(plain) + 9, '%s service data length' % name
        decoded = decode_frame(key, mac, frames[name])
        assert decoded['counter'] == counter and decoded['plaintext'] == plain_hex, name
        assert decoded['plaintext_bytes'] == len(plain) and decoded['expected_length'], name

    # 26092430 reference frames keep decoding unchanged.
    assert decode_frame(key, mac, frames['legacy-even'])['fields'] == dict(
        illuminance_lx=2.56, voltage_v=3.2, out_high=1, motion=1, occupancy=1)
    assert decode_frame(key, mac, frames['legacy-odd'])['fields']['distance_mm'] == 300
    assert 'hold' not in decode_frame(key, mac, frames['legacy-even'])['fields']

    # 26092431 frames carry the hold flag next to the sampled OUT level.
    even = decode_frame(key, mac, frames['status-even'])['fields']
    assert even == dict(illuminance_lx=2.56, voltage_v=3.2, hold=1, out_high=1,
                        motion=1, occupancy=1), even
    odd = decode_frame(key, mac, frames['status-odd'])['fields']
    assert odd == dict(illuminance_lx=2.56, hold=0, out_high=1, motion=1,
                       occupancy=1, distance_mm=300), odd
    nosnap = decode_frame(key, mac, frames['status-nosnap'])['fields']
    assert nosnap == dict(illuminance_lx=2.56, voltage_v=3.2, hold=0, out_high=1), nosnap

    # The whole legacy advertisement, Flags included, must stay within 31 bytes.
    assert object_ids(bytes.fromhex(PLAINTEXTS['status-even'][0])).count(0x0F) == 1
    assert len(frames['status-even']) + 7 == 31, '15-byte plaintext is not a 31-byte AD'
    assert len(frames['legacy-even']) + 7 == 29, '13-byte plaintext is not a 29-byte AD'

    try:
        decode_frame(key, mac, frames['status-even'][:-1] + bytes([frames['status-even'][-1] ^ 1]))
    except InvalidTag:
        pass
    else:
        raise AssertionError('invalid MIC accepted')

    sample = dict(address=mac, time=1000, rssi=-60,
                  service_data={BTHOME_UUID: frames['status-even'].hex()})
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

    # The counter delta is the transmit cadence even when the host drops reports.
    late = wire_frame(key, mac, PLAINTEXTS['status-even'][0], 8204)
    timeline_capture = dict(schema=1, address=mac, started=1000, ended=1007, samples=[
        sample,
        dict(sample, time=1000.004),
        dict(address=mac, time=1006, rssi=-60, service_data={BTHOME_UUID: late.hex()}),
    ])
    records, timeline_errors = decode_records(timeline_capture, key, mac)
    assert not timeline_errors
    assert counter_timeline(records) == dict(unique_frames=2, span_seconds=6,
                                             counter_delta=12, counter_rate_hz=2.0,
                                             counter_monotonic=True,
                                             max_report_gap_seconds=6)
    assert counter_timeline([dict(counter=10, time=1), dict(counter=9, time=2)])[
        'counter_monotonic'] is False
    assert counter_timeline([dict(counter=10, time=1)]) is None
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
    print('PASS: Tester %d plaintext layouts, MIC rejection, freshness, offline CLI fixtures'
          % len(PLAINTEXTS))


if __name__ == '__main__':
    main()