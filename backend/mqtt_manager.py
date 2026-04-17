import os
import json
import logging
from paho.mqtt import client as mqtt_client

logger = logging.getLogger(__name__)

EVENT_TYPE_MAP = {
    0: "Normal Punch Open",
    1: "Punch during Normal Open",
    2: "First Card Normal Open",
    3: "Multi-Card Open",
    4: "Emergency Password Open",
    5: "Open during Normal Open",
    6: "Linkage Event Triggered",
    7: "Cancel Alarm",
    8: "Remote Opening",
    9: "Remote Closing",
    10: "Disable Intraday Normal Open",
    11: "Enable Intraday Normal Open",
    12: "Open Auxiliary Output",
    13: "Close Auxiliary Output",
    20: "Too Short Punch Interval",
    21: "Door Inactive Time Zone",
    22: "Illegal Time Zone",
    23: "Access Denied",
    24: "Anti-Passback",
    25: "Interlock",
    26: "Multi-Card Authentication",
    27: "Unregistered Card",
    28: "Opening Timeout",
    29: "Card Expired",
    30: "Password Error",
    200: "Door Open",
    201: "Door Closed",
    202: "Exit Button Open",
    203: "Door Open Too Long",
    204: "Forced Open Alarm",
    220: "Duress Password Open",
    221: "Opened Unexpectedly",
}


def _sanitize_id(s):
    import re
    return re.sub(r'[^a-zA-Z0-9]', '_', s).strip('_').lower()


