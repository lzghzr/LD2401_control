"""Independent check of the 26092431 OUT-mode feedback path.

The Auditor builds its own BTHome frames (from the object stream the candidate's
machine code produces), drives the real ``bthome-ble`` parser and the real
integration modules in ``custom_components/ld2401_control``, and - when an official
Home Assistant ``passive_update_processor.py`` is supplied - registers a processor
through that source's coordinator class.

This is an offline API/behaviour check. It opens no Bluetooth adapter and does not
start Home Assistant; the HA host services at the boundary are minimal stubs.
"""
import argparse
import ast
import dataclasses
import importlib
import inspect
import json
import logging
import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import project_root, resolve_input  # noqa: E402

ADDRESS = "02:00:00:00:00:01"
KEY = bytes(range(16))
UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"
HOLD_OBJECT = 0x0F
MODE_AUTO, MODE_LOW, MODE_HIGH = 2, 0, 1
EXPECTED = {(0, 0): MODE_AUTO, (0, 1): MODE_AUTO, (1, 0): MODE_LOW, (1, 1): MODE_HIGH}
EXPECTED_OPTIONS = {"auto": MODE_AUTO, "hold_low": MODE_LOW, "hold_high": MODE_HIGH}


def plaintext(*, snapshot, odd, hold, level, light=37, distance=123, state=1):
    """The object stream the candidate firmware builds, in ascending object order."""
    if not snapshot:
        return bytes([0x05, 0x00, light, 0x00, 0x0C, 0x80, 0x0C, HOLD_OBJECT,
                      1 if hold else 0, 0x10, level])
    head = [0x05, 0x00, light, 0x00]
    if odd:
        return bytes(head + [HOLD_OBJECT, 1 if hold else 0, 0x10, level, 0x21, state & 1,
                             0x23, int(state != 0), 0x40, distance * 10 & 0xFF,
                             (distance * 10) >> 8])
    return bytes(head + [0x0C, 0x80, 0x0C, HOLD_OBJECT, 1 if hold else 0, 0x10, level,
                         0x21, state & 1, 0x23, int(state != 0)])


def frame(counter, plain, key=KEY, corrupt=False):
    """Encrypted BTHome v2 service data exactly as the firmware emits it."""
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM

    nonce = bytes.fromhex(ADDRESS.replace(":", "")) + bytes.fromhex("d2fc41") \
        + counter.to_bytes(4, "little")
    sealed = AESCCM(key, tag_length=4).encrypt(nonce, plain, None)
    payload = b"\x41" + sealed[:-4] + counter.to_bytes(4, "little") + sealed[-4:]
    if corrupt:
        payload = payload[:-1] + bytes([payload[-1] ^ 1])
    return payload


def service_info(payload, address=ADDRESS):
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
    from habluetooth import BluetoothServiceInfoBleak

    adv = AdvertisementData(local_name="HLK-LD2401_0001", manufacturer_data={},
                            service_data={UUID: payload}, service_uuids=[UUID],
                            tx_power=None, rssi=-50, platform_data=())
    return BluetoothServiceInfoBleak(
        name=adv.local_name, address=address, rssi=-50, manufacturer_data={},
        service_data=adv.service_data, service_uuids=[UUID], source="auditor",
        device=BLEDevice(address, adv.local_name, {}), advertisement=adv,
        connectable=False, time=time.monotonic(), tx_power=None)


class ConfigEntryState:
    LOADED = "loaded"
    NOT_LOADED = "not_loaded"


def official_classes(source, namespace):
    """Execute the data-update, coordinator and processor classes from a HA release."""
    kept = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    wanted = {"PassiveBluetoothDataUpdate", "PassiveBluetoothProcessorCoordinator",
              "PassiveBluetoothDataProcessor"}
    kept += [node for node in ast.parse(source.read_text(encoding="utf-8")).body
             if isinstance(node, ast.ClassDef) and node.name in wanted]
    exec(compile(ast.fix_missing_locations(ast.Module(body=kept, type_ignores=[])),
                 str(source), "exec"), namespace)
    return namespace["PassiveBluetoothDataProcessor"], namespace["PassiveBluetoothDataUpdate"]


