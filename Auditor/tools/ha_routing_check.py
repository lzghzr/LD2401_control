"""Independent check of ESPHome sender routing in the control integration.

The Auditor builds its own scanner fixtures from the real
``bluetooth_adapters.adapter_human_name`` formatter and the real per-address
``discovered_device_timestamps`` surface, loads the integration from an explicit
directory (so an earlier revision can be compared), and drives the real
``LD2401ControlManager._async_resolve_action``.

This opens no Bluetooth adapter and starts no Home Assistant: the scanner API,
services registry and config-entry lookup at the boundary are fixtures.
"""
import argparse
import importlib
import json
import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _paths import project_root, resolve_input  # noqa: E402

ADDRESS = "02:00:00:00:00:01"
KEY = bytes(range(16))
ACTION_SUFFIX = "ld2401_control_broadcast"
ERROR = "ERROR"


def action(name):
    return f"{name}_{ACTION_SUFFIX}"


class Scanner:
    """Stand-in for habluetooth's BaseHaScanner surface the resolver reads."""

    def __init__(self, node, source, decorated=True):
        from bluetooth_adapters import adapter_human_name

        self.adapter = node
        self.source = source
        self.name = adapter_human_name(node, source) if decorated else node


def device(node, source, rssi, age=0.0, decorated=True, drop_adapter=False,
           drop_timestamps=False):
    """One scanner-aware device entry; ``age`` is seconds since it heard the radar."""
    scanner = Scanner(node, source, decorated)
    if drop_adapter:
        del scanner.adapter
    if not drop_timestamps:
        scanner.discovered_device_timestamps = {ADDRESS: time.monotonic() - age}
    return types.SimpleNamespace(scanner=scanner, advertisement=types.SimpleNamespace(rssi=rssi))


def install_stubs():
    def module(name, **attributes):
        value = types.ModuleType(name)
        value.__dict__.update(attributes)
        sys.modules[name] = value
        return value

    state = {"devices": [], "lookups": 0}

    def async_scanner_devices_by_address(_hass, _address, _connectable=False):
        state["lookups"] += 1
        return list(state["devices"])

    module("homeassistant")
    components = module("homeassistant.components")
    bluetooth = module("homeassistant.components.bluetooth",
                       BluetoothScanningMode=types.SimpleNamespace(PASSIVE="passive"),
                       BluetoothChange=object,
                       async_scanner_devices_by_address=async_scanner_devices_by_address,
                       async_register_callback=lambda *_a, **_k: (lambda: None))
    components.bluetooth = bluetooth
    module("homeassistant.config_entries", ConfigEntryState=types.SimpleNamespace(LOADED="loaded"))
    module("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    module("homeassistant.exceptions",
           HomeAssistantError=type("HomeAssistantError", (Exception,), {}))
    module("homeassistant.helpers")
    module("homeassistant.helpers.event", async_track_time_interval=lambda *_a, **_k: (lambda: None))
    return bluetooth, state


def load_manager(directory, package):
    """Import coordinator.py from one integration directory with stubbed HA services."""
    integration = resolve_input(directory, project_root(HERE))
    pkg = types.ModuleType(package)
    pkg.__path__ = [str(integration)]
    sys.modules[package] = pkg
    mirror = types.ModuleType(package + ".mirror")
    mirror.find_bthome_entry = lambda _hass, _address: None
    sys.modules[package + ".mirror"] = mirror
    shared = types.ModuleType(package + ".shared")
    shared.subscribe_updates = lambda *_a, **_k: (lambda: None)
    sys.modules[package + ".shared"] = shared
    return importlib.import_module(package + ".coordinator")


def manager_for(coordinator_module, actions, configured=None):
    names = {action(name) for name in actions}
    services = types.SimpleNamespace(
        async_services_for_domain=lambda _domain: {name: {} for name in names},
        has_service=lambda domain, name: domain == "esphome" and name in names,
    )
    hass = types.SimpleNamespace(services=services)
    return coordinator_module.LD2401ControlManager(
        hass, address=ADDRESS, bindkey=KEY, action=configured or "", name="Fixture radar")


