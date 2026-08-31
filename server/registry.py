import base64
import hashlib
import threading
import json
import time
from datetime import datetime


def credential(mac, purpose, size):
    digest = hashlib.sha256(f"{mac}:{purpose}".encode("ascii")).digest()[:size]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class DeviceRegistry:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.sessions = {}

    def enroll(self, mac):
        mac = "".join(character for character in mac.upper() if character in "0123456789ABCDEF")
        if len(mac) != 12:
            raise ValueError("invalid MAC")
        with self.lock:
            device = self.store.read("devices", mac, {})
            device.update({
                "mac": mac,
                "entity": f"ASN_CSE-D-local-{mac}-MTAP",
                "uuid": device.get("uuid", f"local-{mac}"),
                "model": "MTTL-W01",
                "name": device.get("name", f"MTTL {mac[-6:]}"),
                "channels": device.get("channels", ["1", "2", "3", "4"]),
                "enrollment": credential(mac, "enrollment", 16),
                "token": credential(mac, "token", 24),
                "updated_at": datetime.now().astimezone().isoformat(),
            })
            self.store.write("devices", mac, device)
            return device

    def by_entity(self, entity):
        prefix, suffix = "ASN_CSE-D-local-", "-MTAP"
        if entity.startswith(prefix) and entity.endswith(suffix):
            return self.store.read("devices", entity[len(prefix):-len(suffix)])
        return None

    def consume_pending_enrollment(self, mac, max_age=900):
        path = self.store.root / f"pending-enrollment-{mac}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            valid = value.get("mac") == mac and time.time() - float(value.get("created_at", 0)) <= max_age
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return valid

    def update_names(self, mac, name, channels):
        mac = "".join(character for character in mac.upper() if character in "0123456789ABCDEF")
        if len(mac) != 12:
            raise ValueError("invalid MAC")
        name = str(name).strip()
        channels = [str(value).strip() for value in channels]
        if not name or len(name) > 40:
            raise ValueError("device name must be 1-40 characters")
        if len(channels) != 4 or any(not value or len(value) > 24 for value in channels):
            raise ValueError("four channel names of 1-24 characters are required")
        with self.lock:
            device = self.store.read("devices", mac)
            if not device or device.get("hidden"):
                raise KeyError("device not found")
            device.update({"name": name, "channels": channels, "updated_at": datetime.now().astimezone().isoformat()})
            self.store.write("devices", mac, device)
        return device

    def delete(self, mac):
        mac = "".join(character for character in mac.upper() if character in "0123456789ABCDEF")
        with self.lock:
            device = self.store.read("devices", mac)
            if not device:
                raise KeyError("device not found")
            self.store.delete("devices", mac)
            self.store.delete("state", mac)
            self.store.delete("energy", mac)
            try:
                (self.store.root / f"pending-enrollment-{mac}.json").unlink()
            except FileNotFoundError:
                pass
