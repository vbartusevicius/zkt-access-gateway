"""MQTT manager: HA discovery payloads, event mapping, reconnect resilience."""
import json

import pytest

from pyzkaccess.enums import EVENT_TYPES as PYZK_EVENT_TYPES

from backend.mqtt_manager import MQTTManager, EVENT_TYPE_MAP


class RecordingClient:
    def __init__(self):
        self.published = []
        self.subscribed = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

    def subscribe(self, topic):
        self.subscribed.append(topic)


@pytest.fixture()
def mgr():
    m = MQTTManager()
    m.device_id = "zkt_test"
    m._availability_topic = "zkt/zkt_test/availability"
    m.client = RecordingClient()
    m.connected = True
    return m


class TestEventTypeMap:
    def test_covers_every_sdk_event_type(self):
        # 255 is the sentinel the SDK returns for "no new events" — never data
        missing = [k for k in PYZK_EVENT_TYPES if k not in EVENT_TYPE_MAP and k != 255]
        assert not missing, f"unmapped event types: {missing}"

    def test_relabeled_codes(self):
        assert EVENT_TYPE_MAP[23] == "Access Denied"
        assert EVENT_TYPE_MAP[27] == "Unregistered Card"
        assert EVENT_TYPE_MAP[206] == "Device Start"


class TestPublishEvent:
    def test_payload_includes_user_name(self, mgr):
        mgr.publish_event("2026-09-03T10:00:00", 1, "16268812", 0, user_name="Jane Doe")
        topic, payload, retain = mgr.client.published[-1]
        body = json.loads(payload)
        assert topic == "zkt/zkt_test/door_1/event"
        assert body["user_name"] == "Jane Doe"
        assert body["description"] == "Normal Punch Open"

    def test_contact_state_updates(self, mgr):
        mgr.publish_event("t", 2, "", 200, "")
        mgr.publish_event("t", 2, "", 201, "")
        topics = [p[0] for p in mgr.client.published if p[0].endswith("/contact")]
        assert topics == ["zkt/zkt_test/door_2/contact"] * 2
        assert mgr.client.published[-1][2] is True  # retained

    def test_disconnected_publish_is_noop(self):
        m = MQTTManager()
        assert m.publish("t", {}) is False


class TestDiscovery:
    def test_per_door_entities(self, mgr):
        mgr.publish_hardware_discovery(
            {"serial_number": "SN1", "device_name": "C3-400"},
            [{"door_id": 1, "active": True, "aux_relay_count": 1, "verify_mode": "only_card",
              "reader": "Reader 1"}],
        )
        topics = [p[0] for p in mgr.client.published]
        assert "homeassistant/sensor/zkt_test/door_1_last_user/config" in topics
        assert "homeassistant/sensor/zkt_test/door_1_last_card/config" in topics
        assert "homeassistant/binary_sensor/zkt_test/door_1_contact/config" in topics
        assert "homeassistant/button/zkt_test/relay_1/config" in topics
        assert "homeassistant/button/zkt_test/aux_1/config" in topics
        assert "homeassistant/button/zkt_test/cancel_alarm/config" in topics

        # inactive doors get no entities
        assert "door_2_last_user" not in " ".join(topics)

    def test_unique_ids_stable(self, mgr):
        mgr.publish_hardware_discovery({"serial_number": "SN1"}, [
            {"door_id": 1, "active": True, "aux_relay_count": 0}])
        uids = [json.loads(p[1])["unique_id"] for p in mgr.client.published
                if p[0].startswith("homeassistant/")]
        assert len(uids) == len(set(uids))


class TestReconnectResilience:
    def test_subscriptions_replayed_on_connect(self, mgr):
        mgr.subscribe("zkt/zkt_test/+/set")
        mgr.client.subscribed.clear()  # simulate broker restart

        mgr._on_connect(mgr.client, None, None, 0, None)
        assert "zkt/zkt_test/+/set" in mgr.client.subscribed
        assert mgr.connected is True
        # availability announced online
        assert mgr.client.published[-1][0] == "zkt/zkt_test/availability"
        assert mgr.client.published[-1][1] == "online"
