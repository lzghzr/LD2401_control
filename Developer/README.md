# Developer checks

Firmware sources and builder live in `src/`, `linker/`, and `tools/`. See
[firmware build](../docs/firmware-build.md) for the pinned factory input and Q32S
toolchain. Use a clean source commit, independent Build ID and empty output
directory for each handoff candidate.

HA behavior checks run from the repository root:

```shell
python -m pip install "bthome-ble==3.9.1" home-assistant-bluetooth pytest
python -B -m pytest Developer/tests -q -p no:cacheprovider
python -B tools/check_repository.py --protocol
```

Run the same commands in a separate virtual environment with
`bthome-ble==3.24.0` for the current verified library version. CI tests these two
exact versions independently. Version 3.9.1 imports the compatibility package
`home-assistant-bluetooth`, so install it as shown instead of substituting a test
module. The integration's minimum requirement stays open to coexist with HA's
built-in BTHome dependency; these checks establish compatibility only with the
versions actually exercised.

The encrypted fixtures use synthetic public addresses and keys. They cover mode
decoding, MIC/replay rejection, key epochs, parser ownership, reload/fallback,
immediate selection, state-notification filtering, send failure, reconciliation,
and superseded queued selections. No Bluetooth adapter is opened.
Shared-parser checks assert authentication status, accepted/rejected updates and
the absence of a fallback parser; they do not wrap private decryption methods.

For additional interface validation, save the official HA release's
`homeassistant/components/bluetooth/passive_update_processor.py` in a local ignored
directory and set `HA_PROCESSOR_SOURCE` to that file when running pytest. The
fixture executes that source's data-update, coordinator and processor classes;
host services at the HA boundary remain synthetic. This is an offline source/API
check, not a running Home Assistant instance or hardware test.

The telemetry C/CCM fixture check additionally requires `llvmlite`:

```shell
python -m pip install llvmlite
python -B Developer/tools/check_telemetry.py --clang <Q32S-toolchain>/clang.exe
```

It compiles the actual `build_live`, frame builder and CCM functions to a host
LLVM target and supplies synthetic GPIO/ADC/MAC/AES inputs. Both firmware layouts
are exercised across radar states, counter parity and hold/OUT combinations.
This validates C behavior and frame encoding; the candidate's Q32S machine code
and real BLE timing are covered by separate build assertions and hardware tests.
