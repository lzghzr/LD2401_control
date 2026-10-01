"""Adapt the built-in BTHome runtime without replacing its parser or methods."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def subscribe_updates(
    coordinator: Any, callback: Callable[[Any, Any], None]
) -> Callable[[], None]:
    """Subscribe after parsing; incompatible HA runtimes use local parsing."""
    from homeassistant.components.bluetooth.passive_update_processor import (
        PassiveBluetoothDataProcessor,
        PassiveBluetoothDataUpdate,
    )

    parser = coordinator.device_data
    for name in (
        "bindkey", "bindkey_verified", "encryption_counter", "encryption_scheme",
        "decryption_failed", "last_service_info",
    ):
        getattr(parser, name)
    if not callable(coordinator.async_register_processor):
        raise TypeError("BTHome runtime cannot register a processor")

    def consume(update: Any) -> Any:
        callback(coordinator.device_data, update)
        return PassiveBluetoothDataUpdate()

    processor = PassiveBluetoothDataProcessor(consume)
    processor.restore_key = None
    return coordinator.async_register_processor(processor)
