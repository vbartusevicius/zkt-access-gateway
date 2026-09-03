"""Write/device-control commands. SDK imports stay lazy so the native backend
can import this module for REGISTRY without pyzkaccess installed."""

import json
from datetime import datetime, date

from .base import WriteCommand
from .spec import device_param_spec, door_param_spec, table_schema, WRITABLE_TABLES

RELAY_PULSE_SECONDS = 5
PIN_MIN, PIN_MAX = 1, 65534
PASSWORD_MAX_LEN = 8


def _convert_param_value(spec, value):
    """Coerce a UI/HTTP string value into the python type a parameter
    setter expects (ints for selects, enums where pyzkaccess requires them)."""
    spec_type = spec["type"]

    if spec_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    if spec_type in ("int", "select"):
        num = int(value)
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None and num < lo or hi is not None and num > hi:
            raise ValueError("Value %d out of allowed range %s-%s" % (num, lo, hi))
        if spec["name"] == "verify_mode":
            from pyzkaccess.enums import VerifyMode
            return VerifyMode(num)
        if spec["name"] == "sensor_type":
            from pyzkaccess.enums import SensorType
            return SensorType(num)
        return num

    if spec_type == "password":
        value = str(value)
        if not (value.isdigit() and len(value) <= PASSWORD_MAX_LEN):
            raise ValueError("Password must be %d digits or less" % PASSWORD_MAX_LEN)
        return value

    return str(value)


def _convert_table_data(schema, data):
    """Coerce raw JSON values into the types the table model expects."""
    converted = {}
    fields = {f["name"]: f for f in schema["fields"]}
    for name, value in data.items():
        if name not in fields:
            continue  # silently drop unknown fields, Model() would reject them
        if value is None or value == "":
            continue  # leave unset to avoid blanking rows
        field_type = fields[name]["type"]
        if field_type in ("int", "select", "door_mask"):
            converted[name] = int(value)
        elif field_type == "bool":
            converted[name] = bool(value) if isinstance(value, bool) \
                else str(value).strip().lower() in ("1", "true", "yes", "on")
        elif field_type == "timerange":
            if isinstance(value, (list, tuple)):
                converted[name] = (_to_time(value[0]), _to_time(value[1]))
            else:
                start, end = str(value).split("-")
                converted[name] = (_to_time(start), _to_time(end))
        else:
            converted[name] = str(value)
    return converted


def _to_time(value):
    """"HH:MM" or plain "HHMM" -> datetime.time (pyzkaccess _tz_validate
    requires time/datetime objects, not ints)."""
    from datetime import time as dtime
    if isinstance(value, dtime):
        return value
    digits = str(value).replace(":", "")[:4]
    num = int(digits)
    if not (0 <= num <= 2359):
        raise ValueError("Invalid time value: %s" % value)
    hour, minute = num // 100, num % 100
    if minute > 59:
        raise ValueError("Invalid time value: %s" % value)
    return dtime(hour, minute)


class CreateUser(WriteCommand):
    """Full upsert of a User record (card/pin/password/group/validity/admin),
    optionally with door access via a UserAuthorize row.

    `doors` is a bitmask: bit N = door N+1 (bit0 = Door 1). `name` is consumed
    gateway-side by the API layer for the event log/HA (device has no name
    field) and is filtered out before this method runs."""
    name = "create_user"
    args = {"pin": str, "card": str, "group": str, "password": str,
            "start_time": str, "end_time": str, "super_authorize": bool,
            "doors": int, "timezone_id": int}
    http_path = None  # explicit route in main.py persists the local name too
    refresh_after = True

    def execute(self, zk, pin="", card="", group="1", password="",
                start_time="", end_time="", super_authorize=False,
                doors=0, timezone_id=1):
        from pyzkaccess.tables import User, UserAuthorize

        if not pin or not str(pin).isdigit() or not (PIN_MIN <= int(pin) <= PIN_MAX):
            return {"success": False,
                    "error": "Invalid PIN: must be numeric between %d and %d" % (PIN_MIN, PIN_MAX)}

        fields = {
            "pin": str(pin),
            "card": str(card),
            "group": str(group),
            "super_authorize": bool(super_authorize),
        }
        if password:
            fields["password"] = str(password)
        for key, value in (("start_time", start_time), ("end_time", end_time)):
            if value:
                try:
                    fields[key] = date.fromisoformat(str(value)[:10])
                except ValueError:
                    return {"success": False, "error": "Invalid %s date: %s" % (key, value)}

        zk.table(User).upsert(User(**fields))

        if doors:
            if not (1 <= int(timezone_id) <= 50):
                return {"success": False, "error": "Invalid timezone_id: must be 1-50"}
            auth = UserAuthorize(pin=str(pin), timezone_id=int(timezone_id), doors=int(doors))
            zk.table(UserAuthorize).upsert(auth)

        return {"success": True}


class DeleteUser(WriteCommand):
    name = "delete_user"
    args = {"pin": str}
    http_path = "users/{pin}"
    http_method = "delete"
    refresh_after = True

    def execute(self, zk, pin=""):
        from pyzkaccess.tables import User

        # Find the target user and pass their record into the delete method
        target_users = [u for u in zk.table(User).where(pin=str(pin))]
        if not target_users:
            # Also try integer just in case SDK types differ
            target_users = [u for u in zk.table(User).where(pin=pin)]

        if not target_users:
            return {"success": False, "error": "User %s not found" % pin}

        zk.table(User).delete(target_users)
        return {"success": True}


