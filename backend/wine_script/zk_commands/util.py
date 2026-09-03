"""Shared helpers for the Wine-side command dispatcher."""

import json
from datetime import datetime


class SafeJSONEncoder(json.JSONEncoder):
    """Robust JSON Encoder for ctypes values, enums, etc."""
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
