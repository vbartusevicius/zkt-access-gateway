"""Cache-backed device reads: the API serves the database until a write
invalidates an entry or the caller explicitly refreshes."""


def _device_calls(bridge, action=None):
    return [c for c in bridge.calls if action is None or c[0] == action]


class TestReadCaching:
    def test_first_read_hits_device_then_serves_cache(self, client, fake_bridge):
        fake_bridge.respond("door_params", {"success": True, "doors": [{"door_id": 1, "params": {}}]})

        first = client.get("/api/doors/params").json()
        assert first["cached"] is False
        assert len(_device_calls(fake_bridge, "door_params")) == 1

        second = client.get("/api/doors/params").json()
        assert second["cached"] is True
        assert second["doors"] == first["doors"]
        assert second["fetched_at"]
        # no additional controller round-trip
        assert len(_device_calls(fake_bridge, "door_params")) == 1

    def test_refresh_param_bypasses_cache(self, client, fake_bridge):
        fake_bridge.respond("device_params", {"success": True, "params": {"ip_address": "1.2.3.4"}})
        client.get("/api/device/params")
        assert len(_device_calls(fake_bridge, "device_params")) == 1

        refreshed = client.get("/api/device/params", params={"refresh": 1}).json()
        assert refreshed["cached"] is False
        assert len(_device_calls(fake_bridge, "device_params")) == 2

    def test_tables_cached_per_table(self, client, fake_bridge):
        fake_bridge.respond("read_table", {"success": True, "rows": []})
        client.get("/api/tables/Holiday")
        client.get("/api/tables/Holiday")
        client.get("/api/tables/Timezone")

        calls = _device_calls(fake_bridge, "read_table")
        assert [c[1]["table"] for c in calls] == ["Holiday", "Timezone"]

    def test_failed_read_is_not_cached(self, client, fake_bridge):
        fake_bridge.respond("door_params", {"success": False, "error": "boom"})
        assert client.get("/api/doors/params").json()["success"] is False
        assert client.get("/api/doors/params").json()["success"] is False
        assert len(_device_calls(fake_bridge, "door_params")) == 2


class TestWriteInvalidation:
    def test_door_param_write_invalidates_door_params(self, client, fake_bridge):
        fake_bridge.respond("door_params", {"success": True, "doors": []})
        client.get("/api/doors/params")
        assert client.get("/api/doors/params").json()["cached"] is True

        client.post("/api/doors/1/param", json={"name": "verify_mode", "value": "4"})

        # cache dropped -> next read talks to the controller again
        assert client.get("/api/doors/params").json()["cached"] is False
        assert len(_device_calls(fake_bridge, "door_params")) == 2

    def test_device_param_and_sync_time_invalidate_device_params(self, client, fake_bridge):
        fake_bridge.respond("device_params", {"success": True, "params": {}})
        for mutation, body in (("/api/device/param", {"name": "backup_hour", "value": 3}),
                               ("/api/device/sync-time", None)):
            client.get("/api/device/params", params={"refresh": 1})
            assert client.get("/api/device/params").json()["cached"] is True
            client.post(mutation, json=body) if body else client.post(mutation)
            assert client.get("/api/device/params").json()["cached"] is False, mutation

    def test_table_row_write_invalidates_only_that_table(self, client, fake_bridge):
        fake_bridge.respond("read_table", {"success": True, "rows": []})
        client.get("/api/tables/Holiday")
        client.get("/api/tables/Timezone")

        client.post("/api/tables/Holiday", json={"data": {"holiday": "0101"}})

        assert client.get("/api/tables/Holiday").json()["cached"] is False
        assert client.get("/api/tables/Timezone").json()["cached"] is True

    def test_user_write_invalidates_user_tables(self, client, fake_bridge):
        fake_bridge.respond("read_table", {"success": True, "rows": []})
        client.get("/api/tables/UserAuthorize")
        assert client.get("/api/tables/UserAuthorize").json()["cached"] is True

        client.post("/api/users", json={"pin": "5", "card": "1", "group": "1"})
        assert client.get("/api/tables/UserAuthorize").json()["cached"] is False

    def test_row_delete_invalidates(self, client, fake_bridge):
        fake_bridge.respond("read_table", {"success": True, "rows": []})
        client.get("/api/tables/Holiday")
        client.request("DELETE", "/api/tables/Holiday/row", json={"key": {"holiday": "0101"}})
        assert client.get("/api/tables/Holiday").json()["cached"] is False


class TestFullSyncWarmsCache:
    def test_state_dump_params_are_cached(self, client, fake_bridge, monkeypatch):
        from backend import main
        fake_bridge.respond("state_dump", {
            "success": True,
            "hardware": {"ip": "10.0.0.5", "serial_number": "SN"},
            "doors": [{"door_id": 1, "active": True}],
            "users": [],
            "events": [],
            "door_params": {"doors": [{"door_id": 1, "params": {"verify_mode": 4}}]},
            "device_params": {"params": {"ip_address": "10.0.0.5"}},
        })
        main.full_sync_job()

        # Pages now render straight from cache, no extra device reads
        doors = client.get("/api/doors/params").json()
        device = client.get("/api/device/params").json()
        assert doors["cached"] is True and doors["doors"][0]["params"]["verify_mode"] == 4
        assert device["cached"] is True and device["params"]["ip_address"] == "10.0.0.5"
        assert _device_calls(fake_bridge, "door_params") == []
        assert _device_calls(fake_bridge, "device_params") == []


class TestPollStaysLightweight:
    def test_poll_job_only_reads_events(self, client, fake_bridge):
        from backend import main
        fake_bridge.respond("rt_events", {"success": True, "events": []})
        main.poll_job()
        assert [c[0] for c in fake_bridge.calls] == ["rt_events"]
