import json
import mimetypes
import os
import signal
import subprocess
import threading
import paramiko
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .registry import DeviceRegistry
from .store import FileStore
from .mqtt_server import MQTTServer
from .dnat import DNATError, DNATManager
from .ha_mqtt import HAMQTTBridge


DATA_DIR = Path(os.getenv("MTTL_DATA_DIR", "/data"))
WEB_DIR = Path("/app/web")
STORE = FileStore(DATA_DIR)
REGISTRY = DeviceRegistry(STORE)
DNAT = DNATManager(DATA_DIR)
MQTT = None
HA = None


class WebHandler(BaseHTTPRequestHandler):
    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/devices":
            body = json.dumps(STORE.list_devices(), ensure_ascii=False).encode()
            return self.send_bytes(body, "application/json; charset=utf-8")
        if self.path == "/api/health":
            body = json.dumps({"status": "ok"}).encode()
            return self.send_bytes(body, "application/json")
        if self.path == "/api/dnat/config":
            return self.send_bytes(json.dumps(DNAT.public_config()).encode(), "application/json")
        if self.path == "/api/dnat/status":
            try:
                value = DNAT.status()
                status = 200
            except Exception as error:
                value, status = {"configured": DNAT.public_config()["configured"], "state": "error", "error": str(error)}, 503
            return self.send_bytes(json.dumps(value).encode(), "application/json", status)
        if self.path == "/api/ha/config":
            return self.send_bytes(json.dumps(HA.public_config()).encode(), "application/json")
        if self.path.startswith("/api/commands/"):
            request_id = self.path.removeprefix("/api/commands/")
            value = MQTT.command_status(request_id)
            if value is None:
                return self.send_bytes(b'{"error":"command not found"}', "application/json", 404)
            return self.send_bytes(json.dumps(value).encode(), "application/json")
        name = "index.html" if self.path in ("/", "/dashboard") else self.path.lstrip("/")
        path = (WEB_DIR / name).resolve()
        if WEB_DIR.resolve() not in path.parents and path != WEB_DIR.resolve():
            return self.send_bytes(b"not found", "text/plain", 404)
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            return self.send_bytes(b"not found", "text/plain", 404)
        content_type = "application/vnd.android.package-archive" if path.suffix == ".apk" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        if path.suffix == ".html":
            content_type += "; charset=utf-8"
        self.send_bytes(body, content_type)

    def do_POST(self):
        if self.path == "/api/dnat/config":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                value = json.loads(self.rfile.read(length) or b"{}")
                return self.send_bytes(json.dumps(DNAT.save_config(value)).encode(), "application/json")
            except (ValueError, json.JSONDecodeError) as error:
                return self.send_bytes(json.dumps({"error": str(error)}).encode(), "application/json", 400)
        if self.path == "/api/ha/config":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                value = json.loads(self.rfile.read(length) or b"{}")
                return self.send_bytes(json.dumps(HA.save_config(value)).encode(), "application/json")
            except (ValueError, json.JSONDecodeError) as error:
                return self.send_bytes(json.dumps({"error": str(error)}).encode(), "application/json", 400)
        if self.path in ("/api/dnat/test", "/api/dnat/enable", "/api/dnat/disable"):
            try:
                action = self.path.rsplit("/", 1)[-1]
                value = getattr(DNAT, action)()
                return self.send_bytes(json.dumps(value).encode(), "application/json")
            except (DNATError, OSError, paramiko.SSHException) as error:
                return self.send_bytes(json.dumps({"error": str(error)}).encode(), "application/json", 503)
        parts = self.path.strip("/").split("/")
        if len(parts) < 4 or parts[:2] != ["api", "devices"]:
            return self.send_bytes(b'{"error":"not found"}', "application/json", 404)
        mac = parts[2].upper()
        try:
            if parts[3] == "settings" and len(parts) == 4:
                length = int(self.headers.get("Content-Length", "0"))
                value = json.loads(self.rfile.read(length) or b"{}")
                device = REGISTRY.update_names(mac, value.get("name"), value.get("channels", []))
                HA.republish_device(mac)
                body = json.dumps({"updated": True, "name": device["name"], "channels": device["channels"]}, ensure_ascii=False).encode()
                return self.send_bytes(body, "application/json; charset=utf-8")
            elif parts[3] == "delete" and len(parts) == 4:
                HA.remove_device(mac)
                MQTT.disconnect(mac)
                REGISTRY.delete(mac)
                return self.send_bytes(b'{"deleted":true}', "application/json")
            elif parts[3] == "ha-link" and len(parts) == 4:
                length = int(self.headers.get("Content-Length", "0"))
                value = json.loads(self.rfile.read(length) or b"{}")
                enabled = HA.set_link(mac, bool(value.get("enabled")))
                return self.send_bytes(json.dumps({"enabled": enabled}).encode(), "application/json")
            elif parts[3] == "refresh":
                request_id = MQTT.command(mac, "STATUS_GET")
            elif parts[3] == "main" and len(parts) == 5:
                request_id = MQTT.command(mac, "POWER_SET", "FF" if parts[4] == "on" else "00")
            elif parts[3] == "channels" and len(parts) == 6:
                number = int(parts[4])
                if number not in range(1, 5):
                    raise ValueError("invalid channel")
                request_id = MQTT.command(mac, f"POWER{number}_SET", "FF" if parts[5] == "on" else "00")
            else:
                return self.send_bytes(b'{"error":"not found"}', "application/json", 404)
            body = json.dumps({
                "accepted": True,
                "status": "sent",
                "request_id": request_id,
                "status_url": f"/api/commands/{request_id}",
            }).encode()
            return self.send_bytes(body, "application/json", 202)
        except KeyError as error:
            message = "device offline" if parts[3] not in ("settings", "delete") else str(error).strip("'")
            return self.send_bytes(json.dumps({"error": message}).encode(), "application/json", 409)
        except (ValueError, RuntimeError, json.JSONDecodeError) as error:
            body = json.dumps({"error": str(error)}).encode()
            return self.send_bytes(body, "application/json", 400)

    def log_message(self, fmt, *args):
        pass


