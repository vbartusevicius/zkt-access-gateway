"""Pure-data specifications for device tables and parameters.

This module must never import pyzkaccess: it is consumed by the Wine-side
commands, the native backend (/api/schemas) and drives form generation in
the web UI. One source of truth for the whole stack.

Field types understood by the UI/generator:
  str | int | bool | password | date | select | timerange
select adds:  choices: [[value, label], ...]
int adds:     min/max where the SDK validates ranges
"""

# --- VerifyMode / SensorType enum values (mirrors pyzkaccess.enums) ---
VERIFY_MODE_CHOICES = [
    [1, "Only Finger"],
    [3, "Only Password"],
    [4, "Only Card"],
    [6, "Card or Finger"],
    [10, "Card and Finger"],
    [11, "Card and Password"],
    [200, "Other/Custom"],
]

SENSOR_TYPE_CHOICES = [
    [1, "Normal Open"],
    [2, "Normal Closed"],
]

HOLIDAY_LOOP_CHOICES = [
    [0, "Unknown"],
    [1, "Annual"],
    [2, "One-time"],
]

LINKAGE_RELAY_CHOICES = [
    [0, "Lock relay"],
    [1, "Aux relay"],
]

# --- Door parameters (pyzkaccess.param.DoorParameters) ---
DOOR_PARAM_SPECS = [
    {"name": "verify_mode",           "label": "Verify Mode",          "type": "select", "choices": VERIFY_MODE_CHOICES},
    {"name": "sensor_type",           "label": "Door Sensor",          "type": "select", "choices": SENSOR_TYPE_CHOICES},
    {"name": "lock_driver_time",      "label": "Lock Drive Time (s)",  "type": "int", "min": 0, "max": 255,
     "help": "0=normally closed, 1-254=seconds, 255=normally open"},
    {"name": "magnet_alarm_duration", "label": "Magnet Timeout (s)",   "type": "int", "min": 0, "max": 255},
    {"name": "punch_interval",        "label": "Punch Interval (s)",   "type": "int", "min": 0, "max": 255,
     "help": "0 = no interval"},
    {"name": "active_time_tz",        "label": "Active Time Zone",     "type": "int", "min": 0, "max": 50,
     "help": "0 = always active, else Time Zone ID"},
    {"name": "open_time_tz",          "label": "Keep-Open Time Zone",  "type": "int", "min": 0, "max": 50,
     "help": "0 = not set"},
    {"name": "lock_on_close",         "label": "Lock When Closed",     "type": "bool"},
    {"name": "multi_card_open",       "label": "Multi-Card Open",      "type": "bool"},
    {"name": "first_card_open",       "label": "First-Card Open",      "type": "bool"},
    {"name": "cancel_open_day",       "label": "Cancel Open Day",      "type": "int", "min": 0},
    {"name": "duress_password",       "label": "Duress Password",      "type": "password"},
    {"name": "emergency_password",    "label": "Emergency Password",   "type": "password"},
]

# --- Device parameters (pyzkaccess.param.DeviceParameters) ---
# editable=False values are displayed read-only in the UI
DEVICE_PARAM_SPECS = [
    {"name": "serial_number",           "label": "Serial Number",         "type": "str",      "editable": False},
    {"name": "fingerprint_version",     "label": "Fingerprint Version",   "type": "int",      "editable": False},
    {"name": "lock_count",              "label": "Locks",                 "type": "int",      "editable": False},
    {"name": "reader_count",            "label": "Readers",               "type": "int",      "editable": False},
    {"name": "aux_in_count",            "label": "Aux Inputs",            "type": "int",      "editable": False},
    {"name": "aux_out_count",           "label": "Aux Outputs",           "type": "int",      "editable": False},
    {"name": "datetime",                "label": "Device Date/Time",      "type": "str",      "editable": False},
    {"name": "ip_address",              "label": "IP Address",            "type": "str"},
    {"name": "netmask",                 "label": "Netmask",               "type": "str"},
    {"name": "gateway_ip_address",      "label": "Gateway IP",            "type": "str"},
    {"name": "rs232_baud_rate",         "label": "RS232 Baud Rate",       "type": "int", "min": 1},
    {"name": "watchdog_enabled",        "label": "Watchdog",              "type": "bool"},
    {"name": "backup_hour",             "label": "Backup Hour",           "type": "int", "min": 1, "max": 24},
    {"name": "reader_direction",        "label": "Reader Directions",     "type": "str"},
    {"name": "display_daylight_saving", "label": "Adjust Clock for DST",  "type": "bool"},
    {"name": "enable_daylight_saving",  "label": "Daylight Saving",       "type": "bool"},
    {"name": "daylight_saving_mode",    "label": "DST Mode",              "type": "select",
     "choices": [[0, "Mode 1"], [1, "Mode 2"]]},
    {"name": "anti_passback_rule",      "label": "Anti-Passback Rule",    "type": "int", "min": 0,
     "help": "Model-specific bitmask, 0 = disabled"},
    {"name": "interlock",               "label": "Interlock",             "type": "int", "min": 0,
     "help": "Model-specific bitmask, 0 = disabled"},
    {"name": "communication_password",  "label": "Comm Password",         "type": "password",
     "help": "Changing this requires updating ZKT_CONNSTR passwd"},
]

