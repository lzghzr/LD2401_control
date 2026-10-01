# Changelog

## 1.1.3

- Exclude unknown RSSI 0 from automatic sender ranking and hysteresis (AUD-06).
- Add zero-RSSI regression checks for single senders, competing senders and all three select commands.

## 1.1.2

- Select automatic ESPHome senders from per-radar receptions within 30 seconds, then compare RSSI.
- Within a 3 dB signal band, use reception time and retain the previous sender if its reception lags by at most five seconds.
- Report an error when no recent matching sender exists; explicit configured actions keep priority.
- Add stale-cache, near-equal signal, hysteresis and real scanner API regression checks.

## 1.1.1

- Match ESPHome actions to the scanner's node identity when choosing among multiple senders.
- Prefer the last authenticated reception source, then the strongest receiving scanner.
- Report feedback timeouts from both advertisement callbacks and periodic checks.
- Add three-node routing and select-entity command/feedback regression checks.

## 1.1.0

- OUT mode select with immediate selection and authenticated broadcast synchronization.
- Shared parsing through the built-in BTHome runtime, with automatic local fallback.
- Firmware 2.50.26092431 candidate adds manual-hold feedback within the 31-byte legacy frame.
- Key epochs, BTHome reloads, stale feedback and failed sends are handled explicitly.
- Upgrade automations from the removed three buttons to `select.select_option`.
- Fixed-hash 26092430 reproduction remains available with `--version 26092430`.

## 1.0.0

- Encrypted BTHome telemetry through the built-in Home Assistant integration.
- OUT low/high/automatic buttons using authenticated ESPHome advertisements.
- Automatic device/key mirroring and sender selection; stable suggested entity IDs.
- ESPHome reports frame validation and BLE availability failures to Home Assistant.
- LD2401 firmware 2.50.26092430 source, reproducible builder and role-owned device tools.
