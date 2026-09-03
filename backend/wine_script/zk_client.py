"""Wine-side bridge CLI. Dispatches a single command from the zk_commands
registry against an open ZKAccess connection and prints a JSON result.

The command surface (names, args, HTTP paths, MQTT topics) is defined once
in zk_commands/ and consumed by both this dispatcher and the native backend.
"""
import sys
import json
import argparse

from zk_commands import REGISTRY
from zk_commands.util import SafeJSONEncoder


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connstr", default="")  # optional for search_devices
    parser.add_argument("--action", required=True, choices=sorted(REGISTRY.keys()))

    # Union of every declared command argument, so CLI flags match REGISTRY specs
    seen = set()
    for cmd_cls in REGISTRY.values():
        for key, typ in cmd_cls.args.items():
            if key in seen:
                continue
            seen.add(key)
            if typ is bool:
                parser.add_argument("--%s" % key, action="store_true")
            else:
                # None default → validate() drops it so execute() defaults apply
                parser.add_argument("--%s" % key, type=typ, default=None)
    return parser


def main():
    args = build_parser().parse_args()

    # Attempt to import pyzkaccess only for real executions, so `--help`
    # and argparse errors behave normally even without the SDK installed.
    try:
        from pyzkaccess import ZKAccess
    except ImportError:
        print(json.dumps({"success": False, "error": "pyzkaccess not installed or not running under Wine"}))
        sys.exit(1)

    cmd = REGISTRY[args.action]()
    kwargs = cmd.validate(vars(args))

    if cmd.needs_connection and not args.connstr:
        print(json.dumps({"success": False, "error": "Connection string is required for '%s'" % args.action}))
        sys.exit(1)

    try:
        if cmd.needs_connection:
            with ZKAccess(connstr=args.connstr) as zk:
                result = cmd.execute(zk, **kwargs)
        else:
            result = cmd.execute(None, **kwargs)
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, cls=SafeJSONEncoder))
        sys.exit(1)

    if "success" not in result:
        result = {"success": True, **result}
    print(json.dumps(result, cls=SafeJSONEncoder))


if __name__ == "__main__":
    # Ensure stdout encoding
    sys.stdout.reconfigure(encoding='utf-8')
    main()