def install_ha_stubs(processor, data_update):
    """Register the minimal HA modules the integration modules import."""
    def module(name, **attributes):
        value = types.ModuleType(name)
        value.__dict__.update(attributes)
        sys.modules[name] = value
        return value

    def no_platform():
        raise RuntimeError("no active entity platform")

    module("homeassistant")
    module("homeassistant.components")
    module("homeassistant.components.bluetooth",
           BluetoothScanningMode=types.SimpleNamespace(PASSIVE="passive"),
           BluetoothChange=object)
    module("homeassistant.components.bluetooth.passive_update_processor",
           PassiveBluetoothDataProcessor=processor,
           PassiveBluetoothDataUpdate=data_update)
    module("homeassistant.config_entries", ConfigEntryState=ConfigEntryState)
    module("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    module("homeassistant.exceptions",
           HomeAssistantError=type("HomeAssistantError", (Exception,), {}))


def load_integration(root):
    package = types.ModuleType("ld2401_audit_load")
    package.__path__ = [str(root / "custom_components/ld2401_control")]
    sys.modules["ld2401_audit_load"] = package
    return (importlib.import_module("ld2401_audit_load.bthome"),
            importlib.import_module("ld2401_audit_load.shared"))


def literal_assignments(path, names, namespace=None):
    """Literal assignments to top-level names, evaluated against ``namespace``.

    Only plain name/number/string literals are evaluated here, so the mapping can be
    read without importing the module or running any Home Assistant code.
    """
    found = dict(namespace or {})
    out = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = (ast.Dict, ast.DictComp, ast.Name, ast.Constant, ast.UnaryOp, ast.Tuple,
               ast.List, ast.GeneratorExp, ast.comprehension, ast.Attribute)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 \
                or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not isinstance(node.value, allowed):
            continue
        try:
            value = eval(compile(ast.Expression(node.value), str(path), "eval"),
                         {"__builtins__": {}}, found)
        except (NameError, TypeError, ValueError, SyntaxError):
            continue
        found[name] = value
        if name in names:
            out[name] = value
    return out


def select_mapping(root):
    """Cross-check the entity option strings against the const mode numbers."""
    consts = literal_assignments(root / "custom_components/ld2401_control/const.py",
                                 {"OUT_MODE_LOW", "OUT_MODE_HIGH", "OUT_MODE_AUTO"})
    select = literal_assignments(root / "custom_components/ld2401_control/select.py",
                                 {"OPTIONS", "MODE_OPTIONS"}, consts)
    options = {key: value for key, value in select.get("OPTIONS", {}).items()}
    expected = dict(EXPECTED_OPTIONS)
    inverted = {value: key for key, value in options.items()}
    states = {}
    for name in ("strings.json", "translations/zh-Hans.json"):
        blob = json.loads((root / "custom_components/ld2401_control" / name).read_text(encoding="utf-8"))
        states[name] = set(blob["entity"]["select"]["out_mode"]["state"])
    return options, expected, inverted, select.get("MODE_OPTIONS"), states


