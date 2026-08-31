#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import re
import socket
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DATA_DIR = os.getenv("MTTL_DATA_DIR", "/var/lib/mttl-probe")
CERT_DIR = os.getenv("MTTL_CERT_DIR", DATA_DIR)
AUTH_LOG = os.path.join(DATA_DIR, "latest-device-auth.json")
PATCHED_OTA_FLAG = "/var/lib/mttl-probe/enable-patched-ota"
PATCHED_OTA_FILE = "/var/lib/mttl-probe/comMTTL-W01_1.0.67-tls-local.fwr"
PATCHED_OTA_NAME = "comMTTL-W01_1.0.67-tls-local.fwr"
PATCHED_OTA_PATH = f"/mef/firmware1.0.67/{PATCHED_OTA_NAME}"
LOCAL_AUTH_FLAG = os.path.join(DATA_DIR, "enable-local-auth")
LOCAL_AUTH_LOG = os.path.join(DATA_DIR, "latest-local-auth.json")
PENDING_PREFIX = os.path.join(DATA_DIR, "pending-enrollment-")
FIRMWARE_DIR = os.path.join(DATA_DIR, "firmware")
STABLE_OTA_VERSION = "1.0.66"
STABLE_OTA_NAME = "comMTTL-W01_1.0.66.fwr"
STABLE_OTA_FILE = os.getenv("MTTL_STABLE_FIRMWARE", os.path.join("/app/firmware", STABLE_OTA_NAME))
STABLE_OTA_PATHS = {
    f"/mef/firmware{STABLE_OTA_VERSION}/{STABLE_OTA_NAME}",
    f"/mef/firmware/MTAP/20/D/{STABLE_OTA_VERSION}/{STABLE_OTA_NAME}",
}
STABLE_OTA_SHA256 = "d780b578af69d52f3a05191a8e7d91a20e05085a912722327481cd5663682c04"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_error(self, code, message=None, explain=None):
        # Some MTTL firmware sends its next protocol record on the existing TLS
        # socket. Record only a short prefix so we can identify the framing
        # without persisting device credentials.
        prefix = getattr(self, "raw_requestline", b"")[:96]
        print(
            f"{self.client_address[0]} NON_HTTP code={code} "
            f"length={len(getattr(self, 'raw_requestline', b''))} prefix={prefix.hex()}",
            flush=True,
        )
        self.close_connection = True

    def _record_auth(self):
        values = {
            "client": self.client_address[0],
            "origin": self.headers.get("X-M2M-Origin"),
            "token": self.headers.get("X-MEF-TK"),
            "eki": self.headers.get("X-MEF-EKI"),
            "path": self.path,
        }
        if all((values["origin"], values["token"], values["eki"])):
            temporary = AUTH_LOG + ".tmp"
            with open(temporary, "w", encoding="utf-8") as stream:
                json.dump(values, stream)
            os.chmod(temporary, 0o600)
            os.replace(temporary, AUTH_LOG)

    def _record_firmware_version(self):
        if not self.path.startswith("/mef/updateVersionCheck/firmware/"):
            return
        version_match = re.search(r"/([0-9]+(?:\.[0-9]+)+)/?$", self.path)
        origin = self.headers.get("X-M2M-Origin", "")
        mac_match = re.search(r"([0-9A-Fa-f]{12})", origin)
        if not (version_match and mac_match):
            return
        mac = mac_match.group(1).upper()
        os.makedirs(FIRMWARE_DIR, exist_ok=True)
        path = os.path.join(FIRMWARE_DIR, mac + ".json")
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump({"version": version_match.group(1), "updated_at": time.time()}, stream)
        os.replace(temporary, path)

    def _blocked_ota(self):
        self._record_auth()
        self.send_response_only(200, "OK")
        self.send_header("Content-Length", "0")
        self.end_headers()
        print(f"{self.client_address[0]} {self.command} {self.path} OTA_BLOCKED", flush=True)

    def _send_bytes(self, content, content_type="application/octet-stream", paced=False):
        self.send_response_only(200, "OK")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Connection", "close")
        self.end_headers()
        sent = 0
        try:
            if paced:
                for offset in range(0, len(content), 4096):
                    chunk = content[offset : offset + 4096]
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    sent += len(chunk)
                    time.sleep(0.03)
            else:
                self.wfile.write(content)
                self.wfile.flush()
                sent = len(content)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass
        self.close_connection = True
        return sent

    def _patched_ota_enabled(self):
        return os.path.isfile(PATCHED_OTA_FLAG) and os.path.isfile(PATCHED_OTA_FILE)

    def _serve_patched_ota(self):
        if self.path == PATCHED_OTA_PATH and self._patched_ota_enabled():
            with open(PATCHED_OTA_FILE, "rb") as stream:
                content = stream.read()
            self._send_bytes(content)
            print(
                f"{self.client_address[0]} GET {self.path} "
                f"PATCHED_OTA_SENT bytes={len(content)}",
                flush=True,
            )
            return True
        return False

    @staticmethod
    def _version(value):
        try:
            return tuple(int(part) for part in value.split("."))
        except (AttributeError, ValueError):
            return None

    def _stable_ota_available(self):
        try:
            with open(STABLE_OTA_FILE, "rb") as stream:
                return hashlib.sha256(stream.read()).hexdigest() == STABLE_OTA_SHA256
        except OSError:
            return False

    def _serve_stable_ota(self):
        if self.path.split("?", 1)[0] not in STABLE_OTA_PATHS:
            return False
        if not self._stable_ota_available():
            self.send_response_only(503, "Firmware Unavailable")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            print(f"{self.client_address[0]} GET {self.path} STABLE_OTA_INVALID", flush=True)
            return True
        with open(STABLE_OTA_FILE, "rb") as stream:
            content = stream.read()
        sent = self._send_bytes(content, paced=True)
        print(
            f"{self.client_address[0]} GET {self.path} "
            f"STABLE_OTA_SENT version={STABLE_OTA_VERSION} bytes={sent}/{len(content)}",
            flush=True,
        )
        return True

    def _offer_stable_ota(self):
        prefix = "/mef/updateVersionCheck/firmware/MTAP/MTTL-W01/"
        path = self.path.split("?", 1)[0]
        if not path.startswith(prefix):
            return False
        current = path[len(prefix):].strip("/")
        current_version = self._version(current)
        target_version = self._version(STABLE_OTA_VERSION)
        if current_version is None or current_version >= target_version:
            return False
        if not self._stable_ota_available():
            print(
                f"{self.client_address[0]} {self.command} {self.path} "
                "STABLE_OTA_NOT_OFFERED invalid_or_missing_file",
                flush=True,
            )
            return False
        self._record_auth()
        response = (
            f"<vr>{STABLE_OTA_VERSION}<url>{STABLE_OTA_VERSION}"
            f"<fwnnam>{STABLE_OTA_NAME}<chksum>12345678"
        ).encode("ascii")
        self._send_bytes(response, "text/plain;charset=UTF-8")
        print(
            f"{self.client_address[0]} {self.command} {self.path} "
            f"STABLE_OTA_OFFERED current={current} target={STABLE_OTA_VERSION}",
            flush=True,
        )
        return True

    def _serve_local_auth(self, body):
        if self.path.rstrip("/") != "/mef" or not os.path.isfile(LOCAL_AUTH_FLAG):
            return False
        match = re.search(br"<mac>([0-9A-Fa-f:-]+)</mac>", body or b"")
        if not match:
            self.send_error(400, "missing device MAC")
            return True
        mac = re.sub(br"[^0-9A-Fa-f]", b"", match.group(1)).upper().decode("ascii")
        enrollment = base64.urlsafe_b64encode(
            hashlib.sha256((mac + ":enrollment").encode("ascii")).digest()[:16]
        ).rstrip(b"=").decode("ascii")
        token = base64.urlsafe_b64encode(
            hashlib.sha256((mac + ":token").encode("ascii")).digest()[:24]
        ).decode("ascii")
        entity = f"ASN_CSE-D-local-{mac}-MTAP"
        response = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            "<authdata>"
            f"<http><enrmtKey>{enrollment}</enrmtKey><entityId>{entity}</entityId>"
            f"<token>{token}</token></http>"
            f"<coap><enrmtKey>{enrollment}</enrmtKey><entityId>{entity}</entityId>"
            f"<token>{token}</token><encryptionMethod>"
            "TLS_PSK_WITH_AES_128_CCM_8</encryptionMethod></coap>"
            f"<mqtt><enrmtKey>{enrollment}</enrmtKey><entityId>{entity}</entityId>"
            f"<token>{token}</token></mqtt>"
            "</authdata>"
        ).encode("utf-8")
        temporary = LOCAL_AUTH_LOG + ".tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump({"mac": mac, "enrollment": enrollment, "entity": entity, "token": token}, stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, LOCAL_AUTH_LOG)
        pending = PENDING_PREFIX + mac + ".json"
        pending_temporary = pending + ".tmp"
        with open(pending_temporary, "w", encoding="utf-8") as stream:
            json.dump({"mac": mac, "created_at": time.time()}, stream)
        os.chmod(pending_temporary, 0o600)
        os.replace(pending_temporary, pending)
        self._send_bytes(response, "application/xml;charset=UTF-8")
        print(f"{self.client_address[0]} POST {self.path} LOCAL_AUTH mac={mac}", flush=True)
        return True

    def _proxy(self):
        is_version_check = self.path.startswith("/mef/updateVersionCheck/firmware/")
        if is_version_check:
            self._record_firmware_version()
        is_current_1_0_66 = is_version_check and self.path.rstrip("/").endswith("/1.0.66")
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else None
        if self._serve_local_auth(body):
            return
        if self._serve_stable_ota():
            return
        if self._offer_stable_ota():
            return
        if self._serve_patched_ota():
            return
        if is_current_1_0_66 and self._patched_ota_enabled():
            self._record_auth()
            response = (
                f"<vr>1.0.67<url>1.0.67<fwnnam>{PATCHED_OTA_NAME}"
                "<chksum>12345678"
            ).encode("ascii")
            self._send_bytes(response, "text/plain;charset=UTF-8")
            print(
                f"{self.client_address[0]} {self.command} {self.path} "
                "PATCHED_OTA_OFFERED version=1.0.67",
                flush=True,
            )
            return
        if self.path.startswith("/mef/firmware") or is_version_check:
            self._blocked_ota()
            return
        # Local-only mode is deliberately fail-closed.  Never let an unknown
        # request escape to the vendor service through this process.
        self.send_response_only(404, "Not Found")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        print(f"{self.client_address[0]} {self.command} {self.path} LOCAL_REJECTED", flush=True)

    do_GET = _proxy
    do_POST = _proxy
    do_PUT = _proxy
    do_DELETE = _proxy

    def log_message(self, fmt, *args):
        pass


class RawCloseThreadingHTTPServer(ThreadingHTTPServer):
    def shutdown_request(self, request):
        # LG's Apache endpoint closes these short-lived TLS sessions with a TCP
        # FIN and no TLS close_notify. The old Realtek client carries broken
        # TLS state into its next connection when close_notify is received.
        # Detach the SSL wrapper so Python does not generate that alert.
        try:
            descriptor = request.detach()
            raw = socket.socket(fileno=descriptor)
            try:
                raw.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            raw.close()
        except (OSError, ValueError):
            try:
                request.close()
            except OSError:
                pass


server = RawCloseThreadingHTTPServer((os.getenv("MTTL_MEF_BIND", "192.168.50.1"), int(os.getenv("MTTL_MEF_PORT", "18443"))), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.minimum_version = ssl.TLSVersion.TLSv1_2
context.maximum_version = ssl.TLSVersion.TLSv1_2
context.set_ciphers("AES256-SHA256:AES128-SHA256:@SECLEVEL=0")
context.load_cert_chain(os.path.join(CERT_DIR, "mef.crt"), os.path.join(CERT_DIR, "mef.key"))
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
