import hashlib
import ssl
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class QMSServer:
    MAX_BODY = 1024 * 1024

    def __init__(self, store, host="0.0.0.0", port=19443, cert_dir="/certs"):
        self.store = store
        self.host = host
        self.port = port
        self.cert_dir = Path(cert_dir)
        self.server = None
        self.thread = None

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                owner._handle(self)

            def do_GET(self):
                owner._respond(self, 405)

            def log_message(self, _format, *_args):
                return

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.cert_dir / "qms.crt", self.cert_dir / "qms.key")
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, name="qms-server", daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)

    def _handle(self, request):
        if request.path != "/read_iot_wifi":
            return self._respond(request, 404)
        try:
            length = int(request.headers.get("Content-Length", "0"))
        except ValueError:
            return self._respond(request, 400)
        if length < 0 or length > self.MAX_BODY:
            return self._respond(request, 413)
        payload = request.rfile.read(length)
        if len(payload) != length:
            return self._respond(request, 400)
        self.store.append_event({
            "at": datetime.now(timezone.utc).isoformat(),
            "kind": "qms",
            "source_ip": request.client_address[0],
            "method": "POST",
            "path": request.path,
            "content_type": request.headers.get("Content-Type", ""),
            "content_length": length,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "response": 200,
        })
        self._respond(request, 200)

    @staticmethod
    def _respond(request, status):
        request.send_response(status)
        request.send_header("Content-Length", "0")
        request.send_header("Connection", "close")
        request.end_headers()
        request.close_connection = True

