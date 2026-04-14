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

def dt_to_str(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connstr", required=True)
    parser.add_argument("--action", required=True, choices=["status", "events", "test"])
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
                print(json.dumps(data))
            
            elif args.action == "events":
                # Get recent events from device RAM via SDK API
                events = zk.events.refresh()
                ev_data = []
                for ev in events:
                    ev_data.append({
                        "timestamp": dt_to_str(ev.time),
                        "door_id": ev.door,
                        "card_id": ev.card,
                        "event_type": ev.event_type
                    })
                
                print(json.dumps({"success": True, "events": ev_data}))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    # Ensure stdout encoding
    sys.stdout.reconfigure(encoding='utf-8')
    main()
