"""Constants for the LD2401 broadcast control integration."""

DOMAIN = "ld2401_control"
BTHOME_DOMAIN = "bthome"
CONF_ADDRESS = "address"
CONF_BINDKEY = "bindkey"
CONF_ACTION = "esphome_action"
CONF_NAME = "name"

BTHOME_SERVICE_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"
COUNTER_MAX_AGE = 45.0
COUNTER_WAIT_TIMEOUT = 5.0
ESP_ACTION_TIME = 2.1
MODE_SETTLE_TIME = 5.0
RUNTIME_CHECK_INTERVAL = 5.0

# ESPHome actions with this name broadcast the control frames. Nodes offering it
# are discovered automatically; the one currently hearing the radar is preferred.
ESPHOME_DOMAIN = "esphome"
ESPHOME_ACTION_SUFFIX = "ld2401_control_broadcast"

# Control frame modes: hold OUT low, hold OUT high, return to automatic control.
OUT_MODE_LOW = 0
OUT_MODE_HIGH = 1
OUT_MODE_AUTO = 2
