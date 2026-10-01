# 26092431 Developer verification

Candidate identity: firmware **2.50.26092431**, HA integration **1.1.0**, Build ID
**26092431-mode-feedback-r1**. The clean release build report binds the complete
source commit to UFW SHA-256:

```text
367df6fde866918147b5ad5e61257e0cc8db00fecd872a2a6390885b9565872a
```

The UFW is 607840 bytes. App length is 176116 bytes and the linked tail ends at
`0x1e2b114`; the app gained 84 bytes over 26092430. VM starts remain `0x2f000` and
`0x2e000`, and the heap context remains 100 bytes. No new hook or RAM-global
address was introduced. The builder validates fixed factory/toolchain hashes,
stock hook preimages, allowed patch regions, matching mirrors, CRCs, preserved
Key/non-app payloads, reserved entries and fixed VM boundaries. The reference
26092430 still reproduces its original SHA-256:

```text
7e74ed708e109bbd721371a2b74244ea52743be85e9b251198cecdf1f23add7d
```

Developer offline checks completed:

- 80 fixtures execute the actual telemetry/frame/CCM C functions on a host LLVM
  target, with synthetic GPIO, ADC, MAC and AES inputs. They cover both layouts,
  absent radar snapshots and states 0–3, counter parity, manual hold and physical
  OUT combinations. MIC/decryption, AD lengths, output bounds, object order,
  existing measurement encodings and voltage/distance alternation pass.
- 11 HA behavior tests pass with `bthome-ble` 3.24.0, and with minimum 3.9.1.
  Coverage includes authenticated modes, MIC/replay rejection, key changes,
  shared decoding once, reload/fallback, notification filtering, immediate
  selection, failed/unconfirmed sends and superseded queued commands.
- The same HA tests pass while executing the official 2026.3.0 and 2026.9.3
  passive processor/coordinator classes. HA host services at the boundary are
  fixtures; these runs do not start Home Assistant.
- The repository protocol check passes, including source identities, Python/
  JSON syntax, relative imports, documentation links and existing offline role
  tool checks. The builders and checks are also invoked from a different cwd.

These are Developer implementation checks. Independent candidate audit and
hardware tests are **pending**. Live HA rendering, real BLE reception of 31-byte
frames, physical mode switching, UART/A6/FE interactions, reboot/key behavior and
OTA/recovery require validation on the identified candidate. No device operation
or public release is included in these checks.