def probe(coordinator_module, state, name, actions, devices, configured=None, previous=None):
    """Run one resolver scenario and return what it selected or refused."""
    state["devices"] = devices
    state["lookups"] = 0
    value = manager_for(coordinator_module, actions, configured)
    value._last_sender_action = previous
    try:
        selected = value._async_resolve_action()
        result = selected[1] if selected else None
        error = None
    except Exception as exc:                       # a refusal is a result too
        result, error = ERROR, "%s: %s" % (type(exc).__name__, exc)
    return dict(scenario=name, selected=result, error=error, scanner_lookups=state["lookups"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--integration-dir', type=Path,
                    default=Path('custom_components/ld2401_control'),
                    help='integration directory to load (default: the current tree)')
    ap.add_argument('--expect-fixed', action='store_true',
                    help='assert the audited routing behaviour (fails on an earlier revision)')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()

    _bluetooth, state = install_stubs()
    coordinator = load_manager(args.integration_dir, "ld2401_routing_audit")
    names = ['a_far', 'm_far', 'z_near']
    rows = []

    def add(*a, **k):
        rows.append(probe(coordinator, state, *a, **k))

    # 1. The hearing node is named last: scanner.adapter carries the node identity,
    #    scanner.name is a decorated display string and scanner.source is a MAC.
    add('decorated_name_and_mac_source', names,
        [device('z-near', '02:00:00:00:10:01', -40)])
    # 2. Equal reception time: the strongest signal decides.
    add('strongest_receiver', names,
        [device('a-far', '02:00:00:00:10:01', -90),
         device('m-far', '02:00:00:00:10:02', -40)])
    # 3. Within the RSSI band, a fresher receiver outranks an older one.
    add('freshest_receiver_wins', names,
        [device('a-far', '02:00:00:00:10:01', -40, age=0.5),
         device('m-far', '02:00:00:00:10:02', -41, age=8.0)])
    # 3b. Outside the band, freshness cannot promote a much weaker receiver.
    add('weaker_beyond_band_excluded', names,
        [device('a-far', '02:00:00:00:10:01', -90, age=0.5),
         device('m-far', '02:00:00:00:10:02', -40, age=8.0)])
    # 4. An explicitly configured action wins without consulting the scanner API.
    add('explicit_action_priority', names,
        [device('z-near', '02:00:00:00:10:01', -20)],
        configured='esphome.' + action('a_far'))
    # 5. No scanner that offers an action has heard the radar: refuse, do not guess.
    add('no_fresh_receiver', names, [])
    # 6. A receiver whose last reception is older than the freshness window is refused.
    add('stale_receiver', names, [device('z-near', '02:00:00:00:10:01', -40, age=600.0)])
    # 7. A receiver without per-address timestamps cannot be ranked.
    add('no_timestamp_receiver', names,
        [device('z-near', '02:00:00:00:10:01', -40, drop_timestamps=True)])
    # 8. Hysteresis: keep the previous sender while the fresher one is within the band.
    add('hysteresis_keeps_previous', names,
        [device('a-far', '02:00:00:00:10:01', -40, age=1.0),
         device('m-far', '02:00:00:00:10:02', -41, age=3.0)],
        previous=('esphome', action('m_far')))
    # 9. Hysteresis releases when the previous sender falls clearly behind.
    add('hysteresis_releases_when_stale', names,
        [device('a-far', '02:00:00:00:10:01', -40, age=1.0),
         device('m-far', '02:00:00:00:10:02', -41, age=20.0)],
        previous=('esphome', action('m_far')))
    # 10. A scanner without the adapter attribute matches only a bare node name.
    add('no_adapter_attribute_bare_name', names,
        [device('z-near', '02:00:00:00:10:01', -40, decorated=False, drop_adapter=True)])
    # 11. Edge: one receiver reports no RSSI.
    add('missing_rssi_one_of_two', names,
        [device('a-far', '02:00:00:00:10:01', None),
         device('m-far', '02:00:00:00:10:02', -40)])
    add('missing_rssi_single', names, [device('z-near', '02:00:00:00:10:01', None)])
    # 12. Edge: a receiver reports RSSI 0, which the Bluetooth library itself treats
    #     as "no signal" and maps to NO_RSSI_VALUE (-127) before comparing. It must
    #     neither win the strongest-signal band nor stand in as the only candidate.
    add('zero_rssi_does_not_win', names,
        [device('a-far', '02:00:00:00:10:01', 0),
         device('m-far', '02:00:00:00:10:02', -40)])
    add('zero_rssi_single', names, [device('z-near', '02:00:00:00:10:01', 0)])

    wanted = {
        'decorated_name_and_mac_source': action('z_near'),
        'strongest_receiver': action('m_far'),
        'freshest_receiver_wins': action('a_far'),
        'weaker_beyond_band_excluded': action('m_far'),
        'explicit_action_priority': action('a_far'),
        'no_fresh_receiver': ERROR,
        'stale_receiver': ERROR,
        'no_timestamp_receiver': ERROR,
        'hysteresis_keeps_previous': action('m_far'),
        'hysteresis_releases_when_stale': action('a_far'),
        'no_adapter_attribute_bare_name': action('z_near'),
        'zero_rssi_does_not_win': action('m_far'),
        'zero_rssi_single': ERROR,
    }
    reported = {'missing_rssi_one_of_two', 'missing_rssi_single'}
    print('routing check: %s' % resolve_input(args.integration_dir, project_root(HERE)))
    failures = []
    for row in rows:
        if row['scenario'] in reported:
            print('  note %-36s %s' % (row['scenario'],
                                       'refused: %s' % row['error'] if row['error']
                                       else 'selected %s' % row['selected']))
            continue
        ok = row['selected'] == wanted[row['scenario']]
        if args.expect_fixed and not ok:
            failures.append(row['scenario'])
        print('  %-4s %-36s selected=%s%s'
              % ('ok' if ok else 'DIFF', row['scenario'], row['selected'],
                 '' if not row['error'] else '  (%s)' % row['error']))
    explicit = next(row for row in rows if row['scenario'] == 'explicit_action_priority')
    if explicit['scanner_lookups']:
        failures.append('explicit_action_priority')
        print('  DIFF explicit_action_priority           consulted the scanner API %d time(s)'
              % explicit['scanner_lookups'])
    print('  scanner API lookups on the explicit-action scenario: %d'
          % explicit['scanner_lookups'])
    if args.json:
        args.json.write_text(json.dumps(dict(
            integration_dir=str(resolve_input(args.integration_dir, project_root(HERE))),
            rows=rows, failures=failures), ensure_ascii=False, indent=2), encoding='utf-8')
    if args.expect_fixed and failures:
        print('ROUTING CHECK FAILED: ' + ', '.join(failures))
        return 1
    print('ROUTING CHECK PASSED' if args.expect_fixed else 'ROUTING SCENARIOS REPORTED')
    return 0


if __name__ == "__main__":
    sys.exit(main())