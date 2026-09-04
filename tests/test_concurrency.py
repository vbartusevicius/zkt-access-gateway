"""Device commands run in a threadpool, never on the event loop.

Regression test for the bug where generated command routes were `async def`
but called the blocking Wine subprocess directly: a single slow device read
(e.g. GET /api/doors/params) stalled every other request, so DB-only
endpoints returned empty/failed responses and the UI hung.
"""
import asyncio
import time

import httpx
import pytest


@pytest.fixture()
def app_with_slow_device(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "conc.db"))
    monkeypatch.setenv("ZKT_CONNSTR", "protocol=TCP,ipaddress=10.0.0.99,port=4370")

    from backend import database, main
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "conc.db"))
    database.init_db()

    def slow_bridge(connstr, action, **kwargs):
        time.sleep(1.0)  # simulates the Wine subprocess round-trip
        return {"success": True, "doors": []}

    monkeypatch.setattr(main, "run_zk_command", slow_bridge)
    return main.app


@pytest.mark.asyncio
async def test_slow_device_read_does_not_block_db_endpoints(app_with_slow_device):
    transport = httpx.ASGITransport(app=app_with_slow_device)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        started = time.monotonic()
        device_call = asyncio.create_task(client.get("/api/doors/params", timeout=30))
        await asyncio.sleep(0.1)  # let the device call grab the lock

        # These must answer immediately while the device read is in flight
        status, schemas, events = await asyncio.gather(
            client.get("/api/status", timeout=5),
            client.get("/api/schemas", timeout=5),
            client.get("/api/events", timeout=5),
        )
        db_elapsed = time.monotonic() - started

        assert status.status_code == 200
        assert schemas.status_code == 200 and schemas.json()["tables"]
        assert events.status_code == 200
        # Without the threadpool offload these would wait out the full sleep
        assert db_elapsed < 0.9, f"DB endpoints blocked for {db_elapsed:.2f}s"

        device = await device_call
        assert device.status_code == 200 and device.json()["success"] is True


@pytest.mark.asyncio
async def test_concurrent_device_reads_are_serialized_but_both_answer(app_with_slow_device):
    transport = httpx.ASGITransport(app=app_with_slow_device)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first, second = await asyncio.gather(
            client.get("/api/doors/params", timeout=30),
            client.get("/api/device/params", timeout=30),
        )
        assert first.status_code == second.status_code == 200
        assert first.json()["success"] and second.json()["success"]
