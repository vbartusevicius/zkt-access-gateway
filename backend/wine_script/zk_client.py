import sys
import json
import argparse
from datetime import datetime

# Attempt to import pyzkaccess. This will only succeed if running under Wine python
try:
    from pyzkaccess import ZKAccess
    from pyzkaccess.tables import User
except ImportError:
    print(json.dumps({"success": False, "error": "pyzkaccess not installed or not running under Wine"}))
    sys.exit(1)

# Robust JSON Encoder for ctypes, enums, etc.
class SafeJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        try:
            return super().default(obj)
        except TypeError:
            if hasattr(obj, 'value'):
                return obj.value
            if hasattr(obj, '__int__'):
                return int(obj)
            return str(obj)

def dt_to_str(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)

def _fetch_transactions(zk, since_str=""):
    """Fetch transactions from the device, optionally filtering by timestamp."""
    since_dt = None
    if since_str:
        try:
            since_dt = datetime.fromisoformat(since_str)
        except (ValueError, TypeError):
            pass
    try:
        transactions = []
        for tx in zk.table('Transaction'):
            ts = tx.time
            if since_dt and isinstance(ts, datetime) and ts <= since_dt:
                continue
            transactions.append({
                "timestamp": dt_to_str(ts),
                "door_id": tx.door,
                "card_id": tx.card,
                "pin": tx.pin,
                "event_type": tx.event_type
            })
        return transactions
    except Exception:
        return []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connstr", required=True)
    parser.add_argument("--action", required=True, choices=["state_dump", "poll_events", "test", "create_user", "delete_user", "trigger_relay", "restart", "sync_time"])
    parser.add_argument("--pin", type=str, default="")
    parser.add_argument("--card", type=str, default="")
    parser.add_argument("--group", type=str, default="1")
    parser.add_argument("--admin", action="store_true")
    parser.add_argument("--relay_id", type=int, default=1)
    parser.add_argument("--since", type=str, default="")
    args = parser.parse_args()

    try:
        if args.action == "test":
            with ZKAccess(connstr=args.connstr) as zk:
                ip = zk.parameters.ip_address
                print(json.dumps({"success": True, "ip": ip}))
            return

        with ZKAccess(connstr=args.connstr) as zk:
            if args.action == "state_dump":
                # Pull Parameters & Hardware
                hw = {
                    "ip": zk.parameters.ip_address,
                    "serial_number": zk.parameters.serial_number,
                    "device_name": getattr(zk.device_model, 'name', 'Access Controller'),
                    "door_count": len(zk.doors),
                    "relay_count": len(zk.relays),
                    "reader_count": len(zk.readers),
                    "aux_input_count": len(zk.aux_inputs)
                }
                
                # Pull Doors specific parameters safely
                doors_data = []
                for i, door in enumerate(zk.doors):
                    door_info = {"door_id": i + 1}

                    # active_time_tz: 0 means door is inactive
                    try:
                        door_info["active_time_tz"] = int(door.parameters.active_time_tz)
                    except Exception:
                        door_info["active_time_tz"] = 0
                    door_info["active"] = door_info["active_time_tz"] != 0

                    try:
                        vm = door.parameters.verify_mode
                        door_info["verify_mode"] = str(vm.name) if hasattr(vm, 'name') else str(vm)
                    except ValueError as ve:
                        door_info["verify_mode"] = f"Custom/Unsupported ({str(ve).split(' ')[0]})"
                    except Exception:
                        door_info["verify_mode"] = "Unknown"

                    for attr in ("lock_on_close", "lock_driver_time", "magnet_alarm_duration", "sensor_type"):
                        try:
                            val = getattr(door.parameters, attr)
                            door_info[attr] = str(val.name) if hasattr(val, 'name') else val
                        except Exception:
                            door_info[attr] = None

                    door_info["relay_count"] = len(door.relays)
                    doors_data.append(door_info)

                # Pull Users
                try:
                    users_qs = zk.table('User')
                    users = []
                    for u in users_qs:
                        users.append(u.dict)
                except Exception as e:
                    users = [{"error": str(e)}]
                
                # Pull Transactions — filter by --since if provided
                transactions = _fetch_transactions(zk, args.since)

                # Return mega JSON blob
                data = {
                    "success": True,
                    "hardware": hw,
                    "doors": doors_data,
                    "users": users,
                    "events": transactions
                }
                print(json.dumps(data, cls=SafeJSONEncoder))

            elif args.action == "poll_events":
                transactions = _fetch_transactions(zk, args.since)
                print(json.dumps({"success": True, "events": transactions}, cls=SafeJSONEncoder))

            elif args.action == "create_user":
                my_user = User(card=args.card, pin=args.pin, group=args.group, super_authorize=args.admin)
                zk.table(User).upsert(my_user)
                print(json.dumps({"success": True}))

            elif args.action == "delete_user":
                # Find the target user and pass their record into the delete method
                target_users = [u for u in zk.table(User).where(pin=str(args.pin))]
                if not target_users:
                    # Also try integer just in case SDK types differ
                    target_users = [u for u in zk.table(User).where(pin=args.pin)]
                    
                if target_users:
                    zk.table(User).delete(target_users)
                print(json.dumps({"success": True}))

            elif args.action == "trigger_relay":
                # Door lock relays are under zk.doors[n].relays, NOT zk.relays (which are aux relays)
                door_idx = args.relay_id - 1
                if door_idx < len(zk.doors):
                    zk.doors[door_idx].relays[0].switch_on(5)
                    print(json.dumps({"success": True}))
                else:
                    print(json.dumps({"success": False, "error": f"Door {args.relay_id} out of bounds"}))

            elif args.action == "restart":
                zk.restart()
                print(json.dumps({"success": True}))

            elif args.action == "sync_time":
                zk.parameters.datetime = datetime.now()
                print(json.dumps({"success": True}))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, cls=SafeJSONEncoder))
        sys.exit(1)

if __name__ == "__main__":
    # Ensure stdout encoding
    sys.stdout.reconfigure(encoding='utf-8')
    main()
