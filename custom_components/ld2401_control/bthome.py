"""Consume authenticated BTHome updates, with a lazy standalone parser."""

from __future__ import annotations

from typing import Any
from types import SimpleNamespace

from bthome_ble.parser import BTHomeBluetoothDeviceData, EncryptionScheme

from .const import BTHOME_SERVICE_UUID, OUT_MODE_AUTO, OUT_MODE_HIGH, OUT_MODE_LOW


def mode_from_update(update: Any) -> int | None:
    """Use hold and physical level from the same update, never cached entities."""
    values = {
        key.key: value.native_value
        for key, value in update.binary_entity_values.items()
        if key.device_id is None
    }
    hold, level = values.get("generic"), values.get("power")
    if not isinstance(hold, bool) or not isinstance(level, bool):
        return None
    if not hold:
        return OUT_MODE_AUTO
    return OUT_MODE_HIGH if level else OUT_MODE_LOW


class BTHomeFrames:
    """Track fresh authenticated counters and OUT modes across parser owners."""

    def __init__(self, bindkey: bytes) -> None:
        self.bindkey = bindkey
        self._parser: BTHomeBluetoothDeviceData | None = None
        self.counter: int | None = None
        self.mode: int | None = None
        self._value_refs: dict = {}

    def ensure_bindkey(self, bindkey: bytes) -> None:
        """A new key starts a new counter epoch and invalidates old feedback."""
        if self.bindkey != bindkey:
            self.bindkey = bindkey
            self._parser = None
            self.counter = None
            self.mode = None
            self._value_refs = {}

    def accept(self, parser: Any, update: Any) -> bool:
        """Read results only after successful encrypted-frame authentication."""
        if (
            parser.bindkey != self.bindkey
            or parser.encryption_scheme != EncryptionScheme.BTHOME_BINDKEY
            or not parser.bindkey_verified
            or parser.decryption_failed
            or getattr(parser, "downgrade_detected", False)
        ):
            return False
        counter = int(parser.encryption_counter)
        if counter <= (self.counter or 0):
            return False

        # SensorUpdate can retain objects omitted from a later frame. Compare
        # identities, since the parser creates a new value object on each read.
        fresh_values = {
            key: value for key, value in update.binary_entity_values.items()
            if value is not self._value_refs.get(key)
        }
        info = parser.last_service_info
        if info is None:
            return False
        payload = next(
            (data for uuid, data in info.service_data.items() if uuid.lower() == BTHOME_SERVICE_UUID),
            b"",
        )
        if not payload or payload[0] != 0x41 or int.from_bytes(payload[-8:-4], "little") != counter:
            return False
        # 26092431 has 11/15 plaintext bytes. Earlier 9/13-byte layouts must
        # not inherit hold values cached by an already-running parser.
        mode = (
            mode_from_update(SimpleNamespace(binary_entity_values=fresh_values))
            if len(payload) - 9 in (11, 15) else None
        )
        self._value_refs = dict(update.binary_entity_values)
        self.counter = counter
        self.mode = mode
        return True

    def update(self, service_info: Any) -> bool:
        """Authenticate locally when the shared runtime interface is unavailable."""
        if self._parser is None:
            self._parser = BTHomeBluetoothDeviceData(bindkey=self.bindkey)
        update = self._parser.update(service_info)
        return self.accept(self._parser, update)
