import base64
import json
import os
import socket
import ssl
import threading
import time
from datetime import datetime


def remaining(length):
    output = bytearray()
    while True:
        value = length % 128
        length //= 128
        output.append(value | (0x80 if length else 0))
        if not length:
            return bytes(output)


def body_offset(packet):
    index = 1
    while packet[index] & 0x80:
        index += 1
    return index + 1


def read_packet(connection):
    first = connection.recv(1)
    if not first:
        return b""
    packet = bytearray(first)
    multiplier = 1
    length = 0
    while True:
        byte = connection.recv(1)
        if not byte:
            return bytes(packet)
        packet += byte
        length += (byte[0] & 127) * multiplier
        if not byte[0] & 128:
            break
        multiplier *= 128
    while length:
        chunk = connection.recv(length)
        if not chunk:
            break
        packet += chunk
        length -= len(chunk)
    return bytes(packet)


def mqtt_string(data, offset):
    length = int.from_bytes(data[offset : offset + 2], "big")
    start = offset + 2
    return data[start : start + length].decode("utf-8", "replace"), start + length


def connect_identity(packet):
    offset = body_offset(packet)
    _, offset = mqtt_string(packet, offset)
    offset += 4  # protocol level, flags, keepalive
    client_id, _ = mqtt_string(packet, offset)
    return client_id


class DeviceSession:
    def __init__(self, server, connection, address, entity, device):
        self.server = server
        self.connection = connection
        self.address = address
        self.entity = entity
        self.device = device
        self.mac = device["mac"]
        self.lock = threading.RLock()
        self.command_topic = None
        self.connected_at = time.time()
        self.last_seen = time.time()

    def send(self, content):
        topic = self.command_topic
        if not topic:
            raise RuntimeError("device subscriptions are not ready")
        topic_bytes = topic.encode()
        payload = json.dumps(content, separators=(",", ":")).encode()
        body = len(topic_bytes).to_bytes(2, "big") + topic_bytes + payload
        with self.lock:
            self.connection.sendall(b"\x30" + remaining(len(body)) + body)

    def control(self, command, value=None):
        request_id = f"local-control-{time.time_ns()}"
        if command == "STATUS_GET":
            command_id = 2
            parameters = [{"command": command, "filter": "ALL"}]
        elif command.endswith("_GET"):
            command_id = 2
            parameters = [{"command": command}]
        else:
            command_id = 1
            parameter = {"command": command}
            if command == "POWER_SET":
                parameter["switchBinary"] = value
            else:
                channel = command.removeprefix("POWER").removesuffix("_SET")
                parameter[f"switchBinary{channel}"] = value
            parameters = [parameter]
        inner = {
            "header": {
                "version": "v2",
                "vendor_code": "0000564",
                "api_key": "device_control",
                "session_id": request_id,
                "device_id": self.mac,
                "device_type": "MULTITAP",
                "device_model": "MTTL-W01",
                "device_uuid": self.device["uuid"],
            },
            "type": "control",
            "content": {"cmd_request": {"cmd_id": command_id, "parameters": parameters}},
        }
        outer = {
            "op": "1",
            "to": f"/{self.entity}",
            "fr": "/IN_CSE-BASE-1",
            "rqi": request_id,
            "ty": "4",
            "pc": {"m2m:cin": {
                "cnf": "text/plain: 0",
                "con": base64.b64encode(json.dumps(inner, separators=(",", ":")).encode()).decode(),
            }},
        }
        self.send(outer)
        self.server.store.append_event({"mac": self.mac, "kind": "command", "command": command, "value": value})
        return request_id


