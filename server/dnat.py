import ipaddress
import json
import os
import shlex
import threading
from pathlib import Path

import paramiko


CHAIN = "MTTL_DNAT"
IPTABLES = "/usr/sbin/iptables"
CONNTRACK = "/usr/sbin/conntrack"
RULES = (
    ("106.103.210.126", 80, 18080),
    ("106.103.210.126", 443, 18443),
    ("106.103.210.119", 18831, 18832),
    ("61.34.165.80", 443, 19443),
)


class DNATError(RuntimeError):
    pass


class DNATManager:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "router-dnat.json"
        self.lock = threading.Lock()

    def public_config(self):
        config = self._load(required=False)
        if not config:
            return {"configured": False, "server_ip": "", "router": {"host": "", "port": 22, "username": "", "password_set": False}}
        router = config["router"]
        return {
            "configured": True,
            "server_ip": config["server_ip"],
            "router": {
                "host": router["host"],
                "port": router["port"],
                "username": router["username"],
                "password_set": bool(router.get("password")),
            },
        }

    def save_config(self, value):
        old = self._load(required=False) or {}
        old_router = old.get("router", {})
        router = value.get("router", {})
        password = router.get("password") or old_router.get("password")
        config = {
            "server_ip": self._ip(value.get("server_ip")),
            "router": {
                "host": self._ip(router.get("host")),
                "port": int(router.get("port", 22)),
                "username": str(router.get("username", "")).strip(),
                "password": password,
            },
        }
        if not 1 <= config["router"]["port"] <= 65535:
            raise ValueError("invalid router port")
        if not config["router"]["username"] or not password:
            raise ValueError("router username and password are required")
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
        return self.public_config()

    def test(self):
        with self._client() as client:
            iptables = self._exec(client, f"{IPTABLES} --version")
            conntrack = self._exec(client, f"{CONNTRACK} -V")
        return {"ok": True, "iptables": iptables.strip(), "conntrack": conntrack.strip()}

    def status(self):
        config = self._load()
        with self._client(config) as client:
            chain = self._run(client, f"{IPTABLES} -t nat -nL {CHAIN}")[0] == 0
            linked = chain and self._has(client, "PREROUTING", f"-j {CHAIN}")
            rules = [self._has(client, CHAIN, self._rule(config, rule)) for rule in RULES] if chain else [False] * len(RULES)
        enabled = linked and all(rules)
        state = "on" if enabled else ("off" if not linked and not any(rules) else "partial")
        return {"configured": True, "state": state, "linked": linked, "rules": rules}

    def enable(self):
        with self.lock:
            config = self._load()
            with self._client(config) as client:
                if self._run(client, f"{IPTABLES} -t nat -nL {CHAIN}")[0] != 0:
                    self._exec(client, f"{IPTABLES} -t nat -N {CHAIN}")
                if not self._has(client, "PREROUTING", f"-j {CHAIN}"):
                    self._exec(client, f"{IPTABLES} -t nat -I PREROUTING 1 -j {CHAIN}")
                for spec in RULES:
                    args = self._rule(config, spec)
                    if not self._has(client, CHAIN, args):
                        self._exec(client, f"{IPTABLES} -t nat -A {CHAIN} {args}")
                self._clear_conntrack(client)
            result = self.status()
            if result["state"] != "on":
                raise DNATError(f"DNAT verification failed: {result['state']}")
            return result

    def disable(self):
        with self.lock:
            config = self._load()
            with self._client(config) as client:
                for location in (CHAIN, "PREROUTING"):
                    for spec in RULES:
                        args = self._rule(config, spec)
                        for _ in range(10):
                            if not self._has(client, location, args):
                                break
                            self._exec(client, f"{IPTABLES} -t nat -D {location} {args}")
                if self._run(client, f"{IPTABLES} -t nat -nL {CHAIN}")[0] == 0:
                    while self._has(client, "PREROUTING", f"-j {CHAIN}"):
                        self._exec(client, f"{IPTABLES} -t nat -D PREROUTING -j {CHAIN}")
                    self._run(client, f"{IPTABLES} -t nat -F {CHAIN}")
                    self._run(client, f"{IPTABLES} -t nat -X {CHAIN}")
                self._clear_conntrack(client)
            return {"configured": True, "state": "off", "linked": False, "rules": [False] * len(RULES)}

    def _load(self, required=True):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            if required:
                raise DNATError("router DNAT is not configured")
            return None
        # Accept the existing Rethink/Purethink router file as an import source.
        if "server_ip" not in value and value.get("router", {}).get("rethinkIp"):
            value["server_ip"] = value["router"]["rethinkIp"]
        return value

    @staticmethod
    def _ip(value):
        try:
            return str(ipaddress.ip_address(str(value)))
        except ValueError as error:
            raise ValueError("invalid IP address") from error

    def _client(self, config=None):
        config = config or self._load()
        router = config["router"]
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            router["host"], port=router["port"], username=router["username"],
            password=router["password"], timeout=5, auth_timeout=5,
            allow_agent=False, look_for_keys=False,
        )
        return client

    @staticmethod
    def _run(client, command):
        _stdin, stdout, stderr = client.exec_command(command, timeout=10)
        code = stdout.channel.recv_exit_status()
        return code, stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")

    def _exec(self, client, command):
        code, stdout, stderr = self._run(client, command)
        if code:
            raise DNATError((stderr or stdout or "router command failed").strip())
        return stdout or stderr

    def _has(self, client, chain, args):
        return self._run(client, f"{IPTABLES} -t nat -C {chain} {args}")[0] == 0

    @staticmethod
    def _rule(config, spec):
        destination, port, target_port = spec
        target = f"{config['server_ip']}:{target_port}"
        return f"-d {destination}/32 -p tcp -m tcp --dport {port} -j DNAT --to-destination {shlex.quote(target)}"

    def _clear_conntrack(self, client):
        for destination, port, _target in RULES:
            self._run(client, f"{CONNTRACK} -D -d {destination} -p tcp --dport {port}")