def run_legacy_services():
    environment = {
        **os.environ,
        "MTTL_CERT_BIND": "0.0.0.0",
        "MTTL_MEF_BIND": "0.0.0.0",
        "MTTL_MQTT_BIND": "0.0.0.0",
        "MTTL_ROOT_CA": os.path.join(os.getenv("MTTL_CERT_DIR", "/certs"), "root-ca.crt"),
    }
    (DATA_DIR / "enable-local-auth").touch(exist_ok=True)
    processes = [
        subprocess.Popen(["python", f"/app/legacy/{name}"], env=environment)
        for name in ("mttl_cert_server.py", "mttl_mef_proxy.py")
    ]
    return processes


def main():
    global MQTT, HA
    cert_dir = Path(os.getenv("MTTL_CERT_DIR", "/certs"))
    required = ("root-ca.crt", "mef.crt", "mef.key", "brk2.crt", "brk2.key")
    missing = [name for name in required if not (cert_dir / name).is_file()]
    if missing:
        raise SystemExit(f"missing certificate files in {cert_dir}: {', '.join(missing)}")
    processes = run_legacy_services()
    MQTT = MQTTServer(
        STORE,
        REGISTRY,
        host=os.getenv("MTTL_MQTT_BIND", "0.0.0.0"),
        port=int(os.getenv("MTTL_MQTT_PORT", "18832")),
        cert_dir=str(cert_dir),
        poll_interval=int(os.getenv("MTTL_POLL_INTERVAL", "15")),
        offline_timeout=int(os.getenv("MTTL_OFFLINE_TIMEOUT", "45")),
        active_poll_interval=int(os.getenv("MTTL_ACTIVE_POLL_INTERVAL", "5")),
        settled_status_delay=float(os.getenv("MTTL_SETTLED_STATUS_DELAY", "3.5")),
        command_active_seconds=int(os.getenv("MTTL_COMMAND_ACTIVE_SECONDS", "30")),
        command_confirm_timeout=int(os.getenv("MTTL_COMMAND_CONFIRM_TIMEOUT", "12")),
    )
    MQTT.start()
    HA = HAMQTTBridge(STORE, lambda mac, command, value: MQTT.command(mac, command, value))
    HA.start()

    def stop(*_):
        for process in processes:
            process.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    bind = os.getenv("MTTL_WEB_BIND", "0.0.0.0")
    port = int(os.getenv("MTTL_WEB_PORT", "18833"))
    ThreadingHTTPServer((bind, port), WebHandler).serve_forever()
