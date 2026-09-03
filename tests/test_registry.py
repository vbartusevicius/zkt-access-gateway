"""Registry integrity: the command surface is the single source of truth for
the CLI dispatcher, REST routes and MQTT topics, so it deserves hard checks."""
import json

import pytest

from zk_commands import REGISTRY, ReadCommand, WriteCommand
from zk_commands.spec import WRITABLE_TABLES, TABLE_SCHEMAS, DOOR_PARAM_SPECS, DEVICE_PARAM_SPECS


def test_all_commands_registered_unique_names():
    assert 15 <= len(REGISTRY) <= 40
    assert len(REGISTRY) == len({c.name for c in REGISTRY.values()})

    for name, cls in REGISTRY.items():
        assert cls.name == name
        assert issubclass(cls, (ReadCommand, WriteCommand))


def test_generated_routes_have_valid_metadata():
    for cls in REGISTRY.values():
        if cls.http_path:
            assert not cls.http_path.startswith("/")
            assert cls.http_method in ("get", "post", "delete")
            # path template placeholders must be declared args
            for part in cls.http_path.split("/"):
                if part.startswith("{"):
                    assert part.strip("{}") in cls.args, f"{cls.name}: {part} not in args"


def test_mqtt_topics_are_write_commands():
    for cls in REGISTRY.values():
        if cls.mqtt_topic:
            assert cls.kind == "write"
            for part in cls.mqtt_topic.split("/"):
                if part.startswith("{"):
                    assert part.strip("{}") in cls.args


def test_known_command_surface():
    expected = {"state_dump", "poll_events", "rt_events", "test", "create_user",
                "delete_user", "trigger_relay", "trigger_aux", "restart", "sync_time",
                "cancel_alarm", "set_device_param", "set_door_param", "search_devices",
                "device_params", "door_params", "read_table", "upsert_table_row",
                "delete_table_row"}
    assert expected == set(REGISTRY)


def test_search_devices_is_the_only_connectionless_command():
    assert {c.name for c in REGISTRY.values() if not c.needs_connection} == {"search_devices"}


def test_writable_tables_have_schemas():
    for table in WRITABLE_TABLES:
        assert table in TABLE_SCHEMAS, f"schema missing for {table}"
        assert any(f.get("key") for f in TABLE_SCHEMAS[table]["fields"]), f"no key field for {table}"


def test_param_specs_present():
    assert len(DOOR_PARAM_SPECS) >= 11
    assert len(DEVICE_PARAM_SPECS) >= 18
    assert all("type" in s and "name" in s and "label" in s
               for s in DOOR_PARAM_SPECS + DEVICE_PARAM_SPECS)


class TestValidate:
    def test_coercion_and_filtering(self):
        kw = REGISTRY["create_user"].validate({
            "pin": 42, "card": "abc", "super_authorize": "true",
            "doors": "5", "name": "not declared", "junk": None,
        })
        assert kw == {"pin": "42", "card": "abc", "super_authorize": True, "doors": 5}

    def test_complex_payloads_pass_through(self):
        data = {"holiday": "0101", "holiday_type": 1}
        kw = REGISTRY["upsert_table_row"].validate({"table": "Holiday", "data": data})
        assert kw["data"] is data  # not mangled to str

    def test_none_values_dropped_so_command_defaults_apply(self):
        kw = REGISTRY["trigger_relay"].validate({"relay_id": 2, "duration": None})
        assert kw == {"relay_id": 2}


class TestDispatcherArgparse:
    def test_choices_match_registry(self):
        from zk_client import build_parser
        parser = build_parser()
        actions = {a.dest: a for a in parser._actions}
        assert set(actions["action"].choices) == set(REGISTRY)

    def test_cli_roundtrip_with_json_payload(self):
        from zk_client import build_parser
        args = build_parser().parse_args([
            "--connstr", "x", "--action", "upsert_table_row", "--table", "Holiday",
            "--data", json.dumps({"holiday": "0314"}),
        ])
        kw = REGISTRY[args.action]().validate(vars(args))
        assert kw == {"table": "Holiday", "data": '{"holiday": "0314"}'}

    def test_bool_flags_store_true(self):
        from zk_client import build_parser
        args = build_parser().parse_args(
            ["--connstr", "x", "--action", "create_user", "--pin", "9", "--super_authorize"])
        kw = REGISTRY[args.action]().validate(vars(args))
        assert kw["super_authorize"] is True
