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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connstr", required=True)
    parser.add_argument("--action", required=True, choices=["status", "state_dump", "test", "create_user", "delete_user", "trigger_relay", "restart", "sync_time"])
    parser.add_argument("--pin", type=str, default="")
    parser.add_argument("--card", type=str, default="")
    parser.add_argument("--group", type=str, default="1")
    parser.add_argument("--admin", action="store_true")
    parser.add_argument("--relay_id", type=int, default=1)
    args = parser.parse_args()

    try:
        if args.action == "test":
            with ZKAccess(connstr=args.connstr) as zk:
                ip = zk.parameters.ip_address
                print(json.dumps({"success": True, "ip": ip}))
            return

        with ZKAccess(connstr=args.connstr) as zk:
            if args.action == "status":
                users_count = zk.table(User).count()
                data = {
                    "success": True,
                    "connected": True,
                    "ip": zk.parameters.ip_address,
                    "serial_number": zk.parameters.serial_number,
                    "users_count": users_count
                }
                print(json.dumps(data, cls=SafeJSONEncoder))
            
            elif args.action == "state_dump":
                # Pull Parameters & Hardware
                hw = {
                    "ip": zk.parameters.ip_address,
                    "serial_number": zk.parameters.serial_number,
                    "door_count": len(zk.doors),
                    "relay_count": len(zk.relays),
                    "reader_count": len(zk.readers),
                    "aux_input_count": len(zk.aux_inputs)
                }
                
                # Pull Doors specific parameters safely
                doors_data = []
                for i, door in enumerate(zk.doors):
                    try:
                        v_mode = str(door.parameters.verify_mode.name) if hasattr(door.parameters.verify_mode, 'name') else str(door.parameters.verify_mode)
                    except ValueError as ve:
                        # Sometimes devices return unsupported Enum integer values like "7"
                        v_mode = f"Custom/Unsupported ({str(ve).split(' ')[0]})"
                    except Exception:
                        v_mode = "Unknown"
                        
                    doors_data.append({
                        "door_id": i + 1,
                        "verify_mode": v_mode
                    })

                # Pull Users
                try:
                    users_qs = zk.table('User')
                    users = []
                    for u in users_qs:
                        users.append(u.dict)
                except Exception as e:
                    users = [{"error": str(e)}]
                
                # Pull Unread Transactions (replaces volatile events API)
                try:
                    tx_qs = zk.table('Transaction').unread()
                    # It's safer to just fetch all historically unread transactions and let the backend deduplicate
                    transactions = []
                    for tx in tx_qs:
                        transactions.append({
                            "timestamp": dt_to_str(tx.time),
                            "door_id": tx.door,
                            "card_id": tx.card,
                            "pin": tx.pin,
                            "event_type": tx.event_type
                        })
                except Exception as e:
                    transactions = []

                # Return mega JSON blob
                data = {
                    "success": True,
                    "hardware": hw,
                    "doors": doors_data,
                    "users": users,
                    "events": transactions
                }
                print(json.dumps(data, cls=SafeJSONEncoder))

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
                # Fallback zero-index mappings
                target_relay = args.relay_id - 1
                if target_relay < len(zk.relays):
                    # We use default switch_on value (5 seconds)
                    zk.relays[target_relay].switch_on(5)
                    print(json.dumps({"success": True}))
                else:
                    print(json.dumps({"success": False, "error": f"Relay {args.relay_id} out of bounds"}))

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