def object_ids(plain, widths=None):
    """Walk an object stream and return its object ids in wire order."""
    widths = widths or {0x05: 3, 0x0C: 2, 0x0F: 1, 0x10: 1, 0x21: 1, 0x23: 1, 0x40: 2}
    ids, pos = [], 0
    while pos < len(plain):
        obj = plain[pos]
        if obj not in widths:
            return None
        ids.append(obj)
        pos += widths[obj] + 1
    return ids if pos == len(plain) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--bthome-path', type=Path,
                    help='directory holding an alternative bthome_ble package')
    ap.add_argument('--ha-processor', type=Path,
                    help='official HA passive_update_processor.py to execute')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()

    root = project_root(HERE)
    if args.bthome_path:
        sys.path.insert(0, str(resolve_input(args.bthome_path, root)))
    try:
        import bthome_ble.parser as parser_module
    except ModuleNotFoundError as missing:
        # Older bthome-ble releases import the address type from home_assistant_bluetooth;
        # only annotations use it at runtime, so the installed class stands in.
        if missing.name != 'home_assistant_bluetooth':
            raise
        from habluetooth import BluetoothServiceInfoBleak
        shim = types.ModuleType('home_assistant_bluetooth')
        shim.BluetoothServiceInfoBleak = BluetoothServiceInfoBleak
        sys.modules['home_assistant_bluetooth'] = shim
        import bthome_ble.parser as parser_module
    from bthome_ble.parser import BTHomeBluetoothDeviceData

    rows = []

    def add(ident, ok, detail, status=None):
        rows.append(dict(id=ident, status=status or ('ok' if ok else 'FAIL'), detail=detail))

    if args.ha_processor:
        namespace = {"dataclasses": dataclasses, "callback": lambda f: f,
                     "override": lambda f: f, "logging": logging,
                     "BasePassiveBluetoothCoordinator": type("BasePassiveBluetoothCoordinator",
                                                             (), {}),
                     "async_get_current_platform": lambda: (_ for _ in ()).throw(RuntimeError())}
        processor_class, data_update_class = official_classes(
            resolve_input(args.ha_processor, root), namespace)
        origin = str(args.ha_processor)
    else:
        @dataclasses.dataclass
        class data_update_class:
            entity_data: dict = dataclasses.field(default_factory=dict)

        class processor_class:
            def __init__(self, update_method, restore_key=None):
                self.update_method = update_method
                self.restore_key = restore_key
                self.data = data_update_class()

            def async_register_coordinator(self, coordinator, _description=None):
                self.coordinator = coordinator

            def async_handle_update(self, update, _was_available=True):
                self.update_method(update)
        origin = '(auditor stub: no official source supplied)'

    install_ha_stubs(processor_class, data_update_class)
    frames_module, shared_module = load_integration(root)

    # 1. Layout and tri-state decoding, for each firmware layout.
    bad = []
    for snapshot, odd in ((True, True), (True, False), (False, False)):
        for (hold, level), want in EXPECTED.items():
            frames = frames_module.BTHomeFrames(KEY)
            plain = plaintext(snapshot=snapshot, odd=odd, hold=hold, level=level)
            wanted_length = 15 if snapshot else 11
            ids = object_ids(plain)
            if len(plain) != wanted_length or ids is None or ids != sorted(ids) \
                    or ids.count(HOLD_OBJECT) != 1:
                bad.append('layout snapshot=%s odd=%s is %d bytes, ids %s'
                           % (snapshot, odd, len(plain), ids))
                continue
            if not frames.update(service_info(frame(8193, plain))):
                bad.append('rejected valid frame snapshot=%s odd=%s hold=%d level=%d'
                           % (snapshot, odd, hold, level))
            elif frames.mode != want:
                bad.append('mode %s for hold=%d level=%d, wanted %s'
                           % (frames.mode, hold, level, want))
    add('decode.tri_state', not bad,
        '; '.join(bad) or 'both layouts, all four hold/level states decode')

    # 2. Freshness: replay, reordering and a corrupt MIC must not move the state.
    frames = frames_module.BTHomeFrames(KEY)
    plain = plaintext(snapshot=True, odd=True, hold=1, level=1)
    first = frames.update(service_info(frame(8193, plain)))
    replay = frames.update(service_info(frame(8193, plain)))
    older = frames.update(service_info(frame(8192, plain)))
    tampered = frames.update(service_info(frame(8194, plain, corrupt=True)))
    add('freshness.replay_reorder_tamper',
        first and not replay and not older and not tampered
        and frames.counter == 8193 and frames.mode == MODE_HIGH,
        'first=%s replay=%s older=%s tampered=%s -> counter=%s mode=%s'
        % (first, replay, older, tampered, frames.counter, frames.mode))

    # 3. A key rotation starts a new epoch and drops stale feedback.
    other = bytes(range(16, 32))
    frames.ensure_bindkey(other)
    cleared = frames.counter is None and frames.mode is None
    rotated = frames.update(service_info(frame(8193, plain, key=other)))
    add('key.epoch', cleared and rotated and frames.mode == MODE_HIGH,
        'cleared=%s accepted=%s mode=%s' % (cleared, rotated, frames.mode))

    # 4. A 26092430 frame (13-byte plaintext, no hold object) must not inherit a hold.
    legacy = bytes.fromhex("05002500") + bytes([0x10, 0x01, 0x21, 0x00, 0x23, 0x01,
                                               0x40, 0x10, 0x04])
    frames = frames_module.BTHomeFrames(KEY)
    accepted = frames.update(service_info(frame(8193, legacy)))
    add('legacy.no_stale_hold', accepted and frames.mode is None,
        'accepted=%s mode=%s plaintext=%d bytes' % (accepted, frames.mode, len(legacy)))

    # 5. Registration through the official coordinator: one decrypt, one callback.
    parser = BTHomeBluetoothDeviceData(bindkey=KEY)
    coordinator = object.__new__(namespace["PassiveBluetoothProcessorCoordinator"]) \
        if args.ha_processor else types.SimpleNamespace(device_data=parser, _processors=[],
                                                        restore_data={}, restore_key=None,
                                                        async_register_processor=None)
    if not args.ha_processor:
        def register(processor):
            processor.async_register_coordinator(coordinator)
            coordinator._processors.append(processor)
            return lambda: coordinator._processors.remove(processor)
        coordinator.async_register_processor = register
    else:
        coordinator._processors = []
        coordinator._available = True
        coordinator.last_update_success = True
        coordinator.restore_data = {}
        coordinator.restore_key = None
        coordinator.logger = logging.getLogger("auditor")
        coordinator.device_data = parser
    frames = frames_module.BTHomeFrames(KEY)
    seen = []
    cancel = shared_module.subscribe_updates(
        coordinator, lambda p, u: seen.append(frames.accept(p, u)))
    registered = len(coordinator._processors) == 1
    decrypts = 0
    original = parser._decrypt_bthome
    # bthome-ble 3.9.1 decrypts through a five-argument helper; only the newer
    # one-argument form can be counted this way, so the count is asserted only there.
    countable = len(inspect.signature(original).parameters) == 1

    def counted(bthome_data):
        nonlocal decrypts
        decrypts += 1
        return original(bthome_data)

    if countable:
        parser._decrypt_bthome = counted
    update = parser.update(service_info(frame(8193, plain)))
    if args.ha_processor:
        coordinator._process_update(update, False)
    else:
        for processor in coordinator._processors:
            processor.async_handle_update(update)
    delivered = seen == [True] and frames.mode == MODE_HIGH
    cancel()
    add('shared.processor_delivery',
        registered and delivered and not coordinator._processors,
        'registered=%s delivered=%s mode=%s remaining=%d'
        % (registered, delivered, frames.mode, len(coordinator._processors)))
    add('shared.single_decrypt', not countable or decrypts == 1,
        'decrypt calls during one advertisement: %s'
        % (decrypts if countable else 'not countable in this release'),
        status=None if countable else 'skip')

    # 6. Option strings, mode numbers and HA state translations agree.
    options, expected, inverted, declared_inverse, states = select_mapping(root)
    details_state = all(state == set(expected) for state in states.values())
    add('select.option_mapping',
        options == expected and declared_inverse == inverted and details_state,
        'OPTIONS=%s expected=%s MODE_OPTIONS=%s state keys=%s'
        % (options, expected, declared_inverse,
           {name: sorted(keys) for name, keys in states.items()}))

    print('ha feedback check: bthome-ble %s' % getattr(parser_module, "__file__", "?"))
    print('  HA processor source: %s' % origin)
    for row in rows:
        print('  %-4s %-36s %s' % (row['status'], row['id'], row['detail']))
    failed = [r for r in rows if r['status'] == 'FAIL']
    skipped = [r for r in rows if r['status'] == 'skip']
    print('\n  %d ok, %d failed, %d skipped'
          % (len(rows) - len(failed) - len(skipped), len(failed), len(skipped)))
    if args.json:
        args.json.write_text(json.dumps(dict(
            bthome_ble=getattr(parser_module, "__file__", None), ha_processor=origin,
            checks=rows), ensure_ascii=False, indent=2), encoding="utf-8")
        print('  wrote %s' % args.json)
    if failed:
        print('HA FEEDBACK CHECK FAILED: ' + ', '.join(r['id'] for r in failed))
        return 1
    print('HA FEEDBACK CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())