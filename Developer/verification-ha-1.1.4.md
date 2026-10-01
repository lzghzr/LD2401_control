# HA 1.1.4 cached counter and command latency verification

Previous versions always waited for a counter newer than the value observed at
selection and slept 2.1 seconds after the ESPHome call. This candidate uses a
recent unused authenticated cached counter during normal operation, and applies
only the remaining interval before a subsequent call.

The first accepted counter establishes the startup/key baseline. A usable
counter must exceed both that baseline and the last attempted send counter,
have an actual reception age of 0–45 seconds, and have been received at or after
the current startup/key epoch. Replayed cache updates preserve their original
timestamps. Multiple pre-start cache updates cannot enable sending. Key rotation
resets the baseline and local counter history; a queued command for a different
key aborts. The firmware's MAC/CMAC, replay and 120-counter lag checks are unchanged.

The dispatch interval is 2.1 seconds between HA ESPHome call starts, rather than
a post-call sleep. A second call at 1.5 seconds waits only 0.6 seconds; calls at
2.1 or 3 seconds add no interval wait. ESPHome radio receipt time is not measured
by this clock. Every attempted call reserves its counter and interval before
handoff, including ambiguous failures. A superseding selection wakes an old
counter wait and prevents its dispatch.

Counter freshness and sender selection run after the interval wait. The sender
policy is unchanged: per-radar reception within 30 seconds, valid nonzero RSSI,
3 dB strongest-signal band and five-second reception hysteresis. Cached counter
use does not retain a previous routing decision. Shared/fallback parser behavior
and optimistic selection with authenticated feedback remain in place.

All **65 Developer tests pass** in each of the six local combinations below:

| bthome-ble | habluetooth | Official HA processor classes |
| --- | --- | --- |
| 3.9.1 | 5.8.0 | 2026.3.0 |
| 3.24.0 | 5.8.0 | 2026.3.0 |
| 3.9.1 | 6.26.11 | 2026.3.0 |
| 3.9.1 | 6.26.11 | 2026.9.4 |
| 3.24.0 | 7.1.2 | 2026.3.0 |
| 3.24.0 | 7.1.2 | 2026.9.4 |

Added coverage executes the real manager and authenticated public fixtures:
unused-cache immediate completion without a new advertisement or post-send
sleep; remaining interval boundaries; replay after reload; original stale/future
timestamps through both parser paths; ambiguous failure reservation; key epoch
reset and key changes while waiting; cache expiry during cooldown; sender
reselection at dispatch; superseded counter waits; multiple pre-start cached
updates. Existing select-entity routing/signing/feedback tests also pass.

Repository/protocol checks from `docs/` and `git diff --check` pass. HA service
and radio boundaries remain fixtures. These are Developer offline checks;
1.1.4 independent audit and live HA/physical OUT latency measurements remain
pending. Existing reports retain their earlier audit/test objects.

Firmware and ESPHome are unchanged. Required firmware 2.50.26092431 remains
SHA-256 `367df6fde866918147b5ad5e61257e0cc8db00fecd872a2a6390885b9565872a`.
The unsigned audit/test candidate is archived from a clean committed checkout
with a new Build ID, full Git commit and ZIP hash.
