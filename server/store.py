import json
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path


class FileStore:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.log_retention_days = max(1, int(os.getenv("MTTL_LOG_RETENTION_DAYS", "14")))
        self._last_log_cleanup = None
        for name in ("devices", "state", "energy", "firmware", "logs"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self._migrate_energy_files()
        self._import_latest_firmware()

    def _migrate_energy_files(self):
        for path in (self.root / "energy").glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            migrated = {
                "meter_raw": value.get("meter_raw", value.get("today_raw")),
                "meter_kwh": value.get("meter_kwh", value.get("today_kwh")),
                "updated_at": value.get("updated_at"),
            }
            migrated = {key: item for key, item in migrated.items() if item is not None}
            if migrated != value:
                with self.lock:
                    self._write(path, migrated)

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
        self._cleanup_logs(now)
        event = {"timestamp": now.isoformat(), **event}
        path = self.root / "logs" / f"events-{now:%Y-%m-%d}.jsonl"
        with self.lock, path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _cleanup_logs(self, now):
        today = now.date()
        if self._last_log_cleanup == today:
            return
        cutoff = today - timedelta(days=self.log_retention_days - 1)
        with self.lock:
            if self._last_log_cleanup == today:
                return
            for path in (self.root / "logs").glob("events-*.jsonl"):
                try:
                    log_date = datetime.strptime(path.stem.removeprefix("events-"), "%Y-%m-%d").date()
                except ValueError:
                    continue
                if log_date < cutoff:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
            self._last_log_cleanup = today