_DEVICE_PARAM_SPECS_BY_NAME = {s["name"]: s for s in DEVICE_PARAM_SPECS}
_DOOR_PARAM_SPECS_BY_NAME = {s["name"]: s for s in DOOR_PARAM_SPECS}

# --- Access tables (pyzkaccess.tables) ---
WRITABLE_TABLES = ("Holiday", "Timezone", "FirstCard", "MultiCard", "InOutFun", "UserAuthorize")


def _tz_fields():
    """Timezone table: 3 segments x 10 days (Sun-Sat + Holiday types 1-3)."""
    days = ["sun", "mon", "tue", "wed", "thu", "fri", "sat", "hol1", "hol2", "hol3"]
    day_labels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Holiday 1", "Holiday 2", "Holiday 3"]
    fields = []
    for seg in (1, 2, 3):
        for day, label in zip(days, day_labels):
            fields.append({
                "name": "%s_time%d" % (day, seg),
                "label": "%s (Seg %d)" % (label, seg),
                "type": "timerange",
            })
    return fields


TABLE_SCHEMAS = {
    "Timezone": {
        "label": "Time Zones",
        "fields": [{"name": "timezone_id", "label": "ID", "type": "str", "key": True}] + _tz_fields(),
    },
    "Holiday": {
        "label": "Holidays",
        "fields": [
            {"name": "holiday", "label": "Date/Segment", "type": "str", "key": True},
            {"name": "holiday_type", "label": "Type", "type": "select",
             "choices": [[1, "Holiday 1"], [2, "Holiday 2"], [3, "Holiday 3"]]},
            {"name": "loop", "label": "Repeat", "type": "select", "choices": HOLIDAY_LOOP_CHOICES},
        ],
    },
    "UserAuthorize": {
        "label": "User Door Access",
        "fields": [
            {"name": "pin", "label": "User PIN", "type": "str", "key": True},
            {"name": "doors", "label": "Doors", "type": "door_mask",
             "help": "Which doors this user may open"},
            {"name": "timezone_id", "label": "Time Zone ID", "type": "int", "min": 0, "max": 50,
             "help": "0/empty = always, else a Time Zone row ID"},
        ],
    },
    "FirstCard": {
        "label": "First-Card Rules",
        "fields": [
            {"name": "door", "label": "Door", "type": "int", "key": True},
            {"name": "pin", "label": "User PIN", "type": "str", "key": True},
            {"name": "timezone_id", "label": "Time Zone ID", "type": "int"},
        ],
    },
    "MultiCard": {
        "label": "Multi-Card Groups",
        "fields": [
            {"name": "index", "label": "Index", "type": "str", "key": True},
            {"name": "door", "label": "Door", "type": "int"},
            {"name": "group1", "label": "Group 1", "type": "str"},
            {"name": "group2", "label": "Group 2", "type": "str"},
            {"name": "group3", "label": "Group 3", "type": "str"},
            {"name": "group4", "label": "Group 4", "type": "str"},
            {"name": "group5", "label": "Group 5", "type": "str"},
        ],
    },
    "InOutFun": {
        "label": "Linkage I/O",
        "fields": [
            {"name": "index", "label": "Index", "type": "str", "key": True},
            {"name": "event_type", "label": "Trigger Event", "type": "int",
             "help": "Event type code, e.g. 23 Access Denied, 8 Remote Opening"},
            {"name": "input_index", "label": "Input Address", "type": "int"},
            {"name": "is_output", "label": "Output Group", "type": "select", "choices": LINKAGE_RELAY_CHOICES},
            {"name": "output_index", "label": "Output Address", "type": "int"},
            {"name": "time", "label": "Active Time", "type": "str"},
            {"name": "reserved", "label": "Reserved", "type": "str"},
        ],
    },
}


def door_param_spec(name):
    return _DOOR_PARAM_SPECS_BY_NAME.get(name)


def device_param_spec(name):
    return _DEVICE_PARAM_SPECS_BY_NAME.get(name)


def table_schema(table):
    return TABLE_SCHEMAS.get(table)
