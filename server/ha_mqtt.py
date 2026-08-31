import json
import threading
import time
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt


class HAMQTTBridge:
    def __init__(self, store, command_callback):
        self.store = store
        self.command_callback = command_callback
        self.path = Path(store.root) / "ha_mqtt.json"
        self.status_path = Path(store.root) / "ha_mqtt_status.json"
        self.lock = threading.RLock()
        self.client = None
        self.connected = False
        self.error = ""
        self.last_states = {}
        self.config = self._read_config()
        self.last_connected = self._read_last_connected()

    def _read_last_connected(self):
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8")).get("last_connected")
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _read_config(self):
        defaults = {"host": "", "port": 1883, "username": "", "password": "", "discovery_prefix": "homeassistant", "topic_prefix": "mttl"}
        try:
            defaults.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return defaults

    def public_config(self):
        with self.lock:
            value = {key: self.config.get(key) for key in ("host", "port", "username", "discovery_prefix", "topic_prefix")}
            value.update({"configured": bool(self.config.get("host")), "has_password": bool(self.config.get("password")), "connected": self.connected, "error": self.error, "last_connected": self.last_connected})
            return value

    def save_config(self, value):
        host = str(value.get("host", "")).strip()
        port = int(value.get("port", 1883))
        if not 1 <= port <= 65535:
            raise ValueError("invalid MQTT port")
        config = {
            "host": host,
            "port": port,
            "username": str(value.get("username", "")).strip(),
            "password": self.config.get("password", "") if value.get("password") in (None, "") else str(value["password"]),
            "discovery_prefix": str(value.get("discovery_prefix", "homeassistant")).strip() or "homeassistant",
            "topic_prefix": str(value.get("topic_prefix", "mttl")).strip().strip("/") or "mttl",
        }
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        with self.lock:
            self.config = config
        self.restart()
        return self.public_config()

    def start(self):
        threading.Thread(target=self._publisher, daemon=True, name="ha-mqtt-publisher").start()
        self.restart()

    def restart(self):
        with self.lock:
            old = self.client
            self.client = None
            self.connected = False
            self.error = ""
        if old:
            old.loop_stop()
            old.disconnect()
        if not self.config.get("host"):
            return
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="mttl-local-bridge", clean_session=True)
            if self.config.get("username"):
                client.username_pw_set(self.config["username"], self.config.get("password", ""))
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            with self.lock:
                self.client = client
            client.connect_async(self.config["host"], int(self.config["port"]), 30)
            client.loop_start()
        except Exception as error:
            with self.lock:
                self.error = str(error)

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            with self.lock:
                self.error = f"connection refused: {reason_code}"
            return
        with self.lock:
            self.connected = True
            self.error = ""
            self.last_connected = datetime.now().astimezone().isoformat()
            prefix = self.config["topic_prefix"]
            try:
                temporary = self.status_path.with_suffix(".json.tmp")
                temporary.write_text(json.dumps({"last_connected": self.last_connected}), encoding="utf-8")
                temporary.replace(self.status_path)
            except OSError:
                pass
        client.subscribe(f"{prefix}/+/set/+", qos=1)
        self.last_states.clear()
        for device in self.store.list_devices():
            if device.get("ha_link"):
                self.publish_discovery(device)
                self.publish_state(device, force=True)

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties):
        with self.lock:
            self.connected = False
            if reason_code != 0:
                self.error = f"disconnected: {reason_code}"

    def _on_message(self, _client, _userdata, message):
        try:
            parts = message.topic.split("/")
            mac7, target = parts[-3].upper(), parts[-1].lower()
            device = next(item for item in self.store.list_devices() if item["mac"].endswith(mac7) and item.get("ha_link"))
            value = message.payload.decode().strip().upper()
            if value not in ("ON", "OFF"):
                return
            number = 0 if target == "all" else int(target.removeprefix("sw"))
            command = "POWER_SET" if number == 0 else f"POWER{number}_SET"
            self.command_callback(device["mac"], command, "FF" if value == "ON" else "00")
        except (StopIteration, ValueError, KeyError, RuntimeError):
            return

    def _publish(self, topic, payload, retain=True):
        with self.lock:
            client, connected = self.client, self.connected
        if client and connected:
            client.publish(topic, payload, qos=1, retain=retain)

    def publish_discovery(self, device, remove=False):
        mac, mac7 = device["mac"], device["mac"][-7:].lower()
        with self.lock:
            discovery, prefix = self.config["discovery_prefix"], self.config["topic_prefix"]
        base = f"{prefix}/{mac7}"
        identifiers = [f"mttl_{mac7}"]
        device_info = {"identifiers": identifiers, "name": device["name"], "manufacturer": "LG U+", "model": "MTTL-W01", "sw_version": device.get("firmware", {}).get("version", "Unknown")}
        entities = []
        for number in range(5):
            suffix = "all" if number == 0 else f"sw{number}"
            object_id = f"mttl_{mac7}_{suffix}"
            channel_name = device["channels"][number - 1] if number else None
            name = "SW All" if number == 0 else (f"SW {number}" if channel_name == str(number) else channel_name)
            entities.append(("switch", object_id, {"name": name, "command_topic": f"{base}/set/{suffix}", "state_topic": f"{base}/state", "value_template": "{{ value_json.%s }}" % suffix}))
        for number in range(5):
            suffix = "powerall" if number == 0 else f"power{number}"
            object_id = f"mttl_{mac7}_{suffix}"
            channel_name = device["channels"][number - 1] if number else None
            name = "Power All" if number == 0 else (f"Power {number}" if channel_name == str(number) else f"{channel_name} Power")
            entities.append(("sensor", object_id, {"name": name, "state_topic": f"{base}/state", "value_template": "{{ value_json.%s }}" % suffix, "unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"}))
        today_usage_id = f"mttl_{mac7}_today_usage"
        entities.append(("sensor", today_usage_id, {"name": "Today Usage", "state_topic": f"{base}/state", "value_template": "{{ value_json.today_usage }}", "unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"}))
        for component, object_id, config in entities:
            topic = f"{discovery}/{component}/{object_id}/config"
            if remove:
                self._publish(topic, "")
                continue
            config.update({"object_id": object_id, "unique_id": object_id, "default_entity_id": f"{component}.{object_id}", "device": device_info, "availability_topic": f"{base}/availability"})
            self._publish(topic, json.dumps(config, separators=(",", ":")))

    def publish_state(self, device, force=False):
        mac7 = device["mac"][-7:].lower()
        state = device.get("state", {})
        channels = state.get("channels", [{}, {}, {}, {}])
        payload = {
            "all": "ON" if state.get("main_on") else "OFF",
            "powerall": state.get("power_w", 0),
            "today_usage": device.get("energy", {}).get("today_kwh"),
        }
        for number in range(1, 5):
            channel = channels[number - 1] if len(channels) >= number else {}
            payload[f"sw{number}"] = "ON" if channel.get("on") else "OFF"
            payload[f"power{number}"] = channel.get("power_w", 0)
        encoded = json.dumps(payload, separators=(",", ":"))
        if force or self.last_states.get(device["mac"]) != encoded:
            self._publish(f"{self.config['topic_prefix']}/{mac7}/state", encoded)
            self.last_states[device["mac"]] = encoded
        self._publish(f"{self.config['topic_prefix']}/{mac7}/availability", "online" if state.get("online") else "offline")

    def set_link(self, mac, enabled):
        device = self.store.read("devices", mac)
        if not device:
            raise KeyError("device not found")
        if device.get("ha_link") and not enabled:
            expanded = {**device, "state": self.store.read("state", mac, {}), "firmware": self.store.read("firmware", mac, {})}
            self.publish_discovery(expanded, remove=True)
        device["ha_link"] = bool(enabled)
        self.store.write("devices", mac, device)
        if enabled:
            expanded = next(item for item in self.store.list_devices() if item["mac"] == mac)
            self.publish_discovery(expanded)
            self.publish_state(expanded, force=True)
        return bool(enabled)

    def remove_device(self, mac):
        device = next((item for item in self.store.list_devices() if item["mac"] == mac), None)
        if device and device.get("ha_link"):
            self.publish_discovery(device, remove=True)

    def republish_device(self, mac):
        device = next((item for item in self.store.list_devices() if item["mac"] == mac), None)
        if device and device.get("ha_link"):
            self.publish_discovery(device)
            self.publish_state(device, force=True)

    def _publisher(self):
        while True:
            time.sleep(2)
            for device in self.store.list_devices():
                if device.get("ha_link"):
                    self.publish_state(device)
