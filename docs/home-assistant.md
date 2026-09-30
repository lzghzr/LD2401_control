# LD2401 OUT Control for Home Assistant

This custom integration adds three stateless command buttons for an LD2401 running the encrypted BTHome control firmware:

- **Hold OUT low**
- **Hold OUT high**
- **Return OUT to auto**

OUT itself has only two levels; the third button is a command, not a state — it releases the manual hold and hands OUT back to the module's own control. The physical level is reported by the built-in BTHome integration as a power binary sensor, which is why these buttons are stateless.

The buttons are created as `button.ld2401_<short address>_out_low`, `..._out_high` and `..._out_auto` (for example `button.ld2401_abcd_out_low`): the id is anchored on the module address, so renaming the device or changing the translation does not move it. Renaming an entity in Home Assistant still takes precedence, and entities created by an earlier version keep the id they already had.

The integration listens passively for the module's encrypted `0xFCD2` BTHome service data. It authenticates and decodes those frames with [`bthome-ble`](https://pypi.org/project/bthome-ble/), the same library Home Assistant's built-in BTHome integration uses, so the BTHome frame format, CCM authentication, replay filtering and measurement decoding are not duplicated here. Each accepted frame hands over its counter, which is used exactly once to build a signed control frame. That frame is then sent through an ESPHome broadcast action, which transmits it for one second. The integration never connects to the radar.

## Bindkey and mirroring

The radar's frames are consumed twice — by the built-in BTHome integration (measurements) and by this integration (the control counter) — and both need the same Bindkey. The Bindkey is the root of both directions of this channel: the control frame is signed with a key derived from it (`AES(bindkey, "LD24-CTRL-KEY-v1")`), and the counter that frame carries is only trusted because it arrived inside a frame this Bindkey authenticates — an unauthenticated high counter from a third party could otherwise steer the control window.

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
2. Otherwise, among all `esphome.<node>_ld2401_control_broadcast` services: the node whose Bluetooth scanner currently hears the radar (or that delivered the last accepted frame).
3. If reception cannot be attributed, the alphabetically first candidate.

When no node offers the action, commands fail with an error saying so. **Reconfigure** only sets this action; the Bindkey needs no attention there.

After a button press, the integration waits for a new authenticated counter that arrived after the press, so a cached advertisement cannot accidentally authorize a repeated command after a Home Assistant reload. It reports an error if it has not received a fresh frame or no ESPHome action is available, and it serializes button presses with a 2.1-second minimum interval between transmissions.

The node answers each call through `api.respond`, so a frame it refuses (bad payload or BLE not active) makes the press fail with that reason instead of silently reporting success. Nodes without that answer — an older ESPHome config — are still supported: the call is then simply fire-and-forget.

ESPHome receives only the short-lived signed control frame; the Bindkey is never logged or sent anywhere.
