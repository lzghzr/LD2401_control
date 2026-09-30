# Third-party resources

MIT applies to the project code distributed in this repository. Vendor firmware, HLKRadarTool, JieLi SDK/toolchains, Home Assistant, ESPHome and Python dependencies retain their respective licenses. Vendor binaries are obtained separately by the builder/user.

The UFW/JLFS format helpers were developed using the [jl-misctools](https://github.com/kagaimiq/jl-misctools) unpacker's format/cipher algorithms as a reference, as recorded in the original project helper. Its [MIT notice](third_party/licenses/jl-misctools-MIT.txt) is preserved for this provenance. This repository contains the project's Python helper implementation. Any separately obtained upstream tool must be used under its own license.

The HA integration depends on `bthome-ble`; host control tools use `cryptography`; device tools use `bleak` and `pyserial`. Dependencies are installed through their package distributions, which include their licensing information. ESPHome provides the BLE APIs used by the included advertiser header.
