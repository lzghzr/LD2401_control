"""Offline HA boundary fixtures; optional official processor source execution."""

import ast
import dataclasses
from enum import Enum
import importlib
import logging
import os
from pathlib import Path
import sys
import types
from typing import Any, Callable, Self, cast, override

ROOT = Path(__file__).resolve().parents[2]


def module(name, **attributes):
    value = types.ModuleType(name)
    value.__dict__.update(attributes)
    sys.modules[name] = value
    return value


class ConfigEntryState(Enum):
    LOADED = "loaded"
    NOT_LOADED = "not_loaded"


class HomeAssistantError(Exception):
    pass


class BasePassiveBluetoothCoordinator:
    pass


def callback(function):
    return function


def no_platform():
    raise RuntimeError("No active entity platform")


@dataclasses.dataclass
class PassiveBluetoothDataUpdate:
    entity_data: dict = dataclasses.field(default_factory=dict)


class PassiveBluetoothDataProcessor:
    def __init__(self, update_method):
        self.update_method = update_method
        self.restore_key = None

    def async_register_coordinator(self, coordinator, _description):
        self.coordinator = coordinator

    def async_handle_update(self, update, _was_available):
        self.update_method(update)


processor_namespace = {
    "dataclasses": dataclasses, "callback": callback, "override": override,
    "Any": Any, "Callable": Callable, "Self": Self, "cast": cast,
    "BasePassiveBluetoothCoordinator": BasePassiveBluetoothCoordinator,
    "async_get_current_platform": no_platform,
    "logging": logging,
    "UNDEFINED": object(),
}
if source := os.environ.get("HA_PROCESSOR_SOURCE"):
    # Execute the actual official classes, preserving their registration and
    # dispatch methods. Only HA host services at the boundary are fixtures.
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))
    names = {
        "PassiveBluetoothDataUpdate", "PassiveBluetoothProcessorCoordinator",
        "PassiveBluetoothDataProcessor",
    }
    selected = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    selected += [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names]
    executable = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    exec(compile(executable, source, "exec"), processor_namespace)
    PassiveBluetoothDataUpdate = processor_namespace["PassiveBluetoothDataUpdate"]
    PassiveBluetoothDataProcessor = processor_namespace["PassiveBluetoothDataProcessor"]

module("homeassistant")
module("homeassistant.components")
bluetooth = module(
    "homeassistant.components.bluetooth",
    BluetoothScanningMode=types.SimpleNamespace(PASSIVE="passive"),
    BluetoothCallbackReplay=types.SimpleNamespace(NEWEST_FIRST="newest"),
    async_register_callback=lambda *_a, **_k: lambda: None,
    async_scanner_devices_by_address=lambda *_a: [],
)
module(
    "homeassistant.components.bluetooth.passive_update_processor",
    PassiveBluetoothDataProcessor=PassiveBluetoothDataProcessor,
    PassiveBluetoothDataUpdate=PassiveBluetoothDataUpdate,
)
module("homeassistant.config_entries", ConfigEntryState=ConfigEntryState, ConfigEntry=types.SimpleNamespace)
module("homeassistant.core", HomeAssistant=object, callback=callback)
module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
module("homeassistant.helpers")
module("homeassistant.helpers.event", async_track_time_interval=lambda *_a: lambda: None)


class SelectEntityBoundary:
    """Host lifecycle boundary; tests execute the actual integration entity."""

    async def async_added_to_hass(self):
        pass

    def async_on_remove(self, cancel):
        self.cancel_listener = cancel

    def async_write_ha_state(self):
        self.written_states.append((self.current_option, self.available))


module('homeassistant.components.select', SelectEntity=SelectEntityBoundary)
module('homeassistant.helpers.device_registry', CONNECTION_BLUETOOTH='bluetooth', DeviceInfo=dict)
module('homeassistant.helpers.entity_platform', AddConfigEntryEntitiesCallback=Callable)

package = module("ld2401_fixture")
package.__path__ = [str(ROOT / "custom_components/ld2401_control")]
module("ld2401_fixture.mirror", find_bthome_entry=lambda hass, _address: hass.bthome_entry)
frames_module = importlib.import_module("ld2401_fixture.bthome")
shared_module = importlib.import_module("ld2401_fixture.shared")
manager_module = importlib.import_module("ld2401_fixture.coordinator")
select_module = importlib.import_module('ld2401_fixture.select')


def coordinator(parser):
    if source:
        value = object.__new__(processor_namespace["PassiveBluetoothProcessorCoordinator"])
        value._processors = []
        value._available = True
        value.last_update_success = True
        value.restore_data = {}
        value.logger = logging.getLogger("ha_fixture")
        value.device_data = parser
        return value

    class FixtureCoordinator:
        def __init__(self):
            self.device_data = parser
            self._processors = []

        def async_register_processor(self, processor):
            processor.async_register_coordinator(self, None)
            self._processors.append(processor)
            return lambda: self._processors.remove(processor)

        def _process_update(self, update):
            for processor in self._processors:
                processor.async_handle_update(update, True)

    return FixtureCoordinator()
