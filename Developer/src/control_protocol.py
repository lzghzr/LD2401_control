"""Host-side codec for LD2401 authenticated OUT advertisements (protocol v1).

The caller sends the returned 30-byte payload as a legacy BLE advertisement.
It should use a counter from an authenticated, recently received BTHome frame.
"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.cmac import CMAC

LABEL = b"LD24-CTRL-KEY-v1"
PREFIX = bytes.fromhex("0201061affd6054c43")


def _mac(address):
    if isinstance(address, str):
        address = bytes.fromhex(address.replace(":", ""))
    address = bytes(address)
    if len(address) != 6:
        raise ValueError("target MAC must be six bytes in display order")
    return address


def _aes_block(key, block):
    return Cipher(algorithms.AES(key), modes.ECB()).encryptor().update(block)


def make_control_advertisement(bindkey, target_mac, counter, mode):
    """Return Flags + manufacturer AD; mode 0=low, 1=high, 2=automatic."""
    bindkey = bytes(bindkey)
    if len(bindkey) != 16:
        raise ValueError("BTHome Bindkey must be 16 bytes")
    if not 1 <= counter <= 0xFFFFFFFF:
        raise ValueError("counter must be an active 32-bit BTHome counter")
    if mode not in (0, 1, 2):
        raise ValueError("mode must be 0, 1, or 2")
    body = bytes([1]) + _mac(target_mac) + counter.to_bytes(4, "little") + bytes([mode, 0])
    control_key = _aes_block(bindkey, LABEL)
    mac = CMAC(algorithms.AES(control_key))
    mac.update(body)
    result = PREFIX + body + mac.finalize()[:8]
    assert len(result) == 30
    return result


def authenticated_bthome_counter(bindkey, target_mac, service_data):
    """Verify encrypted BTHome v2 service data (without UUID) and return counter.

    Raises ValueError on malformed data and InvalidTag on failed authentication.
    """
    bindkey = bytes(bindkey)
    data = bytes(service_data)
    if len(bindkey) != 16 or len(data) < 11 or data[0] != 0x41:
        raise ValueError("expected encrypted BTHome v2 service data and 16-byte key")
    counter_bytes = data[-8:-4]
    nonce = _mac(target_mac) + bytes.fromhex("d2fc41") + counter_bytes
    AESCCM(bindkey, tag_length=4).decrypt(nonce, data[1:-8] + data[-4:], None)
    return int.from_bytes(counter_bytes, "little")
