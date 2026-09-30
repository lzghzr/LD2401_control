#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "esphome/components/esp32_ble/ble.h"

namespace ld2401_control {

inline int hex_digit(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

// Whether this module currently holds a broadcast open. ESP32BLE::advertising_*
// is reference counted, so an unpaired advertising_stop() would release someone
// else's advertisement (for example the one from `esp32_ble: advertising: true`)
// and an unpaired start would keep broadcasting a stale control frame.
inline bool &tx_active_() {
  static bool active = false;
  return active;
}

// Why the last start() attempt was refused, for the log and the API response.
inline const char *&last_error_() {
  static const char *error = "";
  return error;
}

// Public views for the YAML.
inline bool tx_active() { return tx_active_(); }
inline const char *last_error() { return last_error_(); }

// The API receives the complete 30-byte frame from control_protocol.py.
// ESPHome itself supplies the Flags AD, so pass only the 25-byte FF value.
inline bool start(const std::string &payload_hex) {
  last_error_() = "";
  if (payload_hex.size() != 60) {
    last_error_() = "payload must be 60 hex characters";
    return false;
  }
  std::vector<uint8_t> frame(30);
  for (std::size_t i = 0; i < frame.size(); ++i) {
    const int high = hex_digit(payload_hex[2 * i]);
    const int low = hex_digit(payload_hex[2 * i + 1]);
    if (high < 0 || low < 0) {
      last_error_() = "payload contains non-hex characters";
      return false;
    }
    frame[i] = static_cast<uint8_t>((high << 4) | low);
  }
  static constexpr uint8_t prefix[] = {0x02, 0x01, 0x06, 0x1a, 0xff,
                                        0xd6, 0x05, 0x4c, 0x43, 0x01};
  for (std::size_t i = 0; i < sizeof(prefix); ++i) {
    if (frame[i] != prefix[i]) {
      last_error_() = "not an LD2401 control frame";
      return false;
    }
  }
  if (frame[20] > 2 || frame[21] != 0) {
    last_error_() = "unknown OUT mode";
    return false;
  }
  auto *ble = esphome::esp32_ble::global_ble;
  if (ble == nullptr || !ble->is_active()) {
    last_error_() = "BLE is not active";
    return false;
  }
  // Replacing an in-flight broadcast is allowed: the newest command wins, and a
  // second start() must not take another reference on the advertisement.
  const bool already_active = tx_active_();
  ble->advertising_set_manufacturer_data(std::vector<uint8_t>(frame.begin() + 5, frame.end()));
  if (!already_active) {
    ble->advertising_start();
    tx_active_() = true;
  }
  return true;
}

inline void stop() {
  if (!tx_active_()) return;  // never touch the reference count unpaired
  tx_active_() = false;
  auto *ble = esphome::esp32_ble::global_ble;
  if (ble == nullptr) return;
  ble->advertising_stop();
  ble->advertising_set_manufacturer_data(std::vector<uint8_t>{});
}

}  // namespace ld2401_control
