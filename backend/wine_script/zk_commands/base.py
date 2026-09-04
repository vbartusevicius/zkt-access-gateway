"""Base classes for ZK device commands.

This module is pure Python with NO pyzkaccess imports so it can be imported
from both the Wine subprocess (dispatcher) and the native FastAPI backend
(route/topic generation). Any SDK usage must happen lazily inside execute().
"""

REGISTRY = {}


class Command:
    """Base class for a single device command.

    Subclasses are auto-registered under `name` in REGISTRY. The native
    backend reads REGISTRY to generate HTTP routes and MQTT command topics,
    and the Wine dispatcher uses it to build argparse choices.
    """

    name = ""            # also the --action value
    kind = "read"        # "read" | "write"
    needs_connection = True  # False for broadcaster commands like search_devices
    args = {}            # {"relay_id": int, "since": str}
    http_path = None     # e.g. "relays/{relay_id}/trigger" → POST /api/relays/{relay_id}/trigger
    http_method = "post"
    mqtt_topic = None    # e.g. "relay_{relay_id}" → zkt/<device>/relay_{relay_id}/set
    refresh_after = False  # schedule a full sync after a successful write

    # Cache-backed reads: the API serves the stored result instead of talking
    # to the controller, until a write invalidates it or the caller refreshes.
    # Templates may reference declared args, e.g. "table:{table}".
    cache_key = None
    # Cache keys a successful write makes stale; a trailing '*' clears a family.
    invalidates = ()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name:
            if cls.name in REGISTRY:
                raise RuntimeError("Duplicate command name: %s" % cls.name)
            REGISTRY[cls.name] = cls

    @classmethod
    def validate(cls, raw):
        """Coerce/filter an incoming payload against the declared args."""
        result = {}
        for key, typ in cls.args.items():
            value = raw.get(key)
            if value is None:
                continue  # absent → execute() falls back to its own defaults
            if typ is bool:
                if isinstance(value, str):
                    value = value.strip().lower() in ("1", "true", "yes", "on")
                result[key] = bool(value)
            elif isinstance(value, (dict, list)):
                result[key] = value  # complex JSON payloads handled by the command
            elif value is not None and not isinstance(value, typ):
                try:
                    result[key] = typ(value)
                except (ValueError, TypeError):
                    result[key] = value
            else:
                result[key] = value
        return result

    def execute(self, zk, **kwargs):
        """Run against an open ZKAccess context. Must return a dict."""
        raise NotImplementedError


class ReadCommand(Command):
    kind = "read"


class WriteCommand(Command):
    kind = "write"
