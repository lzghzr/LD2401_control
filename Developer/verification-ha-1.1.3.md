# HA 1.1.3 AUD-06 correction verification

The [Auditor report](../Auditor/reports/26092431-mode-feedback-r1.md), section 14.4,
identified an incomplete RSSI fix in 1.1.2: `None` and NaN were excluded, but
unknown RSSI 0 still outranked valid negative RSSI values.

The resolver now excludes RSSI 0 before building the strongest-signal band,
consistent with the existing exclusion of unknown/non-finite readings. This
also prevents hysteresis from retaining an unknown-signal sender. A sole
zero-RSSI sender is refused by automatic routing; explicit configured actions
retain priority. Reception window, RSSI band, timing, authenticated counters
and select feedback behavior retain the 1.1.2 policy.

Six added regression cases failed against the previous implementation before
the fix. They cover a sole zero-RSSI sender, zero versus -40 dBm with/without
previous-sender history, and all three select options through signed commands
and synthetic authenticated feedback with a competing zero-RSSI node.

All **52 Developer tests pass in each of the six version combinations** listed
in [the 1.1.2 verification record](verification-ha-1.1.2.md): bthome-ble 3.9.1 /
3.24.0, habluetooth 5.8.0 / 6.26.11 / 7.1.2, with the corresponding official HA
2026.3.0 / 2026.9.4 processor classes. Repository/protocol checks from `docs/`
and `git diff --check` pass.

Developer also ran the existing Auditor routing tool without changing it.
Its 11 asserted routing scenarios pass. Its reported `zero_rssi_ranks_best`
scenario selects `m_far` (-40 dBm), and Developer separately asserted that JSON
result; the tool itself reports this boundary without asserting it. This run
does not replace an Auditor closure decision. The Auditor report is unchanged.

Firmware/ESPHome and prior candidate artifacts are unchanged. Firmware
2.50.26092431 SHA-256 remains
`367df6fde866918147b5ad5e61257e0cc8db00fecd872a2a6390885b9565872a`.
The new audit/test candidate records a unique Build ID, full commit and ZIP
hash, and is built from a clean isolated checkout. Live HA/hardware verification
of this candidate remains pending.
