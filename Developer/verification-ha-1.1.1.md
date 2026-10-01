# HA 1.1.1 sender routing verification

User-reported environment: HA 2026.9.4, three ESPHome broadcast actions,
automatic sender selection. Selecting another OUT mode restored the observed
mode a few seconds later, with no reported error.

The original resolver compared `scanner.name` and `scanner.source` with the
ESPHome action's node prefix. The installed HA Bluetooth library produces a
display name such as `z-near (02:00:00:00:10:01)`; the source is the Bluetooth
MAC. Neither matches `z_near_ld2401_control_broadcast`. A three-node fixture
using the real `adapter_human_name` formatter reproduces selection of `a_far`
instead of the hearing scanner `z_near` on the original code.

The resolver now matches `scanner.adapter`, the node identity, to the service
prefix. Among receiving scanners, it first prefers the last authenticated
source, then the highest RSSI. An explicit action still wins, and missing
actions retain the documented fallback behavior with a warning.

The investigation checked the official HA 2026.9.4 ESPHome service naming and
status-response handling, and the public scanner API:

- [ESPHome manager](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/components/esphome/manager.py)
- [Bluetooth API](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/components/bluetooth/api.py)

Previously, an advertisement arriving after the settling deadline cleared the
pending selection without logging. Both advertisement and timer expiry now
report the chosen action, requested/observed mode and counter once. Debug
sender logs omit keys and payloads.

Developer automated coverage includes three-node name matching, explicit action
priority, authenticated-source/RSSI ranking, missing-action fallback, timeout
logging, and all three options through the actual select entity and manager.
The latter tests use real BTHome parsing and independently check the generated
command's address, fresh counter, mode and CMAC before returning synthetic
authenticated feedback. HA lifecycle/service boundaries and the radio endpoint
remain fixtures. The original single-sender stub test did not cover this case.

All 29 Developer tests pass for each of four combinations: bthome-ble 3.9.1 /
3.24.0 with official HA 2026.3.0 / 2026.9.4 processor classes. The repository
protocol check passes from `docs/` (82 public files), and `git diff --check`
passes. These are Developer offline checks.

Firmware and ESPHome sender code are unchanged. The 26092431 firmware's existing
identity and audit/hardware reports remain bound to their original artifacts.
HA 1.1.1 installation, real service routing and physical OUT switching still
require verification in the user's HA instance; the reproduced code defect is
consistent with the report but no live command trace was provided.
