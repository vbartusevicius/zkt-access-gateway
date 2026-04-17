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


class MQTTManager:
    def __init__(self):
        self.client = None
        self.connected = False
        self.broker = ""
        self.port = 1883
        self.device_id = "zkt_gateway"
        self.device_name = "ZKTeco Access Gateway"
        self.on_command_callback = None
        self._discovery_published = False
        self._availability_topic = f"zkt/{self.device_id}/availability"

    def connect(self, broker, port, user, password, on_command_callback=None):
        if not broker:
            return False

        self.broker = broker
        self.port = port
        self.on_command_callback = on_command_callback
        self.client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, "zkt_gateway_client")

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
            logger.info("Connected to MQTT Broker!")
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

    def publish_hardware_discovery(self, hw_dict):
        if not self.connected or self._discovery_published:
            return

        serial = hw_dict.get("serial_number", "")
        device_info = {
            "identifiers": [self.device_id],
            "name": self.device_name,
            "manufacturer": "ZKTeco",
            "model": hw_dict.get("device_name", "Access Controller"),
            "serial_number": serial
        }
        avail = self._availability_config()

        self.client.subscribe(f"zkt/{self.device_id}/+/set")

        # Device connectivity — binary_sensor
        status_config = {
            "name": "Connection Status",
            "unique_id": f"{self.device_id}_status",
            "state_topic": f"zkt/{self.device_id}/status",
            "value_template": "{{ value_json.status }}",
            "payload_on": "Online",
            "payload_off": "Offline",
            "device_class": "connectivity",
            "device": device_info,
            **avail
        }
        self.publish(f"homeassistant/binary_sensor/{self.device_id}/status/config", status_config, retain=True)

        # Last Event sensor
        event_config = {
            "name": "Last Event",
            "unique_id": f"{self.device_id}_last_event",
            "state_topic": f"zkt/{self.device_id}/event",
            "value_template": "{{ value_json.description }}",
            "json_attributes_topic": f"zkt/{self.device_id}/event",
            "icon": "mdi:door",
            "device": device_info,
            **avail
        }
        self.publish(f"homeassistant/sensor/{self.device_id}/last_event/config", event_config, retain=True)

        # Relay trigger buttons — only for doors that actually exist
        door_count = hw_dict.get("door_count", 0)
        for i in range(1, door_count + 1):
            relay_config = {
                "name": f"Trigger Relay {i}" if door_count > 1 else "Trigger Relay",
                "unique_id": f"{self.device_id}_relay_{i}",
                "command_topic": f"zkt/{self.device_id}/relay_{i}/set",
                "payload_press": "TRIGGER",
                "icon": "mdi:electric-switch",
                "device": device_info,
                **avail
            }
            self.publish(f"homeassistant/button/{self.device_id}/relay_{i}/config", relay_config, retain=True)

        # Utility buttons
        for action, name, icon in [("reboot", "Reboot Controller", "mdi:restart"), ("sync_time", "Sync Time", "mdi:clock-sync")]:
            config = {
                "name": name,
                "unique_id": f"{self.device_id}_{action}",
                "command_topic": f"zkt/{self.device_id}/{action}/set",
                "payload_press": "TRIGGER",
                "icon": icon,
                "device": device_info,
                **avail
            }
            self.publish(f"homeassistant/button/{self.device_id}/{action}/config", config, retain=True)

        # Serial Number sensor
        sn_config = {
            "name": "Serial Number",
            "unique_id": f"{self.device_id}_serial",
            "state_topic": f"zkt/{self.device_id}/status",
            "value_template": "{{ value_json.serial_number }}",
            "icon": "mdi:identifier",
            "entity_category": "diagnostic",
            "device": device_info,
            **avail
        }
        self.publish(f"homeassistant/sensor/{self.device_id}/serial/config", sn_config, retain=True)

        # IP Address sensor
        ip_config = {
            "name": "IP Address",
            "unique_id": f"{self.device_id}_ip",
            "state_topic": f"zkt/{self.device_id}/status",
            "value_template": "{{ value_json.ip }}",
            "icon": "mdi:ip-network",
            "entity_category": "diagnostic",
            "device": device_info,
            **avail
        }
        self.publish(f"homeassistant/sensor/{self.device_id}/ip/config", ip_config, retain=True)

        self._discovery_published = True

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
            "description": f"{description} — Door {door_id}"
        }
        self.publish(f"zkt/{self.device_id}/event", payload)


mqtt = MQTTManager()
