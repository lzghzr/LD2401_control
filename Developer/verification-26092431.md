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
Key/non-app payloads and fixed VM boundaries. The original r1 builder recorded
whether reserved entries moved; it did not assert their layout policies. The
audit follow-up below adds those assertions. The reference
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
- 11 HA behavior tests passed with `bthome-ble` 3.24.0. The original claim that
  the same tests passed with minimum 3.9.1 was incorrect: AUD-01 reproduced
  1 failed / 10 passed due to the test's private decryption wrapper. The
  corrected test and separate version runs are recorded below.
  Coverage includes authenticated modes, MIC/replay rejection, key changes,
  shared authenticated updates, reload/fallback, notification filtering, immediate
  selection, failed/unconfirmed sends and superseded queued commands.
- The same HA tests pass while executing the official 2026.3.0 and 2026.9.3
  passive processor/coordinator classes. HA host services at the boundary are
  fixtures; these runs do not start Home Assistant.
- The repository protocol check passes, including source identities, Python/
  JSON syntax, relative imports, documentation links and existing offline role
  tool checks. The builders and checks are also invoked from a different cwd.

These are Developer implementation checks recorded at the original handoff.
Independent audit and hardware results for r1 are now recorded by their owners
in `Auditor/reports/26092431-mode-feedback-r1.md` and
`Tester/reports/26092431-mode-feedback-r1.md`; their coverage and conclusions
remain attached to the original commit and UFW. No device operation or public
release is included in the Developer checks.

## Developer audit follow-up: D1 / D2 / D3

- **D1 / AUD-01:** The shared-parser test now observes `bindkey_verified`,
  `decryption_failed`, accepted updates, authenticated counters and mode changes.
  It also checks that sharing creates no fallback parser. It does not replace
  or count calls to a private decryption method. In separate environments with
  real dependencies, 3.9.1 and 3.24.0 each pass 11 HA tests and 11 reserved-layout
  tests (22 total). The minimum-version environment installs the real
  `home-assistant-bluetooth` compatibility package. CI selects exact versions
  3.9.1 and 3.24.0; the manifest retains its minimum-only requirement to coexist
  with HA's built-in dependency. This is evidence for the tested versions,
  rather than a guarantee of future library compatibility.
  Both library versions also pass all 22 tests with the official HA 2026.3.0
  and 2026.9.3 processor classes (four combinations, without a running HA host).
- **D2 / AUD-03:** Before writing the UFW, the builder asserts reserved entry
  identities/metadata and per-entry layout policies: VM starts at the fixed
  boundary and preserves its original end, PRCT spans zero through VM start,
  and BTIF/EXIF retain their original offsets and sizes. Each mirror's
  `reserved_entry_checks` reports these policies and before/after coordinates;
  `reserved_layout_validated` records successful assertions. Eleven synthetic
  layout tests cover permitted relocation and reject boundary/identity drift.
- **D3 / AUD-05:** The HA upgrade section explains the new built-in BTHome
  `generic` binary sensor for manual hold, including on/off meaning.

The follow-up development build uses a separate output directory and Build ID
`26092431-audit-fixes-dev1`, invoked from `docs/`. Its UFW is byte-identical to
the audited/tested r1 UFW (SHA-256 above). The original r1 artifacts and reports
are preserved. No firmware source or HA runtime implementation was changed.
