"""ZK device command registry.

Importing this package registers every command in REGISTRY. Keep all
pyzkaccess imports lazy (inside execute()) so the native FastAPI backend
can import this package without the PULL SDK available.
"""

from .base import Command, ReadCommand, WriteCommand, REGISTRY
from . import read   # noqa: F401  (registers read commands)
from . import write  # noqa: F401  (registers write commands)

__all__ = ["Command", "ReadCommand", "WriteCommand", "REGISTRY"]
