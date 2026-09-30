"""Talk to the module over the UART configuration protocol.

Examples (run it from wherever this file sits):
  python -B a6.py --version            # 0xA0 build stamp (the version criterion)
  python -B a6.py --read-key           # A6 param 3: the persisted BTHome bindkey
  python -B a6.py --rotate-key         # A6 param 4: generate, persist, return a new key
  python -B a6.py --out 1              # A6 param 1: hold OUT high (0 low, 2 release)
  python -B a6.py --param 3            # any A6 parameter
  python -B a6.py --raw 6000           # any command word
  python -B a6.py --self-test          # frame bytes only, no port touched

The run opens the configuration session (0x00FF) and closes it again (0x00FE) unless
--keep-session is given: while the session is open the module suppresses its own UART
reporting, so leaving it open also silences the radar stream.  Nothing else is written.
"""
import argparse
import sys
import time
from pathlib import Path

HEAD = bytes.fromhex('fdfcfbfa')
TAIL = bytes.fromhex('04030201')

ENTER_CMD, ENTER_VAL = 'ff00', '0100'     # 0x00FF: open the configuration session (idempotent)
LEAVE_CMD, LEAVE_VAL = 'fe00', ''         # 0x00FE: close it
A6 = 'a600'
KEY_PARAM = '0300'          # A6 parameter 3: read the persisted bindkey
ROTATE_PARAM = '0400'       # A6 parameter 4: generate and persist a new bindkey


def frame(cmd_hex, value_hex=''):
    body = bytes.fromhex(cmd_hex) + bytes.fromhex(value_hex)
    return HEAD + len(body).to_bytes(2, 'little') + body + TAIL


def split_frames(data):
    """Return [(frame_hex, payload_bytes)] for every well-formed protocol frame in data."""
    out, i = [], 0
    while True:
        j = data.find(HEAD, i)
        if j < 0:
            return out
        i = j + 1
        if j + 6 > len(data):
            return out
        n = int.from_bytes(data[j + 4:j + 6], 'little')
        if n > 64 or j + 6 + n + 4 > len(data):
            continue
        out.append((data[j:j + 6 + n + 4].hex(), data[j + 6:j + 6 + n]))


def collect(port, seconds):
    """Read until the deadline; also report when the first byte arrived (reply latency)."""
    end = time.time() + seconds
    buf = bytearray()
    first = None
    while time.time() < end:
        chunk = port.read(4096)
        if chunk:
            if first is None:
                first = time.time()
            buf.extend(chunk)
    return bytes(buf), first


def send(port, cmd_hex, value_hex='', wait=0.8, window=0.8):
    port.reset_input_buffer()
    t0 = time.time()
    port.write(frame(cmd_hex, value_hex))
    time.sleep(wait)
    data, first = collect(port, window)
    latency = None if first is None else first - t0
    return split_frames(data), latency


A6_ACK = bytes.fromhex('a601')            # acknowledgement = command word | 0x0100
OK_STATUS = bytes.fromhex('0000')


def bindkey_from(frames):
    """Payload layout is <cmd LE><status LE><data>; an A6 success reply ends with the key."""
    for _hex, payload in frames:
        if len(payload) >= 20 and payload[:2] == A6_ACK and payload[2:4] == OK_STATUS:
            return payload[-16:].hex()
    return None


def self_test():
    cases = [
        (ENTER_CMD, ENTER_VAL, 'fdfcfbfa0400ff00010004030201'),
        (LEAVE_CMD, LEAVE_VAL, 'fdfcfbfa0200fe0004030201'),
        ('a000', '', 'fdfcfbfa0200a00004030201'),
        ('a200', '', 'fdfcfbfa0200a20004030201'),
        ('a300', '', 'fdfcfbfa0200a30004030201'),
        (A6, KEY_PARAM, 'fdfcfbfa0400a600030004030201'),
        (A6, ROTATE_PARAM, 'fdfcfbfa0400a600040004030201'),
        (A6, '0100', 'fdfcfbfa0400a600010004030201'),
    ]
    for cmd, value, want in cases:
        got = frame(cmd, value).hex()
        assert got == want, '%s %s -> %s, want %s' % (cmd, value, got, want)
    key = bytes(range(16)).hex()  # synthetic public self-test fixture
    assert bindkey_from([('x', bytes.fromhex('a6010000' + key))]) == key
    assert bindkey_from([('x', bytes.fromhex('a6010100' + key))]) is None      # status != 0
    assert bindkey_from([('x', bytes.fromhex('a6010000'))]) is None            # no key bytes
    print('self-test: %d frame(s) match the recorded captures' % len(cases))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default=None)
    ap.add_argument('--baud', type=int, default=256000)
    ap.add_argument('--version', action='store_true', help='0xA0 build stamp')
    ap.add_argument('--read-key', action='store_true', help='A6 parameter 3')
    ap.add_argument('--rotate-key', action='store_true', help='A6 parameter 4')
    ap.add_argument('--out', choices=('0', '1', '2'), help='OUT control: 0 low, 1 high, 2 release')
    ap.add_argument('--param', type=int, help='A6 parameter number')
    ap.add_argument('--value', default='', help='extra hex bytes after the parameter')
    ap.add_argument('--raw', help='raw command word as hex, e.g. 6000 or a600')
    ap.add_argument('--keep-session', action='store_true', help='do not send 0x00FE afterwards')
    ap.add_argument('--wait', type=float, default=0.8, help='seconds to wait before reading the reply')
    ap.add_argument('--window', type=float, default=0.8, help='seconds to read the reply for')
    ap.add_argument('--self-test', action='store_true', help='check frame bytes, touch no port')
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return 0

    if not args.port:
        ap.error('--port is required for device operations')

    if args.version:
        cmd, value = 'a000', ''
    elif args.read_key:
        cmd, value = A6, KEY_PARAM
    elif args.rotate_key:
        cmd, value = A6, ROTATE_PARAM
    elif args.out is not None:
        cmd, value = A6, '0%s00' % args.out
    elif args.param is not None:
        cmd, value = A6, '%02x00%s' % (args.param, args.value)
    elif args.raw:
        cmd, value = args.raw, args.value
    else:
        ap.error('nothing to do: pick one of --version/--read-key/--rotate-key/--out/--param/--raw')

    try:
        import serial
    except ImportError:
        raise SystemExit('pyserial is missing: install Tester/requirements.txt')
    port = serial.Serial(args.port, args.baud, bytesize=8, parity='N', stopbits=1, timeout=0.3)
    try:
        send(port, ENTER_CMD, ENTER_VAL)
        frames, latency = send(port, cmd, value, wait=args.wait, window=args.window)
    finally:
        if not args.keep_session:
            send(port, LEAVE_CMD, LEAVE_VAL, wait=0.2, window=0.4)
        port.close()

    for hex_frame, payload in frames:
        when = '' if latency is None else ' (reply after %.1fs)' % latency
        print('<- %s%s' % (hex_frame, when))
    if not frames:
        print('<- no acknowledgement (session closed, wrong command, or device busy)')
    key = bindkey_from(frames)
    if key:
        print('bindkey = %s' % key)
        if args.rotate_key:
            print('pair the Home Assistant BTHome integration with this key')
    return 0


if __name__ == '__main__':
    sys.exit(main())
