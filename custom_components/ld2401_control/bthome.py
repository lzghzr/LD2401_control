"""Read the module's authenticated BTHome frames with the bthome_ble library.

Home Assistant hands every integration the raw advertisement; decryption happens
in whichever integration holds the Bindkey.  This module reuses ``bthome_ble``,
the same library the built-in BTHome integration uses, so the frame format,
CCM authentication, replay filtering and measurement decoding are not
re-implemented here.  We still need the raw frame because a control frame has to
carry a counter the module has just broadcast, and the built-in integration does
not expose it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bthome_ble.parser import BTHomeBluetoothDeviceData

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak


class BTHomeFrames:
    """Track the newest counter that this Bindkey authenticates."""

    def __init__(self, bindkey: bytes) -> None:
        """Authenticate frames with this Bindkey."""
        self._parser = BTHomeBluetoothDeviceData(bindkey=bindkey)
        self.counter: int | None = None

    def ensure_bindkey(self, bindkey: bytes) -> None:
        """Switch keys when the linked BTHome entry rotates theirs."""
        if self._parser.bindkey != bindkey:
            self._parser.set_bindkey(bindkey)

    def update(self, service_info: BluetoothServiceInfoBleak) -> bool:
        """Decode one advertisement; report whether a newer authenticated frame arrived.

        A failed authentication, a duplicate or an out-of-order counter leaves
        the parser's counter untouched, so comparing it against the last
        accepted value is what distinguishes a fresh frame from a rejected one.
        """
        self._parser.update(service_info)
        counter = int(self._parser.encryption_counter)
        if counter <= (self.counter or 0):
            return False

        self.counter = counter
        return True
