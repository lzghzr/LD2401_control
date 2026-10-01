# LD2401 OUT Control for Home Assistant

Integration **1.1.1** provides one **OUT mode** select entity with three options:
`auto`, `hold_low`, and `hold_high`. Suggested entity id:
`select.ld2401_<short address>_out_mode`. The id and unique id are anchored on the
module address, so device renaming and translations do not change them.

Firmware **26092431** includes manual hold (`0x0F`) and physical OUT (`0x10`) in
every encrypted BTHome frame. Automatic mode is hold=0 regardless of the current
pin level; hold=1 reports low/high according to the pin. The mode selector is
unavailable until recent authenticated mode feedback arrives. Earlier firmware
continues to provide its sensor measurements, but does not provide mode feedback.

The selected option changes immediately. The integration sends the authenticated
command while suppressing transient previous-mode feedback. Matching newer
feedback ends this pending selection. A failed send restores the last observed
mode; after transmission a five-second settling window expires on the next frame
or periodic check, and the display reconciles with the last observed mode.
The entity is updated only when its displayed mode or availability changes.
Counter reception continues on every accepted fresh frame.

The built-in BTHome integration normally decrypts and parses each advertisement
once. This integration registers an additional data processor on that entry's
runtime coordinator and consumes its parsed values and authenticated encryption
counter. The raw Bluetooth callback checks runtime ownership and handles fallback;
it does not decrypt while sharing is active. The adapter checks the runtime
interface rather than using an exact-version whitelist. HA 2024.8.0 introduced
BTHome's `entry.runtime_data` storage; this integration retains its declared minimum
HA version of **2026.3.0**. Source/API checks do not substitute for live HA testing.

BTHome unload/reload and key changes are checked on advertisements and every five
seconds. If the runtime interface is absent or incompatible, a lazy standalone
`bthome-ble` parser authenticates the frames instead. Both paths enforce newer
counters, successful encryption authentication, and the configured Bindkey;
plaintext and stale/replayed data cannot authorize a command. Parsed value objects
and authenticated frame lengths are checked to avoid inheriting a hold value from
cached measurements when an earlier firmware is installed. ESPHome still receives
only the signed control advertisement and never receives the Bindkey.

### Upgrade from 1.0.0

The three command button entities are removed from the entity registry during
setup. Automations targeting them must be migrated to `select.select_option`:

```yaml
action: select.select_option
target:
  entity_id: select.ld2401_abcd_out_mode
data:
  option: hold_high
```

Use `hold_low` or `auto` for the other modes. Install firmware 26092431 before
using the selector. Existing radar device associations, BTHome measurements and
ESPHome broadcast actions are retained.

After upgrading the firmware, the built-in BTHome integration also adds a
`generic` binary sensor for manual hold (`0x0F`): on means the module is holding
OUT manually, and off means automatic mode. The OUT mode selector combines this
sensor's state with the physical OUT level.

## Bindkey and mirroring

The radar's parsed frames normally serve both the built-in BTHome measurements and this integration's mode feedback/control counter through one parser. The fallback parser uses the same Bindkey. The Bindkey is the root of both directions of this channel: the control frame is signed with a key derived from it (`AES(bindkey, "LD24-CTRL-KEY-v1")`), and the counter that frame carries is only trusted because it arrived inside a frame this Bindkey authenticates — an unauthenticated high counter from a third party could otherwise steer the control window.

This integration therefore **reads the Bindkey from the built-in BTHome integration's entry for the same address every time** it authenticates a frame or builds a control frame:

- You never type the Bindkey here. Adding the radar to the built-in BTHome integration is all that is needed.
- After a key rotation there is nothing to update: the new key is picked up on the next frame, and the stored copy (used only as a fallback if the BTHome entry disappears) is ignored while that entry exists.
- Devices are recognised by the name their **firmware advertises** (`HLK-LD24…`), which cannot be changed from Home Assistant — renaming the device or the config entry does not hide it. The entry title (the same name with the short address appended) is only a fallback for devices that have not been heard yet. A device that was heard and is *not* a radar is never offered, so other vendors' encrypted BTHome devices cannot be imported by mistake.
- If nothing can be recognised — a renamed device that has not advertised yet — the integration asks you to **pick the device by hand** instead of failing: every BTHome entry that still has an unknown identity is listed with its name and address, and choosing one imports it with that entry's Bindkey.

Adding a control entry happens automatically:

- At Home Assistant start, when the built-in integration registers the device while running, and when the module advertises itself (the integration has a narrow Bluetooth discovery matcher for `HLK-LD24…` plus the BTHome service data).
- Choosing **Add integration → HLK LD2401 OUT Control** imports on the spot, with no form at all, whenever at least one radar is recognised: every one of them is added (the flow reports success for the first and the rest arrive through the same silent import), and when nothing can be recognised the device picker described above appears. With no importable BTHome entry at all it reports that no device was found.
- If you delete a control entry it stays deleted: the address is remembered so the automatic paths will not recreate it. Adding it again through the flow (or via **Reconfigure**) clears that memory.

Removing the entry from the built-in BTHome integration does not remove the control entry; it keeps working with the last known key.

## Install

Copy `custom_components/ld2401_control/` to `<Home Assistant config>/custom_components/ld2401_control`, restart Home Assistant. The entry appears by itself once the radar is configured in the built-in BTHome integration; adding it manually is optional.

The module must be in range of a Home Assistant Bluetooth adapter. Home Assistant installs `bthome-ble` automatically if it is missing; the requirement states a minimum version so it never fights the version pinned by the built-in BTHome integration.

## ESPHome action

ESPHome nodes expose the broadcast through an action named **`ld2401_control_broadcast`** (see [the generic ESPHome example](../esphome/ld2401_sender.example.yaml)). At every command the integration picks the node to use:

1. An action set in **Reconfigure**, while that service still exists.
2. Otherwise, among scanners hearing the radar, prefer the source of the last authenticated frame, then the strongest received signal. Match the scanner's `adapter` (ESPHome node name) to `esphome.<node>_ld2401_control_broadcast`; the scanner's display name also contains its Bluetooth address and is not the service prefix.
3. If reception cannot be attributed, the alphabetically first candidate.

When no node offers the action, commands fail with an error saying so. **Reconfigure** only sets this action; the Bindkey needs no attention there.

Version 1.1.1 fixes automatic sender matching in installations with multiple
ESPHome nodes. Upgrade the custom integration and restart HA; firmware 26092431
and the ESPHome broadcast action do not need an update for this fix. To select a
sender explicitly, enter its complete `esphome.<node>_ld2401_control_broadcast`
action in **Reconfigure**.

If the action succeeds but the radar does not report the selected mode within
the settling window, HA logs `OUT mode feedback did not converge` with the
chosen action, requested/observed mode and counter. A fallback sender choice
also produces a warning. Debug logs record each selected sender without logging
the Bindkey or control payload.

After a selection, the integration waits for a new authenticated counter that arrived after the selection, so a cached advertisement cannot accidentally authorize a repeated command after a Home Assistant reload. It reports an error if it has not received a fresh frame or no ESPHome action is available, and it serializes commands with a 2.1-second minimum interval between transmissions.

The node answers each call through `api.respond`, so a frame it refuses (bad payload or BLE not active) makes the selection fail with that reason instead of silently reporting success. Nodes without that answer — an older ESPHome config — are still supported: the call is then simply fire-and-forget.

ESPHome receives only the short-lived signed control frame; the Bindkey is never logged or sent anywhere.
