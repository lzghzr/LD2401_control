"""LD2401 OUT control advertisement codec.

The control frame is this integration's own authenticated format (AES-CMAC over
a body carrying the module address, a BTHome counter and the requested mode); it
is not a BTHome frame, so it stays here. Reading the module's BTHome
advertisements lives in bthome.py.
"""

from __future__ import annotations

import re

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.cmac import CMAC

CONTROL_LABEL = b"LD24-CTRL-KEY-v1"
CONTROL_PREFIX = bytes.fromhex("0201061affd6054c43")
MAC_PATTERN = re.compile(r"^[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}$")


def normalize_address(address: str) -> str:
    """Validate and canonicalize a public BLE MAC address."""
    if not MAC_PATTERN.fullmatch(address):
        raise ValueError("Enter the module's six-byte Bluetooth address")
    return address.upper()


def address_bytes(address: str) -> bytes:
    """Convert a display-order MAC address into its six wire bytes."""
    return bytes.fromhex(normalize_address(address).replace(":", ""))


def make_control_frame(
    bindkey: bytes, target_address: str, counter: int, mode: int
) -> bytes:
    """Build a 30-byte authenticated frame; mode is 0=low, 1=high, 2=auto."""
    if len(bindkey) != 16:
        raise ValueError("BTHome Bindkey must be 16 bytes")
    if not 0 < counter <= 0xFFFFFFFF:
        raise ValueError("A fresh, nonzero BTHome counter is required")
    if mode not in (0, 1, 2):
        raise ValueError("Unknown OUT mode")

    body = b"\x01" + address_bytes(target_address) + counter.to_bytes(4, "little")
    body += bytes((mode, 0))
    encryptor = Cipher(algorithms.AES(bindkey), modes.ECB()).encryptor()
    control_key = encryptor.update(CONTROL_LABEL) + encryptor.finalize()
    cmac = CMAC(algorithms.AES(control_key))
    cmac.update(body)
    frame = CONTROL_PREFIX + body + cmac.finalize()[:8]
    if len(frame) != 30:
        raise AssertionError("Control frame must fit the legacy advertisement format")
    return frame