class MQTTServer:
    def __init__(self, store, registry, host="0.0.0.0", port=18832, cert_dir="/certs",
                 poll_interval=15, offline_timeout=45):
        self.store = store
        self.registry = registry
        self.host = host
        self.port = port
        self.poll_interval = poll_interval
        self.offline_timeout = offline_timeout
        self.sessions = {}
        self.sessions_lock = threading.RLock()
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.maximum_version = ssl.TLSVersion.TLSv1_2
        self.context.set_ciphers("AES256-SHA256:AES128-SHA256:@SECLEVEL=0")
        self.context.load_cert_chain(os.path.join(cert_dir, "brk2.crt"), os.path.join(cert_dir, "brk2.key"))

    def start(self):
        threading.Thread(target=self._listen, daemon=True, name="mqtt-listener").start()
        threading.Thread(target=self._poll, daemon=True, name="mqtt-poller").start()

    def command(self, mac, command, value=None):
        with self.sessions_lock:
            session = self.sessions.get(mac)
        if not session:
            raise KeyError("device offline")
        return session.control(command, value)

    def disconnect(self, mac):
        with self.sessions_lock:
            session = self.sessions.pop(mac, None)
        if session:
            try:
                session.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                session.connection.close()
            except OSError:
                pass

    def _poll(self):
        while True:
            time.sleep(self.poll_interval)
            with self.sessions_lock:
                sessions = list(self.sessions.values())
            for session in sessions:
                if time.time() - session.last_seen >= self.offline_timeout:
                    self._expire(session)
                    continue
                try:
                    session.control("STATUS_GET")
                except (OSError, RuntimeError):
                    self._expire(session)

    def _expire(self, session):
        with self.sessions_lock:
            if self.sessions.get(session.mac) is not session:
                return
            self.sessions.pop(session.mac, None)
        self._set_online(session, False)
        try:
            session.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            session.connection.close()
        except OSError:
            pass

    def _listen(self):
        with socket.create_server((self.host, self.port)) as listener:
            while True:
                raw, address = listener.accept()
                threading.Thread(target=self._handle, args=(raw, address), daemon=True).start()

    def _handle(self, raw, address):
        session = None
        connection = None
        try:
            connection = self.context.wrap_socket(raw, server_side=True)
            packet = read_packet(connection)
            if not packet or packet[0] >> 4 != 1:
                return
            entity = connect_identity(packet)
            device = self.registry.by_entity(entity)
            if not device:
                prefix, suffix = "ASN_CSE-D-local-", "-MTAP"
                if not (entity.startswith(prefix) and entity.endswith(suffix)):
                    raise ValueError("unsupported client ID")
                mac = entity[len(prefix) : -len(suffix)]
                if not self.registry.consume_pending_enrollment(mac):
                    raise ValueError("device must be provisioned before registration")
                device = self.registry.enroll(mac)
            session = DeviceSession(self, connection, address, entity, device)
            with self.sessions_lock:
                previous = self.sessions.get(session.mac)
                self.sessions[session.mac] = session
            if previous:
                try:
                    previous.connection.close()
                except OSError:
                    pass
            self._set_online(session, True)
            connection.sendall(b"\x20\x02\x00\x00")
            while True:
                packet = read_packet(connection)
                if not packet:
                    break
                session.last_seen = time.time()
                self._packet(session, packet)
        except Exception as error:
            print(f"MQTT {address[0]} {type(error).__name__}: {error}", flush=True)
        finally:
            if session:
                mark_offline = False
                with self.sessions_lock:
                    if self.sessions.get(session.mac) is session:
                        self.sessions.pop(session.mac, None)
                        mark_offline = True
                if mark_offline:
                    self._set_online(session, False)
            if connection:
                connection.close()
            else:
                raw.close()

    def _set_online(self, session, online):
        if not self.store.read("devices", session.mac):
            return
        state = self.store.read("state", session.mac, {})
        state.update({
            "online": online,
            "ip": session.address[0],
            "last_seen": datetime.now().astimezone().isoformat(),
        })
        self.store.write("state", session.mac, state)

    def _packet(self, session, packet):
        packet_type = packet[0] >> 4
        offset = body_offset(packet)
        if packet_type == 8:
            packet_id = packet[offset : offset + 2]
            cursor = offset + 2
            grants = []
            while cursor + 2 <= len(packet):
                topic, cursor = mqtt_string(packet, cursor)
                if cursor >= len(packet):
                    break
                grants.append(packet[cursor])
                cursor += 1
                if topic.startswith("/oneM2M/req/IN_CSE-BASE-1/"):
                    session.command_topic = topic
            connection = session.connection
            with session.lock:
                connection.sendall(bytes((0x90, len(packet_id) + len(grants))) + packet_id + bytes(grants))
            if session.command_topic:
                threading.Timer(2, self._safe_status, args=(session,)).start()
        elif packet_type == 3:
            topic, payload, packet_id = self._publish(packet, offset)
            if packet_id:
                with session.lock:
                    session.connection.sendall(b"\x40\x02" + packet_id)
            self._onem2m(session, topic, payload)
        elif packet_type == 12:
            with session.lock:
                session.connection.sendall(b"\xd0\x00")
            self._set_online(session, True)

    def _safe_status(self, session):
        try:
            session.control("STATUS_GET")
        except (OSError, RuntimeError):
            pass

    @staticmethod
    def _publish(packet, offset):
        topic, cursor = mqtt_string(packet, offset)
        qos = (packet[0] >> 1) & 3
        packet_id = packet[cursor : cursor + 2] if qos else None
        if qos:
            cursor += 2
        return topic, packet[cursor:], packet_id

    def _send_response(self, session, topic, response):
        parts = topic.split("/")
        response_topic = f"/oneM2M/resp/{parts[3]}/{parts[4]}"
        topic_bytes = response_topic.encode()
        payload = json.dumps(response, separators=(",", ":")).encode()
        body = len(topic_bytes).to_bytes(2, "big") + topic_bytes + payload
        with session.lock:
            session.connection.sendall(b"\x30" + remaining(len(body)) + body)

    def _onem2m(self, session, topic, payload):
        try:
            message = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if "/oneM2M/resp/" in topic:
            self._application_report(session, message)
            return
        # Device-originated status and physical-button notifications are
        # contentInstance CREATE requests and still need an oneM2M response.
        self._application_report(session, message)
        rqi = message.get("rqi")
        if not rqi:
            return
        if rqi == "cseBaseRetrieve":
            response = {"rsc": 2000, "rqi": rqi, "pc": {"m2m:cb": {"rn": "cb-1", "csi": "/IN_CSE-BASE-1"}}}
        elif rqi == "remoteCSERetrieve":
            response = {"rsc": 2000, "rqi": rqi, "pc": {"m2m:csr": {"ri": f"csr-{session.mac}"}}}
        else:
            response = {"rsc": 2001, "rqi": rqi}
            content = message.get("pc")
            if message.get("op") == "1" and isinstance(content, dict) and content:
                kind = next(iter(content))
                response["pc"] = {kind: {"rn": message.get("nm", f"local-{rqi}"), "ri": f"ri-{rqi}-{session.mac}"}}
            if rqi == "smartplugbootstrap":
                inner = {
                    "header": {"version": "v2", "vendor_code": "0000564", "ret_code": "200", "api_key": "device_bootstrap", "device_id": session.mac, "device_uuid": session.device["uuid"], "device_type": "MULTITAP", "device_model": "MTTL-W01"},
                    "type": "data", "content": {"device": {"uuid": session.device["uuid"]}},
                }
                response["pc"]["m2m:cin"]["con"] = base64.b64encode(json.dumps(inner, separators=(",", ":")).encode()).decode()
        response["to"] = message.get("fr", "")
        response["fr"] = message.get("to", "/IN_CSE-BASE-1")
        self._send_response(session, topic, response)
        self.store.append_event({"mac": session.mac, "kind": "onem2m", "rqi": rqi, "rsc": response["rsc"]})

    def _application_report(self, session, message):
        try:
            encoded = message["pc"]["m2m:cin"]["con"]
            report = json.loads(base64.b64decode(encoded))
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            return
        content = report.get("content", {})
        parameters = content.get("cmd_report", {}).get("parameters")
        if parameters:
            self._status(session, parameters, report)
        notification = content.get("notification", {})
        if notification.get("parameters"):
            self._events(session, notification["parameters"])

    @staticmethod
    def _watts(raw):
        try:
            return round(int(raw, 16) / 100, 2)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _kilowatt_hours(raw):
        # meter_00 uses the device's cumulative 0.001 kWh counter. Keep the
        # original value alongside this display value so scaling can be
        # corrected later without losing source data.
        try:
            return round(int(raw, 16) / 1000, 3)
        except (TypeError, ValueError):
            return None

    def _status(self, session, parameters, report):
        state = self.store.read("state", session.mac, {"channels": [{}, {}, {}, {}]})
        state.setdefault("channels", [{}, {}, {}, {}])
        for item in parameters:
            command = item.get("command")
            if command == "STATUS_REPORT":
                state["main_on"] = item.get("switchBinary") == "FF"
                state["power_w"] = self._watts(item.get("meter_02"))
                state["rssi"] = int(item["RSSI"]) if item.get("RSSI") else None
            elif command and command.startswith("STATUS") and command.endswith("_REPORT"):
                number = command[len("STATUS") : -len("_REPORT")]
                if number.isdigit() and 1 <= int(number) <= 4:
                    index = int(number) - 1
                    state["channels"][index].update({
                        "on": item.get(f"switchBinary{number}") == "FF",
                        "power_w": self._watts(item.get(f"meter{number}_02")),
                        "raw_power": item.get(f"meter{number}_02"),
                    })
            elif command == "METER_ACC_STATUS_REPORT":
                self._energy(session, item)
        state.update({"online": True, "last_seen": datetime.now().astimezone().isoformat()})
        self.store.write("state", session.mac, state)
        self.store.append_event({"mac": session.mac, "kind": "status", "state": state})

    def _events(self, session, parameters):
        state = self.store.read("state", session.mac, {"channels": [{}, {}, {}, {}]})
        state.setdefault("channels", [{}, {}, {}, {}])
        for item in parameters:
            command = item.get("command", "")
            if command == "POWER_EVENT":
                state["main_on"] = item.get("switchBinary") == "FF"
                for number in range(1, 5):
                    state["channels"][number - 1]["on"] = item.get(f"switchBinary{number}") == "FF"
            elif command.startswith("POWER") and command.endswith("_EVENT"):
                number = command[len("POWER") : -len("_EVENT")]
                if number.isdigit() and 1 <= int(number) <= 4:
                    state["channels"][int(number) - 1]["on"] = item.get(f"switchBinary{number}") == "FF"
            elif command == "METER_CUR_STATUS_EVENT":
                state["power_w"] = self._watts(item.get("meter_02"))
                for number in range(1, 5):
                    state["channels"][number - 1]["power_w"] = self._watts(item.get(f"meter{number}_02"))
            elif command in ("METER_ACC_STATUS_EVENT", "METER_ACC_STATUS_REPORT"):
                self._energy(session, item)
            self.store.append_event({"mac": session.mac, "kind": "physical", "payload": item})
        state.update({"online": True, "last_seen": datetime.now().astimezone().isoformat()})
        self.store.write("state", session.mac, state)

    def _energy(self, session, item):
        now = datetime.now().astimezone()
        energy = self.store.read("energy", session.mac, {})
        if energy.get("month") != f"{now:%Y-%m}":
            energy = {"month": f"{now:%Y-%m}", "month_estimated": 0.0}
        energy.update({
            "date": f"{now:%Y-%m-%d}",
            "today_raw": item.get("meter_00"),
            "yesterday_raw": item.get("premeter_00"),
            "today_kwh": self._kilowatt_hours(item.get("meter_00")),
            "yesterday_kwh": self._kilowatt_hours(item.get("premeter_00")),
            "updated_at": now.isoformat(),
        })
        self.store.write("energy", session.mac, energy)
