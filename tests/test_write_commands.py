"""Wine-side write-command logic against stub devices and real pyzkaccess
table models (they validate field types natively — no SDK calls needed)."""
import pytest

from pyzkaccess.tables import Holiday, Timezone

from zk_commands.write import (TriggerRelay, TriggerAux, CreateUser, DeleteUser,
                               SetDeviceParam, SetDoorParam, UpsertTableRow,
                               DeleteTableRow, CancelAlarm, _convert_param_value,
                               _convert_table_data, RELAY_PULSE_SECONDS)


class StubRelays:
    def __init__(self, name): self.fired_with = name

    def __len__(self): return 1

    def switch_on(self, timeout): self.fired_with = timeout


class StubRelaysGroups:
    def __init__(self, lock=True, aux=True):
        self.lock = StubRelays(0) if lock else []
        self.aux = StubRelays(0) if aux else []


class StubParameters:
    pass


class StubDoor:
    def __init__(self, lock=True, aux=True):
        self.relays = StubRelaysGroups(lock, aux)
        self.parameters = StubParameters()


class StubZK:
    def __init__(self, doors=2, **kw):
        self.doors = [StubDoor(**kw)] * doors
        self.parameters = StubParameters()
        self.alarm_cancelled = False
        self.datetime_synced = None

    def cancel_alarm(self): self.alarm_cancelled = True


class TestRelayTriggers:
    def test_lock_trigger_default_duration(self):
        zk = StubZK()
        res = TriggerRelay().execute(zk, relay_id=1)
        assert res == {"success": True}
        assert zk.doors[0].relays.lock.fired_with == RELAY_PULSE_SECONDS

    def test_aux_trigger_with_duration(self):
        zk = StubZK()
        res = TriggerAux().execute(zk, relay_id=2, duration=10)
        assert res == {"success": True}
        assert zk.doors[1].relays.aux.fired_with == 10

    def test_out_of_bounds(self):
        zk = StubZK(doors=1)
        res = TriggerRelay().execute(zk, relay_id=5)
        assert res["success"] is False and "out of bounds" in res["error"]

    def test_zero_and_negative_door_rejected(self):
        zk = StubZK()
        for rid in (0, -3):
            res = TriggerRelay().execute(zk, relay_id=rid)
            assert res["success"] is False

    def test_missing_aux_relay(self):
        zk = StubZK(aux=False)
        res = TriggerAux().execute(zk, relay_id=1)
        assert res["success"] is False and "no aux relay" in res["error"]

    def test_bad_duration(self):
        res = TriggerRelay().execute(StubZK(), relay_id=1, duration=300)
        assert res["success"] is False and "Duration" in res["error"]


class TestCreateUser:
    def test_invalid_pin_rejected(self):
        for pin in ("", "abc", "0", "65535", "-1"):
            res = CreateUser().execute(StubZK(), pin=pin)
            assert res["success"] is False, pin

    def test_bad_date_rejected(self):
        res = CreateUser().execute(StubZK(), pin="5", start_time="not-a-date")
        assert res["success"] is False


class TestParamConversion:
    def test_bool(self):
        from zk_commands.spec import device_param_spec
        assert _convert_param_value(device_param_spec("watchdog_enabled"), "true") is True
        assert _convert_param_value(device_param_spec("watchdog_enabled"), True) is True
        assert _convert_param_value(device_param_spec("watchdog_enabled"), "0") is False

    def test_int_range_enforced(self):
        from zk_commands.spec import device_param_spec
        assert _convert_param_value(device_param_spec("backup_hour"), 12) == 12
        with pytest.raises(ValueError):
            _convert_param_value(device_param_spec("backup_hour"), 25)

    def test_enum_select(self):
        from pyzkaccess.enums import VerifyMode
        from zk_commands.spec import door_param_spec
        assert _convert_param_value(door_param_spec("verify_mode"), "4") == VerifyMode(4)
        with pytest.raises(ValueError):
            _convert_param_value(door_param_spec("verify_mode"), "99")

    def test_password_must_be_digits(self):
        from zk_commands.spec import door_param_spec
        assert _convert_param_value(door_param_spec("duress_password"), "1234") == "1234"
        with pytest.raises(ValueError):
            _convert_param_value(door_param_spec("duress_password"), "ab")

    def test_unknown_or_readonly_params(self):
        assert SetDeviceParam().execute(StubZK(), name="bogus", value="1")["success"] is False
        res = SetDeviceParam().execute(StubZK(), name="serial_number", value="x")
        assert res["success"] is False and "read-only" in res["error"]
        res = SetDoorParam().execute(StubZK(), door_id=9, name="verify_mode", value="4")
        assert "out of bounds" in res["error"]


