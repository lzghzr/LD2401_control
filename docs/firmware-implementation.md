# Firmware implementation

## Target and source identity

The target module is HLK LD2401, and the target platform is JieLi Q32S. The target factory firmware is `LD2401_2.50.24110415.ufw`. The builder pins that firmware package to SHA-256 `3e518750921f9392eb71da0becc641915d4204376f7eb571c54ed4f586bab9a7`. It reads both flash mirrors, expects their application payloads to match, and reconstructs the UFW container after replacing the application image. The source builder generates firmware version `2.50.26092430`; the resulting UFW is a local build output.

The application code is compiled into a tail region beginning at `0x1e2a454`; short hooks redirect selected stock call sites into it. The linker script records the section map and stock ROM entry points. The build source also fixes the two VM boundaries at `0x2f000` and `0x2e000` for the two mirror formats. These addresses belong to this specific base image and must be recalculated for any other firmware.

## Main pieces

- `payload.c` implements encrypted BTHome generation, persistent key/counter state, sensor snapshots, BLE receive scheduling, authentication, replay checks, and OUT control.
- `scanrsp.c` constructs the existing scan-response payload while preserving the stock path.
- `rxcontrol.c` parses a bounded legacy advertising payload and verifies the addressed control frame with AES-CMAC.
- `hooks.s` contains fixed-width branches at stock call sites, the firmware-version block, and the A6/A2/FE wrappers.
- `layout.ld` maps the tail sections, hook addresses, and stock ROM functions and asserts each section's expected size.
- `control_protocol.py` is the host-side codec for generating and validating control frames. It is not needed to compile the firmware.
- `build.py` compiles the Q32S sources, links the tail image, applies declared hooks to the pinned stock image, rebuilds both flash mirrors, and emits the UFW container.

Build-time Python helpers live alongside the builder in `Developer/tools/`. The bundled `ld24_elf_sections.py` contains the ELF-section reader used by this build.

## Broadcast behavior

The firmware submits encrypted BTHome v2 service data on the existing legacy advertising path at a 500 ms timer cadence. The service-data UUID is `0xFCD2`; its encrypted-data header is `0x41`. The payload uses the device MAC and the BTHome counter in the AES-CCM nonce, with a four-byte MIC.

The BTHome object stream includes illuminance (`0x05`), OUT as a one-byte binary/power object (`0x10`), motion (`0x21`), occupancy (`0x23`), voltage (`0x0C`), and distance (`0x40`). With a valid radar snapshot, the frame alternates voltage and distance by counter parity to fit the legacy advertisement limit. Without a valid snapshot, voltage remains present each frame. The source calculations are in `build_live()` in `payload.c`; preserve those encodings when updating the object map.

The advertising firmware-version bytes and UART `A0` version stamp are patched from the same version string by the builder. The current build pins the version family to `260924xx` because one advertising byte is shared with the factory company identifier.

## Key and counter state

The device creates a random 16-byte BTHome Bindkey when the current VM record is absent or legacy. A CRC-protected 32-byte versioned record stores the key and counter high-water mark. The key is read through the existing A6 extension (`03`) and rotated through A6 (`04`); A2 factory reset also rotates the key and applies stock defaults.

The counter is reserved in VM in blocks of 8192 before use. A reboot resumes from the reserved high-water mark, skipping any unused values in the previous block so an AES-CCM nonce is not reused. OTA/package changes can invalidate or replace VM state depending on how the image is installed; read the key again after an operation that resets VM or rotates the key.

## Receive-side OUT control

The RX report hook copies one bounded candidate from the BLE stack report and defers cryptographic work to the timer callback. Scanning uses the nonblocking JieLi command path, so it can coexist with the periodic BTHome transmitter. It skips its own scan while the stock B2 operation is marked active by byte `0x4345`; this is target-specific state derived from the stock B2 flow.

### B2 scan state

The stock B2 handler at `0x1e0152e` sets byte `0x4345` to 1 before queuing its scan. The report handler at `0x1e04c82` consumes reports while that byte is 1 and changes it to 2 on a target MAC match. The appended receiver yields while stock B2 is active. These addresses and state meanings were established from the pinned stock binary; a byte stuck at 1 suppresses the appended receive scan.

The 30-byte host-generated control advertisement carries a target MAC in display order, an already-observed BTHome counter, a mode (`0` low, `1` high, `2` automatic), and an eight-byte CMAC. The receiver checks the target MAC, frame structure, tag, counter ordering, and a maximum lag of 120 ticks (60 seconds at the current cadence). A counter may execute once. The firmware uses the existing manual OUT hold byte and physical GPIO state, and automatic mode returns control to the stock radar behavior.

The counter used by a sender must come from a recently received, authenticated BTHome frame from this module. The same Bindkey is used for BTHome decryption and for deriving the control CMAC key; the control protocol does not use the sender's BLE address as its authorization identity.

## Safe change boundaries

Keep the version stamp and advertising version synchronized. Preserve the full-width RX-context pointer and the lock placement. Maintain the order “validate candidate, authenticate, enforce fresh counter, then change OUT.” Any change to tail length, linker placement, mirror layout, or VM boundary is a firmware-layout change and must be handled as a separate engineering task before producing a new image.
