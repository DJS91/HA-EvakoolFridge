"""Constants for the EVAKOOL fridge integration."""

DOMAIN = "evakool"
MANUFACTURER = "EVAKOOL"
MODEL = "Down Under / CoolRide"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_KEEP_CONNECTED = "keep_connected"

DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 600
DEFAULT_KEEP_CONNECTED = True

COMPARTMENTS = {1: "left", 2: "right"}
