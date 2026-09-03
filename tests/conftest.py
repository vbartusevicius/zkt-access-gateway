"""Shared pytest fixtures.

The Wine subprocess is never spawned in tests: backend.main's bridge function
is replaced with a recording stub, and pyzkaccess table models are used
directly (they import natively — only live SDK calls are mocked by the
library itself).
"""
import os
import sys

import pytest

# Back off schedulers/short-circuit before any backend module is imported
os.environ.setdefault("ZK_SYNC_INTERVAL", "99999")
os.environ.setdefault("ZK_FULL_SYNC_INTERVAL", "99999")
os.environ.pop("ZKT_CONNSTR", None)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO_ROOT, os.path.join(REPO_ROOT, "backend", "wine_script")):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Isolated SQLite database per test; returns the database module."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    from backend import database
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    return database


class FakeBridge:
    """Records run_zk_command calls; returns canned responses per action."""

    def __init__(self):
        self.calls = []
        self.responses = {}

    def respond(self, action, payload):
        self.responses[action] = payload

    def __call__(self, connstr, action, **kwargs):
        self.calls.append((action, kwargs))
        return self.responses.get(action, {"success": True})

    @property
    def last(self):
        return self.calls[-1] if self.calls else None


@pytest.fixture()
def fake_bridge():
    return FakeBridge()


@pytest.fixture()
def client(tmp_path, monkeypatch, fake_bridge):
    """FastAPI TestClient with the bridge stubbed and a temp DB."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("ZKT_CONNSTR", "protocol=TCP,ipaddress=10.0.0.99,port=4370")

    from backend import database, main
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setattr(main, "run_zk_command", fake_bridge)
    database.init_db()

    from fastapi.testclient import TestClient
    return TestClient(main.app)
