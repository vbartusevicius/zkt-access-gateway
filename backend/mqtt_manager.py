import os
import json
import logging
from paho.mqtt import client as mqtt_client

logger = logging.getLogger(__name__)

class MQTTManager:
    def __init__(self):
        self.client = None
        self.connected = False
        self.broker = ""
        self.port = 1883
        self.device_id = "zkt_gateway"
        self.device_name = "ZKTeco Access Gateway"

    def connect(self, broker, port, user, password):
        if not broker:
            return False
            
        self.broker = broker
        self.port = port
        self.client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, "zkt_gateway_client")

        if user:
            self.client.username_pw_set(user, password)
            
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

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
            self._publish_ha_discovery()
        else:
            logger.error(f"Failed to connect, return code {reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        logger.info("Disconnected from MQTT Broker")
        self.connected = False

    def _publish_ha_discovery(self):
        # Publish HA Discovery payloads
        device_info = {
            "identifiers": [self.device_id],
            "name": self.device_name,
            "manufacturer": "ZKTeco",
            "model": "Access Controller Gateway"
        }

        # Status Sensor
        status_config = {
            "name": "Connection Status",
            "unique_id": f"{self.device_id}_status",
            "state_topic": f"zkt/{self.device_id}/status",
            "value_template": "{{ value_json.status }}",
            "device": device_info
        }
        self.publish(f"homeassistant/sensor/{self.device_id}/status/config", status_config, retain=True)

        # Last Event Sensor
        event_config = {
            "name": "Last Event",
            "unique_id": f"{self.device_id}_last_event",
            "state_topic": f"zkt/{self.device_id}/event",
            "value_template": "{{ value_json.description }}",
            "json_attributes_topic": f"zkt/{self.device_id}/event",
            "icon": "mdi:door",
            "device": device_info
        }
        self.publish(f"homeassistant/sensor/{self.device_id}/last_event/config", event_config, retain=True)

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

    def publish_status(self, is_connected, ip=""):
        payload = {
            "status": "Online" if is_connected else "Offline",
            "ip": ip
        }
        self.publish(f"zkt/{self.device_id}/status", payload)

    def publish_event(self, timestamp, door_id, card_id, event_type):
        payload = {
            "timestamp": timestamp,
            "door_id": door_id,
            "card_id": card_id,
            "event_type": event_type,
            "description": f"Event {event_type} on Door {door_id}"
        }
        self.publish(f"zkt/{self.device_id}/event", payload)

mqtt = MQTTManager()
