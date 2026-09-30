# Portability assessment

## Across operating systems

The firmware source, linker script, protocol description, and host-side Python codec are ordinary text/Python files and can be transferred between Windows, Linux, and macOS. The firmware build itself is tied to the JieLi Q32S toolchain distributed for Windows with the path supplied through `--toolchain` or `JL_Q32S_BIN`. Windows is the verified build host. The HA integration and repository checker can run on Linux; ESPHome is compiled through its own supported environment. BLE/serial device tools depend on the host Bluetooth and serial backend and must be verified separately on each operating system. Another operating system can host a Windows VM, but the build environment and USB access must be set up separately.

Auditor's static tools use only Python's standard library and accept explicit package/listing paths. They can consume previously generated Q32S listings on other systems; producing those listings still requires the applicable JieLi toolchain. Tester capture requires a supported `bleak` backend and adapter access; offline decryption and control-frame generation use `cryptography` and do not require a Bluetooth adapter. macOS Bluetooth APIs generally expose UUID identifiers rather than the six-byte device MAC needed for this protocol's nonce; provide captures with the actual device MAC from a backend that supplies it. Source relocation checks do not establish device backend availability on another operating system.

## Across JieLi products

The workflow is useful as a method, not as a binary patch template. Reuse the general pattern—pin the vendor package, inspect its container and mirrors, compile target-native code, place additions in a confirmed code region, add narrow hooks, then rebuild the original OTA container—only after re-establishing each target's own facts.

For a different model, firmware release, or JieLi SoC, independently identify:

- CPU/ISA, compiler version, calling convention, instruction encoding, and linker behavior.
- UFW signature/key requirements, package and mirror formats, CRC rules, and exact stock-package hash.
- Application and VM boundaries, reserved flash areas, boot/update behavior, and factory-reset semantics.
- Every hook's original bytes, caller/callee ABI, ROM function addresses, RAM globals, BLE report format, and task/interrupt context.
- Advertising limits and controller update rules, and whether the target can scan while advertising.
- The target's BLE peripheral role, UART protocol dispatch, and availability of an existing safe extension point.

Do not carry LD2401 addresses, offsets, stock preimages, VM addresses, or ROM entry points into another model by resemblance alone. A different AC63 board can still ship a different application layout; a different JieLi SoC may need an entirely different toolchain and binary analysis.
