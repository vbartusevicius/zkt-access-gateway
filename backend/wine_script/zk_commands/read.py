"""Read-only device commands. SDK imports stay lazy so the native backend
can import this module for REGISTRY without pyzkaccess installed."""

import re
from datetime import datetime

from .base import ReadCommand
from .spec import WRITABLE_TABLES, DEVICE_PARAM_SPECS, DOOR_PARAM_SPECS
from .util import dt_to_str, SafeJSONEncoder
import json


def _as_int(value, default=0):
    """Coerce SDK values (ints, enums, DocValue strings) to int, best effort."""
    if value is None:
        return default
    if hasattr(value, 'value'):
        try:
            return int(value.value)
        except (TypeError, ValueError):
            pass
    try:
        return int(value)
    except (TypeError, ValueError):
        match = re.search(r'\d+', str(value))
        return int(match.group()) if match else default


def _as_name(value, default=""):
    """Enum-friendly string: prefer the enum name, fall back to str()."""
    if value is None:
        return default
    if hasattr(value, 'name'):
        return str(value.name)
    return str(value)


def _value(value):
    """Generic SDK value → JSON-friendly python value."""
    if hasattr(value, 'name') and hasattr(value, 'value'):
        return "%s (%s)" % (value.name, _as_int(value))
    if isinstance(value, (tuple, list)):
        return list(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _spec_value(spec, value):
    """Convert an SDK parameter value by its spec type — selects/ints stay
    numeric so UI select inputs can be prefilled."""
    if value is None:
        return None
    spec_type = spec["type"]
    if spec_type in ("int", "select"):
        return _as_int(value)
    if spec_type == "bool":
        return bool(value) if isinstance(value, bool) else bool(_as_int(value))
    return _value(value)


def fetch_transactions(zk, since_str=""):
    """Fetch transactions from the device, optionally filtering by timestamp.

    Returns (events, error). An empty list with a non-empty error means the
    table read failed — callers surface this instead of silently reporting
    an idle device.
    """
    since_dt = None
    if since_str:
        try:
            since_dt = datetime.fromisoformat(since_str)
        except (ValueError, TypeError):
            pass
    events = []
    try:
        for tx in zk.table('Transaction'):
            ts = tx.time
            if since_dt and isinstance(ts, datetime) and ts <= since_dt:
                continue
            events.append({
                "timestamp": dt_to_str(ts),
                "door_id": tx.door,
                "card_id": tx.card,
                "pin": tx.pin,
                "event_type": tx.event_type,
                "entry_exit": _as_name(getattr(tx, "entry_exit", None)),
                "verify_mode": _as_name(getattr(tx, "verify_mode", None)),
            })
        return events, ""
    except Exception as e:
        return events, str(e)


class TestConnection(ReadCommand):
    name = "test"

    def execute(self, zk):
        return {"ip": zk.parameters.ip_address}


class PollEvents(ReadCommand):
    name = "poll_events"
    args = {"since": str}

    def execute(self, zk, since=""):
        events, error = fetch_transactions(zk, since)
        payload = {"events": events}
        if error:
            payload["events_error"] = error
        return payload


class StateDump(ReadCommand):
    name = "state_dump"
    args = {"since": str}

    def execute(self, zk, since=""):
        hw = {
            "ip": zk.parameters.ip_address,
            "serial_number": zk.parameters.serial_number,
            "device_name": getattr(zk.device_model, 'name', 'Access Controller'),
            "door_count": len(zk.doors),
            "relay_count": len(zk.relays),
            "reader_count": len(zk.readers),
            "aux_input_count": len(zk.aux_inputs)
        }

        doors_data = []
        for i, door in enumerate(zk.doors):
            door_info = {"door_id": i + 1}

            try:
                vm = door.parameters.verify_mode
                door_info["verify_mode"] = str(vm.name) if hasattr(vm, 'name') else str(vm)
            except ValueError as ve:
                door_info["verify_mode"] = "Custom/Unsupported (%s)" % str(ve).split(' ')[0]
            except Exception:
                door_info["verify_mode"] = "Unknown"

            door_info["active"] = not door_info["verify_mode"].startswith(("Custom/Unsupported", "Unknown"))

            for attr in ("lock_on_close", "lock_driver_time", "magnet_alarm_duration"):
                try:
                    val = getattr(door.parameters, attr)
                    door_info[attr] = str(val.name) if hasattr(val, 'name') else val
                except Exception:
                    door_info[attr] = None

            door_info["lock_relay_count"] = len(door.relays.lock)
            door_info["aux_relay_count"] = len(door.relays.aux)
            rn = door.reader.number if hasattr(door.reader, 'number') else None
            door_info["reader"] = "Reader %s" % rn if rn is not None else "Unknown"
            doors_data.append(door_info)

        try:
            users = [u.dict for u in zk.table('User')]
        except Exception as e:
            users = [{"error": str(e)}]

        events, events_error = fetch_transactions(zk, since)

        payload = {
            "hardware": hw,
            "doors": doors_data,
            "users": users,
            "events": events
        }
        if events_error:
            payload["events_error"] = events_error
        return payload


class RtEvents(ReadCommand):
    """Realtime event log (GetRTLog). GetRTLog consumes the device-side read
    pointer, so each call yields only events not delivered to any prior call.

    timeout > 0  → keep the (ephemeral) Wine process waiting up to N seconds
                   for events, 1s cadence
    timeout <= 0 → single non-blocking snapshot; the process returns as fast
                   as one refresh() round-trip takes (minimal Wine residency)
    """
    name = "rt_events"
    args = {"timeout": int}

    def execute(self, zk, timeout=3):
        if timeout and timeout > 0:
            events = zk.events.poll(timeout=timeout)
        else:
            count = zk.events.refresh()
            log = list(getattr(zk.events, 'data', []))
            events = log[-count:] if count > 0 else []
        return {
            "events": [
                {
                    "timestamp": dt_to_str(e.time),
                    "door_id": _as_int(e.door),
                    "card_id": "" if e.card in (None, "0") else str(e.card),
                    "pin": "" if e.pin in (None, "0") else str(e.pin),
                    "event_type": _as_int(e.event_type, default=-1),
                    "entry_exit": _as_name(e.entry_exit),
                    "verify_mode": _as_name(e.verify_mode),
                }
                for e in events
            ]
        }


class SearchDevices(ReadCommand):
    """Broadcast-scan the local subnet for ZKAccess controllers (no connection needed)."""
    name = "search_devices"
    needs_connection = False
    http_path = "device/search"
    http_method = "post"

    def execute(self, zk):
        from pyzkaccess import ZKAccess

        devices = []
        for dev in ZKAccess.search_devices():
            devices.append({
                "ip": str(getattr(dev, "ip", "")),
                "mac": str(getattr(dev, "mac", "")),
                "model": _as_name(getattr(dev, "device_model", None) or getattr(dev, "model", "")),
                "serial_number": str(getattr(dev, "serial_number", "")),
                "version": str(getattr(dev, "version", "")),
            })
        return {"devices": devices}


class DeviceParams(ReadCommand):
    """Dump all known device-wide parameters."""
    name = "device_params"
    http_path = "device/params"
    http_method = "get"

    def execute(self, zk):
        params = {}
        errors = {}
        for spec in DEVICE_PARAM_SPECS:
            name = spec["name"]
            try:
                params[name] = _spec_value(spec, getattr(zk.parameters, name))
            except Exception as e:
                params[name] = None
                errors[name] = str(e)
        payload = {"params": params}
        if errors:
            payload["param_errors"] = errors
        return payload


class DoorParams(ReadCommand):
    """Dump the full parameter set for every door."""
    name = "door_params"
    http_path = "doors/params"
    http_method = "get"

    def execute(self, zk):
        doors = []
        for i, door in enumerate(zk.doors):
            entry = {"door_id": i + 1, "params": {}, "param_errors": {}}
            for spec in DOOR_PARAM_SPECS:
                name = spec["name"]
                try:
                    entry["params"][name] = _spec_value(spec, getattr(door.parameters, name))
                except Exception as e:
                    entry["params"][name] = None
                    entry["param_errors"][name] = str(e)
            if not entry["param_errors"]:
                del entry["param_errors"]
            doors.append(entry)
        return {"doors": doors}


class ReadTable(ReadCommand):
    """Dump a whole access table (schema-gated)."""
    name = "read_table"
    args = {"table": str}
    http_path = "tables/{table}"
    http_method = "get"

    ALLOWED = {"User", "Transaction"} | set(WRITABLE_TABLES)

    def execute(self, zk, table=""):
        if table not in self.ALLOWED:
            return {"success": False, "error": "Unknown or disallowed table '%s'" % table}
        rows = []
        for row in zk.table(table):
            data = row.dict
            if not isinstance(data, dict):
                data = dict(data)
            rows.append(data)
        # Normalize enums/datetimes/tuples to JSON-friendly values
        return {"rows": json.loads(json.dumps(rows, cls=SafeJSONEncoder))}
