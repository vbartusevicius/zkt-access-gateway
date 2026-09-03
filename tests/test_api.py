"""API surface tests via FastAPI TestClient with a stubbed bridge (no Wine)."""


class TestStaticEndpoints:
    def test_status(self, client):
        body = client.get("/api/status").json()
        assert {"connected", "mqtt_connected", "serial_number"} <= set(body)

    def test_schemas(self, client):
        body = client.get("/api/schemas").json()
        assert "UserAuthorize" in body["tables"]
        assert len(body["door_params"]) >= 11
        assert "27" in body["event_types"]

    def test_settings_masks_password(self, client):
        body = client.get("/api/settings").json()
        assert "zkt_connstr" in body


class TestEventsEndpoint:
    def test_description_attached(self, client):
        from backend import database
        database.save_events([{
            "timestamp": "2026-09-03T10:00:00", "door_id": 1, "card_id": "100",
            "pin": "1", "event_type": 23, "entry_exit": "", "verify_mode": "only_card",
        }])
        body = client.get("/api/events").json()
        ev = body["events"][0]
        assert ev["description"] == "Access Denied"
        assert ev["verify_mode"] == "only_card"

    def test_filter_params(self, client):
        from backend import database
        database.save_events([
            {"timestamp": "2026-09-03T10:00:00", "door_id": 1, "card_id": "100", "pin": "1",
             "event_type": 0, "entry_exit": "", "verify_mode": ""},
            {"timestamp": "2026-09-03T11:00:00", "door_id": 2, "card_id": "999", "pin": "",
             "event_type": 27, "entry_exit": "", "verify_mode": ""},
        ])
        assert len(client.get("/api/events", params={"door_id": 2}).json()["events"]) == 1
        assert len(client.get("/api/events", params={"event_type": 27}).json()["events"]) == 1
        assert len(client.get("/api/events", params={"q": "999"}).json()["events"]) == 1


class TestUserFlow:
    def test_create_user_strips_name_from_device_but_persists_it(self, client, fake_bridge):
        r = client.post("/api/users", json={
            "name": "Jane Doe", "pin": "5", "card": "16268812", "group": "1",
            "doors": 5, "timezone_id": 1,
        })
        assert r.json()["success"] is True

        action, kw = fake_bridge.last
        assert action == "create_user"
        assert kw["doors"] == 5 and kw["timezone_id"] == 1
        assert "name" not in kw  # device has no name field

        from backend import database
        database.save_users([{"pin": "5", "card": "16268812", "group": "1"}])
        assert client.get("/api/users").json()["users"][0]["name"] == "Jane Doe"

    def test_delete_user(self, client, fake_bridge):
        r = client.request("DELETE", "/api/users/5")
        assert r.json()["success"] is True
        assert fake_bridge.last[0] == "delete_user"
        assert fake_bridge.last[1]["pin"] == "5"


class TestTableRoutes:
    def test_read_table(self, client, fake_bridge):
        fake_bridge.respond("read_table", {
            "success": True, "rows": [{"holiday": "0314", "holiday_type": 2, "loop": 1}],
        })
        body = client.get("/api/tables/Holiday").json()
        assert body["rows"][0]["holiday"] == "0314"
        assert fake_bridge.last == ("read_table", {"table": "Holiday"})

    def test_upsert_and_delete_pass_dict_payloads_through(self, client, fake_bridge):
        r = client.post("/api/tables/UserAuthorize", json={
            "data": {"pin": "5", "doors": 3, "timezone_id": 1}})
        assert r.json()["success"] is True
        assert fake_bridge.last[0] == "upsert_table_row"
        assert fake_bridge.last[1]["data"] == {"pin": "5", "doors": 3, "timezone_id": 1}

        r = client.request("DELETE", "/api/tables/UserAuthorize/row",
                           json={"key": {"pin": "5"}})
        assert r.json()["success"] is True
        assert fake_bridge.last[0] == "delete_table_row"
        assert fake_bridge.last[1]["key"] == {"pin": "5"}


class TestDeviceRoutes:
    def test_param_reads_and_writes(self, client, fake_bridge):
        fake_bridge.respond("door_params", {"success": True, "doors": [
            {"door_id": 1, "params": {"verify_mode": 4}}]})
        assert client.get("/api/doors/params").json()["doors"][0]["params"]["verify_mode"] == 4

        r = client.post("/api/doors/1/param", json={"name": "verify_mode", "value": "4"})
        assert r.json()["success"] is True
        assert fake_bridge.last == ("set_door_param", {"door_id": 1, "name": "verify_mode", "value": "4"})

        r = client.post("/api/device/param", json={"name": "watchdog_enabled", "value": True})
        assert r.json()["success"] is True
        # "value" is a str-typed arg, so bools stringify for argv; the command
        # converts them back (("True").lower() parses fine into a bool)
        assert fake_bridge.last[1]["value"].lower() == "true"

    def test_search_devices_without_extra_conn(self, client, fake_bridge):
        r = client.post("/api/device/search")
        assert r.json()["success"] is True
        assert fake_bridge.last[0] == "search_devices"

    def test_actions(self, client, fake_bridge):
        for path, action in [("/api/device/reboot", "restart"),
                             ("/api/device/sync-time", "sync_time"),
                             ("/api/device/cancel-alarm", "cancel_alarm"),
                             ("/api/relays/1/trigger", "trigger_relay"),
                             ("/api/aux/2/trigger", "trigger_aux")]:
            r = client.post(path)
            assert r.json()["success"] is True, path
            assert fake_bridge.last[0] == action, path


class TestFailureMapping:
    def test_bridge_error_becomes_detail(self, client, fake_bridge):
        fake_bridge.respond("restart", {"success": False, "error": "timeout"})
        r = client.post("/api/device/reboot")
        assert r.json() == {"success": False, "detail": "timeout"}

    def test_command_failures_return_non_success(self, client, fake_bridge):
        fake_bridge.respond("create_user", {"success": False, "error": "bad pin"})
        r = client.post("/api/users", json={"pin": "0", "card": "x", "group": "1"})
        assert r.json()["detail"] == "bad pin"
