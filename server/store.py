import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path


class FileStore:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        for name in ("devices", "state", "energy", "firmware", "logs"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self._import_latest_firmware()

    def _import_latest_firmware(self):
        try:
            latest = json.loads((self.root / "latest-device-auth.json").read_text(encoding="utf-8"))
            mac_match = re.search(r"([0-9A-Fa-f]{12})", latest.get("origin", ""))
            version_match = re.search(r"/([0-9]+(?:\.[0-9]+)+)/?$", latest.get("path", ""))
            if mac_match and version_match:
                mac = mac_match.group(1).upper()
                if not self.read("firmware", mac):
                    self.write("firmware", mac, {"version": version_match.group(1)})
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)

    def read(self, group, key, default=None):
        path = self.root / group / f"{key}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def write(self, group, key, value):
        with self.lock:
            self._write(self.root / group / f"{key}.json", value)

    def list_devices(self):
        result = []
        for path in sorted((self.root / "devices").glob("*.json")):
            try:
                device = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if device.get("hidden"):
                continue
            device.pop("enrollment", None)
            device.pop("token", None)
            device["state"] = self.read("state", path.stem, {})
            device["energy"] = self.read("energy", path.stem, {})
            device["firmware"] = self.read("firmware", path.stem, {})
            result.append(device)
        return result

    def delete(self, group, key):
        path = self.root / group / f"{key}.json"
        with self.lock:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def append_event(self, event):
        now = datetime.now().astimezone()
        event = {"timestamp": now.isoformat(), **event}
        path = self.root / "logs" / f"events-{now:%Y-%m-%d}.jsonl"
        with self.lock, path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
