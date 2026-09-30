"""Software protocol consistency checks using synthetic public fixtures."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    host = load('Developer/src/control_protocol.py', 'firmware_host_codec')
    ha = load('custom_components/ld2401_control/codec.py', 'ha_control_codec')
    key, address = bytes(range(16)), '02:00:00:00:00:01'
    for counter in (1, 120, 8192, 0xFFFFFFFF):
        for mode in (0, 1, 2):
            one = host.make_control_advertisement(key, address, counter, mode)
            two = ha.make_control_frame(key, address, counter, mode)
            if one != two or len(one) != 30:
                raise SystemExit('Control codec disagreement')
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
    from cryptography.exceptions import InvalidTag
    count = (8192).to_bytes(4, 'little')
    nonce = bytes.fromhex(address.replace(':', '')) + bytes.fromhex('d2fc41') + count
    enc = AESCCM(key, tag_length=4).encrypt(nonce, bytes.fromhex('1001'), None)
    data = b'\x41' + enc[:-4] + count + enc[-4:]
    if host.authenticated_bthome_counter(key, address, data) != 8192:
        raise SystemExit('BTHome counter decoding mismatch')
    try:
        host.authenticated_bthome_counter(key, address, data[:-1] + bytes([data[-1] ^ 1]))
    except InvalidTag:
        pass
    else:
        raise SystemExit('Host codec accepted an invalid MIC')
    print('PASS: 12 control frame comparisons; BTHome authentication fixtures')


if __name__ == '__main__':
    main()
