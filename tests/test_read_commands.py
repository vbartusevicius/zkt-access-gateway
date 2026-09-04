"""Read-command behaviour: batched parameter reads (few SDK round-trips) and
query-buffer escalation for wide tables."""
import pytest

from zk_commands.read import (DeviceParams, DoorParams, ReadTable,
                              _prop_meta, _batch_read_params, SDK_PARAMS_PER_CALL)
from zk_commands.spec import DOOR_PARAM_SPECS, DEVICE_PARAM_SPECS


class FakeSDK:
    """Records how many GetDeviceParam round-trips happen."""

    def __init__(self, values=None, fail=False):
        self.values = values or {}
        self.calls = []
        self.fail = fail

    def get_device_param(self, parameters, buffer_size):
        self.calls.append(tuple(parameters))
        if self.fail:
            raise RuntimeError("SDK error -112")
        assert len(parameters) <= SDK_PARAMS_PER_CALL, "exceeded SDK per-call limit"
        return {p: self.values.get(p, "0") for p in parameters}


def _real_param_objects():
    """Build real pyzkaccess parameter objects (no SDK calls on construction)."""
    from pyzkaccess.param import DeviceParameters, DoorParameters
    from pyzkaccess.device import ZK400
    sdk = FakeSDK()
    return sdk, DeviceParameters(sdk, ZK400), DoorParameters(sdk, ZK400, 1)


class TestPropMeta:
    def test_extracts_raw_query_template(self):
        _sdk, _dev, door = _real_param_objects()
        meta = _prop_meta(door, "lock_driver_time")
        assert meta is not None
        tpl, data_type, prop_type = meta
        assert tpl == "Door{self.door_number}Drivertime"
        assert data_type is int

    def test_device_param_template(self):
        _sdk, dev, _door = _real_param_objects()
        tpl, _dt, _pt = _prop_meta(dev, "ip_address")
        assert "IPAddress" in tpl or "ip" in tpl.lower()

    def test_unknown_property_returns_none(self):
        _sdk, dev, _door = _real_param_objects()
        assert _prop_meta(dev, "not_a_param") is None


class TestBatchedReads:
    def test_all_door_params_in_minimal_calls(self):
        from pyzkaccess.param import DoorParameters
        from pyzkaccess.device import ZK400
        sdk = FakeSDK()

        class ZK:
            pass
        zk = ZK()
        zk.sdk = sdk

        doors = [DoorParameters(sdk, ZK400, n) for n in (1, 2, 3, 4)]
        requests = [((i, s["name"]), d, s)
                    for i, d in enumerate(doors) for s in DOOR_PARAM_SPECS]

        results = _batch_read_params(zk, requests)

        # 4 doors x 13 params = 52 params; naive code did 52 round-trips
        assert len(results) == 52
        assert len(sdk.calls) <= 3, f"expected batched reads, got {len(sdk.calls)} calls"
        total_params = sum(len(c) for c in sdk.calls)
        assert total_params == 52

    def test_values_converted_by_spec_type(self):
        from pyzkaccess.param import DoorParameters
        from pyzkaccess.device import ZK400
        sdk = FakeSDK(values={"Door1Drivertime": "7", "Door1CloseAndLock": "1",
                              "Door1VerifyType": "4"})

        class ZK:
            pass
        zk = ZK()
        zk.sdk = sdk
        door = DoorParameters(sdk, ZK400, 1)
        specs = {s["name"]: s for s in DOOR_PARAM_SPECS}
        results = _batch_read_params(zk, [
            ("t", door, specs["lock_driver_time"]),
            ("l", door, specs["lock_on_close"]),
            ("v", door, specs["verify_mode"]),
        ])
        assert results["t"] == (7, "")
        assert results["l"] == (True, "")
        assert results["v"] == (4, "")  # select stays numeric for the UI

    def test_sdk_failure_is_reported_per_param_not_raised(self):
        from pyzkaccess.param import DoorParameters
        from pyzkaccess.device import ZK400
        sdk = FakeSDK(fail=True)

        class ZK:
            pass
        zk = ZK()
        zk.sdk = sdk
        door = DoorParameters(sdk, ZK400, 1)
        specs = {s["name"]: s for s in DOOR_PARAM_SPECS}
        results = _batch_read_params(zk, [("t", door, specs["lock_driver_time"])])
        value, error = results["t"]
        assert value is None and "-112" in error


class StubQuerySet:
    def __init__(self, rows, min_buffer, current):
        self.rows = rows
        self.min_buffer = min_buffer
        self.current = current

    def __iter__(self):
        # None means pyzkaccess auto-estimates (256 bytes/record) — model that
        # as a small buffer so wide tables still fail on it.
        effective = self.current if self.current is not None else 4096
        if effective < self.min_buffer:
            raise RuntimeError("GetDeviceData failed: unknown error -112")
        return iter(self.rows)


class BufferZK:
    """Fails table reads until the query buffer is large enough."""

    def __init__(self, min_buffer, rows=None):
        self.min_buffer = min_buffer
        self.query_buffer_size = None
        self.rows = rows if rows is not None else [_Row({"timezone_id": "1"})]
        self.attempts = []

    def table(self, name):
        self.attempts.append(self.query_buffer_size)
        return StubQuerySet(self.rows, self.min_buffer, self.query_buffer_size)


class _Row:
    def __init__(self, d): self._d = d

    @property
    def dict(self): return self._d


class TestReadTableBuffer:
    def test_wide_table_starts_with_large_buffer(self):
        zk = BufferZK(min_buffer=1 << 18)
        res = ReadTable().execute(zk, table="Timezone")
        assert res["rows"] == [{"timezone_id": "1"}]
        # succeeded on the very first attempt — no wasted round-trip
        assert zk.attempts == [1 << 18]

    def test_escalates_until_it_fits(self):
        zk = BufferZK(min_buffer=1 << 20)
        res = ReadTable().execute(zk, table="Timezone")
        assert "rows" in res
        assert zk.attempts == [1 << 18, 1 << 20]

    def test_narrow_table_uses_auto_buffer_first(self):
        zk = BufferZK(min_buffer=0)
        res = ReadTable().execute(zk, table="User")
        assert "rows" in res
        assert zk.attempts == [None]  # auto-estimate, pyzkaccess default

    def test_gives_up_with_clear_error(self):
        zk = BufferZK(min_buffer=1 << 30)
        res = ReadTable().execute(zk, table="Timezone")
        assert res["success"] is False
        assert "-112" in res["error"] and "larger buffers" in res["error"]

    def test_disallowed_table(self):
        res = ReadTable().execute(BufferZK(0), table="Secrets")
        assert res["success"] is False and "disallowed" in res["error"]
