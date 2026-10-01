# HA 1.1.2 automatic sender verification

The user reported that the 1.1.1 aggregate-source priority selected a distant
sender while testing beside another node. This candidate changes automatic
routing to use each scanner's own cached reception of the radar.

Configured available actions retain priority. Automatic senders must match an
available ESPHome action and have a valid per-radar monotonic timestamp at most
30 seconds old. Find the strongest RSSI, then consider nodes within 3 dB of it.
Choose the newest reception, retaining the previously used action when it is
in that band and its reception lags by at most five seconds. Exact ties use
stable action-name ordering. History updates after the ESPHome call succeeds;
physical delivery still requires authenticated target-mode feedback.

Automatic selection fails explicitly if there is no recent matching receiver,
including single-sender installations. There is no alphabetical or aggregate
source fallback. An explicit action bypasses this ranking and freshness filter.
Authenticated counters, key handling, select feedback and command serialization
retain their existing behavior. Ranking reads scanner caches only during sends
and adds no BTHome parsing or periodic polling.

The public `discovered_device_timestamps` property is present in the official
habluetooth versions used by both the declared minimum HA and the user's HA:

- [HA 2026.3.0 Bluetooth dependencies](https://github.com/home-assistant/core/blob/2026.3.0/homeassistant/components/bluetooth/manifest.json): habluetooth 5.8.0.
- [habluetooth 5.8.0 scanner](https://github.com/Bluetooth-Devices/habluetooth/blob/v5.8.0/src/habluetooth/base_scanner.py).
- [HA 2026.9.4 Bluetooth dependencies](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/components/bluetooth/manifest.json): habluetooth 6.26.11.
- [habluetooth 6.26.11 scanner](https://github.com/Bluetooth-Devices/habluetooth/blob/v6.26.11/src/habluetooth/base_scanner.py).

All 46 Developer tests pass in each of these six local combinations:

| bthome-ble | habluetooth | Official HA processor classes |
| --- | --- | --- |
| 3.9.1 | 5.8.0 | 2026.3.0 |
| 3.24.0 | 5.8.0 | 2026.3.0 |
| 3.9.1 | 6.26.11 | 2026.3.0 |
| 3.9.1 | 6.26.11 | 2026.9.4 |
| 3.24.0 | 7.1.2 | 2026.3.0 |
| 3.24.0 | 7.1.2 | 2026.9.4 |

Tests cover stronger reception overriding the aggregate owner, stale RSSI
caches and the 30-second boundary, invalid/missing timestamps, per-address
freshness, near-equal RSSI/time boundaries, deterministic ties, explicit action
priority, and all three real select options through signing, routing and
synthetic authenticated feedback. One test restores actual remote scanner
objects through their public API and reads their separate RSSI/timestamps.
HA service/lifecycle boundaries and the radio endpoint remain fixtures.

CI covers both parser versions with habluetooth 5.8.0, 6.26.11 and 7.1.2.
Repository/protocol checks from `docs/` and `git diff --check` pass. These are
Developer offline checks. Real HA installation and physical OUT verification
for 1.1.2 remain pending; prior audit/hardware conclusions retain their objects.

Firmware and ESPHome code are unchanged. Firmware 2.50.26092431 remains required,
with SHA-256 `367df6fde866918147b5ad5e61257e0cc8db00fecd872a2a6390885b9565872a`.
Candidate packaging records its full Git commit, unique Build ID and ZIP hash.