def _trigger_relay(zk, relay_id, relay_kind, duration):
    """Trigger the lock or aux relay for door number `relay_id` (1-based)."""
    duration = int(duration) if duration else RELAY_PULSE_SECONDS
    if not 1 <= duration <= 255:
        return {"success": False, "error": "Duration must be 1-255 seconds"}
    idx = int(relay_id) - 1
    if idx < 0 or idx >= len(zk.doors):
        return {"success": False, "error": "Door %s out of bounds" % relay_id}
    relays = getattr(zk.doors[idx].relays, relay_kind)
    if len(relays) == 0:
        return {"success": False, "error": "Door %s has no %s relay" % (relay_id, relay_kind)}
    relays.switch_on(duration)
    return {"success": True}


class TriggerRelay(WriteCommand):
    name = "trigger_relay"
    args = {"relay_id": int, "duration": int}
    http_path = "relays/{relay_id}/trigger"
    mqtt_topic = "relay_{relay_id}"

    def execute(self, zk, relay_id=0, duration=0):
        return _trigger_relay(zk, relay_id, "lock", duration)


class TriggerAux(WriteCommand):
    name = "trigger_aux"
    args = {"relay_id": int, "duration": int}
    http_path = "aux/{relay_id}/trigger"
    mqtt_topic = "aux_{relay_id}"

    def execute(self, zk, relay_id=0, duration=0):
        return _trigger_relay(zk, relay_id, "aux", duration)


class CancelAlarm(WriteCommand):
    """Switch the device from alarm mode back to normal mode."""
    name = "cancel_alarm"
    http_path = "device/cancel-alarm"
    mqtt_topic = "cancel_alarm"

    def execute(self, zk):
        zk.cancel_alarm()
        return {"success": True}


class Restart(WriteCommand):
    name = "restart"
    http_path = "device/reboot"
    mqtt_topic = "reboot"

    def execute(self, zk):
        zk.restart()
        return {"success": True}


class SyncTime(WriteCommand):
    name = "sync_time"
    http_path = "device/sync-time"
    mqtt_topic = "sync_time"

    def execute(self, zk):
        zk.parameters.datetime = datetime.now()
        return {"success": True}


class SetDeviceParam(WriteCommand):
    name = "set_device_param"
    args = {"name": str, "value": str}
    http_path = "device/param"

    def execute(self, zk, name="", value=""):
        spec = device_param_spec(name)
        if spec is None:
            return {"success": False, "error": "Unknown device parameter '%s'" % name}
        if not spec.get("editable", True):
            return {"success": False, "error": "Parameter '%s' is read-only" % name}
        try:
            converted = _convert_param_value(spec, value)
        except (ValueError, TypeError) as e:
            return {"success": False, "error": str(e)}
        try:
            setattr(zk.parameters, name, converted)
        except ValueError as e:
            return {"success": False, "error": "Device rejected value: %s" % e}
        return {"success": True}


class SetDoorParam(WriteCommand):
    name = "set_door_param"
    args = {"door_id": int, "name": str, "value": str}
    http_path = "doors/{door_id}/param"

    def execute(self, zk, door_id=0, name="", value=""):
        spec = door_param_spec(name)
        if spec is None:
            return {"success": False, "error": "Unknown door parameter '%s'" % name}
        idx = int(door_id) - 1
        if idx < 0 or idx >= len(zk.doors):
            return {"success": False, "error": "Door %s out of bounds" % door_id}
        try:
            converted = _convert_param_value(spec, value)
        except (ValueError, TypeError) as e:
            return {"success": False, "error": str(e)}
        try:
            setattr(zk.doors[idx].parameters, name, converted)
        except ValueError as e:
            return {"success": False, "error": "Device rejected value: %s" % e}
        return {"success": True}


def _table_model_cls(table):
    from pyzkaccess import tables
    cls = getattr(tables, table, None)
    if cls is None or table not in WRITABLE_TABLES:
        return None
    return cls


class UpsertTableRow(WriteCommand):
    """Insert or update a row in an access table (schema-gated)."""
    name = "upsert_table_row"
    args = {"table": str, "data": str}
    http_path = "tables/{table}"
    refresh_after = True

    def execute(self, zk, table="", data=""):
        schema = table_schema(table)
        cls = _table_model_cls(table)
        if schema is None or cls is None:
            return {"success": False, "error": "Unknown or read-only table '%s'" % table}
        try:
            raw = json.loads(data) if isinstance(data, str) else data
            fields = _convert_table_data(schema, raw)
            record = cls(**fields)
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            return {"success": False, "error": "Invalid row: %s" % e}
        zk.table(cls).upsert(record)
        return {"success": True}


class DeleteTableRow(WriteCommand):
    """Delete rows matching the given key fields (schema-gated)."""
    name = "delete_table_row"
    args = {"table": str, "key": str}
    http_path = "tables/{table}/row"
    http_method = "delete"
    refresh_after = True

    def execute(self, zk, table="", key=""):
        schema = table_schema(table)
        cls = _table_model_cls(table)
        if schema is None or cls is None:
            return {"success": False, "error": "Unknown or read-only table '%s'" % table}
        try:
            raw = json.loads(key) if isinstance(key, str) else key
            where = _convert_table_data(schema, raw)
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            return {"success": False, "error": "Invalid key: %s" % e}

        queryset = zk.table(cls).where(**where)
        rows = list(queryset)
        if not rows:
            return {"success": False, "error": "No matching rows in %s" % table}
        queryset.delete(rows)
        return {"success": True, "deleted": len(rows)}