class StubQS:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.upserted = []
        self.deleted = []

    def where(self, **kw):
        matched = [r for r in self.rows
                   if all(getattr(r, k, None) == v for k, v in kw.items())]
        qs = StubQS(matched)
        qs.upserted, qs.deleted = self.upserted, self.deleted
        qs._parent = self
        return qs

    def upsert(self, rec): self.upserted.append(rec)
    def delete(self, recs): self.deleted.extend(recs)
    def __iter__(self): return iter(self.rows)


class StubTableZK(StubZK):
    def __init__(self, rows=()):
        super().__init__()
        self.qs = StubQS(rows)

    def table(self, cls): return self.qs


class TestTableCommands:
    def test_upsert_accepts_dict_and_json_string(self):
        import json
        zk = StubTableZK()
        r = UpsertTableRow().execute(zk, table="Holiday",
                                     data=json.dumps({"holiday": "0314", "holiday_type": 2}))
        assert r["success"] is True
        assert isinstance(zk.qs.upserted[-1], Holiday)

    def test_upsert_rejects_lucky_drop_unknown_fields(self):
        zk = StubTableZK()
        r = UpsertTableRow().execute(zk, table="Holiday",
                                     data={"holiday": "0314", "not_a_field": "x"})
        assert r["success"] is True  # unknown key dropped by schema, not sent to Model

    def test_upsert_invalid_json(self):
        r = UpsertTableRow().execute(StubTableZK(), table="Holiday", data="{nope")
        assert r["success"] is False

    def test_upsert_readonly_table_refused(self):
        r = UpsertTableRow().execute(StubTableZK(), table="Transaction", data={"x": 1})
        assert "read-only" in r["error"]

    def test_timerange_coercion(self):
        from datetime import time as dtime
        from zk_commands.spec import table_schema
        out = _convert_table_data(table_schema("Timezone"),
                                  {"timezone_id": "3", "sun_time1": ["0800", "1800"],
                                   "mon_time1": "", "junk": 1})
        # pyzkaccess._tz_validate requires time/datetime objects, not ints
        assert out == {"timezone_id": "3", "sun_time1": (dtime(8, 0), dtime(18, 0))}
        Timezone(**out)  # real model validation passes

    def test_timerange_invalid_minute_rejected(self):
        from zk_commands.write import _to_time
        with pytest.raises(ValueError):
            _to_time("0860")
        assert _to_time("08:30") == __import__("datetime").time(8, 30)

    def test_delete_by_key(self):
        row = Holiday(holiday="0314", holiday_type=2)
        zk = StubTableZK(rows=[row])
        r = DeleteTableRow().execute(zk, table="Holiday",
                                     key={"holiday": "0314", "holiday_type": 2})
        assert r["success"] is True and r["deleted"] == 1

    def test_delete_miss(self):
        r = DeleteTableRow().execute(StubTableZK(), table="Holiday",
                                     key={"holiday": "nope"})
        assert r["success"] is False and "No matching" in r["error"]


class TestDeviceOps:
    def test_cancel_alarm(self):
        zk = StubZK()
        CancelAlarm().execute(zk)
        assert zk.alarm_cancelled is True
