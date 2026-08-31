#!/usr/bin/env python3
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import socket


ROOT_CA = Path(os.getenv("MTTL_ROOT_CA", "/var/lib/mttl-probe/root-ca.crt"))
BIND_HOST = os.getenv("MTTL_CERT_BIND", "192.168.50.1")
BIND_PORT = int(os.getenv("MTTL_CERT_PORT", "18080"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        names = {
            "/mef/cert/http/pem": "oneM2M_HTTP_CA.pem",
            "/mef/cert/mqtt/pem": "oneM2M_MQTT_CA.pem",
        }
        filename = names.get(self.path.split("?", 1)[0])
        if filename is None:
            self.send_error(404)
            return
        body = ROOT_CA.read_bytes()
        header = (
            "HTTP/1.1 200 OK\r\n"
            f"Date: {formatdate(usegmt=True)}\r\n"
            "Server: Apache\r\n"
            f"Content-Disposition: attachment;filename={filename}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Content-Type: application/xml;charset=UTF-8\r\n"
            "\r\n"
        ).encode("ascii")
        self.wfile.write(header)
        self.wfile.flush()
        self.wfile.write(body)
        self.wfile.flush()
        # LG's Apache endpoint keeps the HTTP/1.1 socket open after sending the
        # complete body. The old Realtek client closes it after processing the
        # declared Content-Length; an immediate server FIN makes its downloader
        # report failure and repeat the request five times.
        self.close_connection = False
        # Keep the handler (and therefore the TCP socket) alive until the
        # device closes first, matching the observed Apache behavior.
        self.connection.settimeout(3.0)
        try:
            self.connection.recv(1)
        except (socket.timeout, OSError):
            pass

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} {self.command} {self.path} " + fmt % args, flush=True)


ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler).serve_forever()