class MQTTManager:
    def __init__(self):
        self.client = None
        self.connected = False
        self.device_id = "zkt_gateway"
        self.device_name = "ZKTeco Access Gateway"
        self.on_command_callback = None
        self._discovery_published = False
        self._availability_topic = f"zkt/{self.device_id}/availability"

    def connect(self, broker, port, user, password, serial="", on_command_callback=None):
        if not broker:
            return False

        if serial:
            self.device_id = f"zkt_{_sanitize_id(serial)}"
            self._availability_topic = f"zkt/{self.device_id}/availability"

        self.on_command_callback = on_command_callback
        self.client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION2,
            f"{self.device_id}_client"
        )

        if user:
            self.client.username_pw_set(user, password)

        self.client.will_set(self._availability_topic, "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        try:
            self.client.connect(broker, port)
            self.client.loop_start()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            self.connected = False
            return False

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info(f"Connected to MQTT Broker as {self.device_id}")
            self.connected = True
            self._discovery_published = False
            self.client.publish(self._availability_topic, "online", retain=True)
        else:
            logger.error(f"Failed to connect, return code {reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        logger.info("Disconnected from MQTT Broker")
        self.connected = False

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        if self.on_command_callback:
            self.on_command_callback(topic, payload)

    def _availability_config(self):
        return {
            "availability_topic": self._availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline"
        }

    def publish_hardware_discovery(self, hw_dict, doors_list=None):
        if not self.connected or self._discovery_published:
            return

        serial = hw_dict.get("serial_number", "")
        model = hw_dict.get("device_name", "Access Controller")
        avail = self._availability_config()
        active_doors = [d for d in (doors_list or []) if d.get("active")]

        # --- Main controller device ---
        controller_info = {
            "identifiers": [self.device_id],
            "name": self.device_name,
            "manufacturer": "ZKTeco",
            "model": model,
            "serial_number": serial
        }

        self.client.subscribe(f"zkt/{self.device_id}/+/set")

        # Connection Status
        self._publish_discovery("binary_sensor", "status", {
            "name": "Connection Status",
            "state_topic": f"zkt/{self.device_id}/status",
            "value_template": "{{ value_json.status }}",
            "payload_on": "Online",
            "payload_off": "Offline",
            "device_class": "connectivity",
        }, controller_info, avail)

        # Last Event
        self._publish_discovery("sensor", "last_event", {
            "name": "Last Event",
            "state_topic": f"zkt/{self.device_id}/event",
            "value_template": "{{ value_json.description }}",
            "json_attributes_topic": f"zkt/{self.device_id}/event",
            "icon": "mdi:door",
        }, controller_info, avail)

        # Last Card
        self._publish_discovery("sensor", "last_card", {
            "name": "Last Card",
            "state_topic": f"zkt/{self.device_id}/event",
            "value_template": "{{ value_json.card_id }}",
            "icon": "mdi:card-account-details",
        }, controller_info, avail)

        # Utility buttons
        for action, name, icon in [("reboot", "Reboot Controller", "mdi:restart"), ("sync_time", "Sync Time", "mdi:clock-sync")]:
            self._publish_discovery("button", action, {
                "name": name,
                "command_topic": f"zkt/{self.device_id}/{action}/set",
                "payload_press": "TRIGGER",
                "icon": icon,
            }, controller_info, avail)

        # Serial Number
        self._publish_discovery("sensor", "serial", {
            "name": "Serial Number",
            "state_topic": f"zkt/{self.device_id}/status",
            "value_template": "{{ value_json.serial_number }}",
            "icon": "mdi:identifier",
            "entity_category": "diagnostic",
        }, controller_info, avail)

        # IP Address
        self._publish_discovery("sensor", "ip", {
            "name": "IP Address",
            "state_topic": f"zkt/{self.device_id}/status",
            "value_template": "{{ value_json.ip }}",
            "icon": "mdi:ip-network",
            "entity_category": "diagnostic",
        }, controller_info, avail)

        # --- Per-active-door sub-devices ---
        for door in active_doors:
            did = door["door_id"]
            door_dev_id = f"{self.device_id}_door_{did}"

            door_info = {
                "identifiers": [door_dev_id],
                "name": f"{self.device_name} Door {did}",
                "manufacturer": "ZKTeco",
                "model": model,
                "via_device": self.device_id,
            }

            # Relay trigger
            self._publish_discovery("button", f"relay_{did}", {
                "name": "Trigger Relay",
                "command_topic": f"zkt/{self.device_id}/relay_{did}/set",
                "payload_press": "TRIGGER",
                "icon": "mdi:electric-switch",
            }, door_info, avail)

            # Verify mode
            self._publish_discovery("sensor", f"door_{did}_mode", {
                "name": "Verify Mode",
                "state_topic": f"zkt/{self.device_id}/door_{did}/state",
                "value_template": "{{ value_json.verify_mode }}",
                "icon": "mdi:shield-lock",
                "entity_category": "diagnostic",
            }, door_info, avail)

            # Sensor type
            self._publish_discovery("sensor", f"door_{did}_sensor", {
                "name": "Sensor Type",
                "state_topic": f"zkt/{self.device_id}/door_{did}/state",
                "value_template": "{{ value_json.sensor_type }}",
                "icon": "mdi:magnet",
                "entity_category": "diagnostic",
            }, door_info, avail)

            # Lock driver time
            self._publish_discovery("sensor", f"door_{did}_lock_time", {
                "name": "Lock Driver Time",
                "state_topic": f"zkt/{self.device_id}/door_{did}/state",
                "value_template": "{{ value_json.lock_driver_time }}",
                "icon": "mdi:timer-lock-outline",
                "entity_category": "diagnostic",
            }, door_info, avail)

            # Publish door state
            self.publish(f"zkt/{self.device_id}/door_{did}/state", {
                "verify_mode": door.get("verify_mode", "Unknown"),
                "sensor_type": door.get("sensor_type"),
                "lock_driver_time": door.get("lock_driver_time"),
                "lock_on_close": door.get("lock_on_close"),
            }, retain=True)

        self._discovery_published = True

    def _publish_discovery(self, component, object_id, config, device_info, avail):
        config["unique_id"] = f"{self.device_id}_{object_id}"
        config["device"] = device_info
        config.update(avail)
        self.publish(f"homeassistant/{component}/{self.device_id}/{object_id}/config", config, retain=True)

    def publish(self, topic, payload, retain=False):
        if not self.connected or not self.client:
            return False

        if isinstance(payload, dict):
            payload = json.dumps(payload)

        try:
            self.client.publish(topic, payload, retain=retain)
            return True
        except Exception as e:
            logger.error(f"Failed to publish to {topic}: {e}")
            return False

    def publish_status(self, is_connected, ip="", serial_number=""):
        payload = {
            "status": "Online" if is_connected else "Offline",
            "ip": ip,
            "serial_number": serial_number
        }
        self.publish(f"zkt/{self.device_id}/status", payload)

    def publish_event(self, timestamp, door_id, card_id, event_type):
        description = EVENT_TYPE_MAP.get(event_type, f"Unknown ({event_type})")
        payload = {
            "timestamp": timestamp,
            "door_id": door_id,
            "card_id": card_id,
            "event_type": event_type,
            "description": f"{description} - Door {door_id}"
        }
        self.publish(f"zkt/{self.device_id}/event", payload)


mqtt = MQTTManager()
