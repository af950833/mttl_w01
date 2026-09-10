import hashlib
import ipaddress
import json
import os
import struct
import threading
from pathlib import Path


SOURCE_NAME = "comMTTL-W01_1.0.66.fwr"
OUTPUT_NAME = "comMTTL-W01_1.0.68.fwr"
SOURCE_SHA256 = "d780b578af69d52f3a05191a8e7d91a20e05085a912722327481cd5663682c04"
XOR_KEY = bytes.fromhex("3f5a27e8d8fb85f9bd4d51196c4f5159")

# Reuse the verified STATUS_REPORT extension layout. The stock formatter is
# left untouched; this hook appends compact, fixed-width hexadecimal fields to
# cmd_report after the original parameters array has been generated.
STATUS_CAVE_SOURCE = bytes.fromhex(
    "0d5b5350494620496e665d537069634e564d43616c4c6f61643a2043616c6962726174696f6e204c6f61646564284269744d6f64652025642c20435055436c6b202564293a2042617564526174653d3078257820526444756d6d7943796c653d307825782044656c61794c696e653d307825780d0a0000000d5b535049462057726e5d537069634e564d43616c4c6f61643a204461746120696e20466c61736828402030782578203d203078257820307825782920697320496e76616c69640d0a000000"
    "0d5b5350494620496e665d537069634e564d4361"
)
STATUS_CAVE_PATCH = bytes.fromhex(
    "f8b55c46207808b10134fbe7043c22a500f01cf82a4e706800f030f820a500f015f80423002200f018f801331ea500f00df8182200f011f81da500f007f8142200f00bf81ca500f001f8f8bd2878013510b120700134f9e7704704b5002717b12c20207001342c2078433044009a805800f004f801379f42f1db04bd1c2120fa01f212f00f020a2ab4bf30323732227001340439f3d570475d2c2276223a2200222c2274223a2200222c2270223a2200222c2265223a2200227d7d7d00000000307d0510"
)

# Expanded STATUS payload: voltage, temperatures, currents, and accumulated
# energy. Power is deliberately excluded because the stock meter_02 reports
# already provide it. Four i/w values contain channels 1-4; totals are derived.
_status_diagnostic = bytearray(STATUS_CAVE_PATCH)
_status_diagnostic[0x2A:0x2C] = bytes.fromhex("00bf")  # keep four values
_status_diagnostic[0x32:0x34] = bytes.fromhex("0822")  # current member +0x08
_status_diagnostic[0xAB] = ord("i")                   # JSON key p -> i (current)
_status_diagnostic[0xB3] = ord("w")                   # JSON key e -> w (energy)
# Voltage wrapper: divide millivolts by 100 and emit three hex digits.
# Array wrapper derives width from the member offset: t=2, i=4, w=6 digits.
_status_diagnostic[0x18:0x1C] = bytes.fromhex("00f054f8")
_status_diagnostic[0x70:0x74] = bytes.fromhex("00f02df8")
_status_diagnostic[0x7C:0x7E] = bytes.fromhex("1c21")
_status_diagnostic.extend(bytes.fromhex("6421b0fbf1f00821d7e7111d142a08bf0439d2e7"))
STATUS_CAVE_PATCH = bytes(_status_diagnostic)


class FirmwarePatchError(RuntimeError):
    pass


def _decode(raw):
    decoded = bytearray(raw)
    for index in range(16, len(decoded)):
        decoded[index] ^= XOR_KEY[index % 16]
    return decoded


def _encode(decoded):
    encoded = bytearray(decoded)
    for index in range(16, len(encoded)):
        encoded[index] ^= XOR_KEY[index % 16]
    return bytes(encoded)


def _replace(decoded, offset, expected, replacement, label):
    actual = bytes(decoded[offset:offset + len(expected)])
    if actual != expected:
        raise FirmwarePatchError(f"unexpected {label} bytes at 0x{offset:x}: {actual.hex()}")
    if len(replacement) > len(expected):
        raise FirmwarePatchError(f"replacement for {label} is too long")
    decoded[offset:offset + len(expected)] = replacement.ljust(len(expected), b"\0")


def build(source, destination, server_ip):
    address = str(ipaddress.IPv4Address(server_ip))
    raw = Path(source).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_SHA256:
        raise FirmwarePatchError(f"source SHA-256 mismatch: {digest}")
    decoded = _decode(raw)
    stored = struct.unpack_from("<I", decoded, len(decoded) - 4)[0]
    calculated = sum(decoded[:-4]) & 0xFFFFFFFF
    if stored != calculated:
        raise FirmwarePatchError(f"source checksum mismatch: {stored:08x} != {calculated:08x}")

    encoded_ip = address.encode("ascii")
    _replace(decoded, 0x4DCFC, b"mef.onem2m.uplus.co.kr", encoded_ip, "MEF/certificate host")
    _replace(decoded, 0x4DD30, b"brk2.onem2m.uplus.co.kr", encoded_ip, "MQTT host")
    _replace(decoded, 0x20594, b"hdslog.lguplus.co.kr", encoded_ip, "QMS TLS host")
    _replace(decoded, 0x20660, b"hdslog.lguplus.co.kr", encoded_ip, "QMS HTTP Host")
    _replace(decoded, 0x1D35E, bytes.fromhex("40f2bb11"), bytes.fromhex("44f60b01"), "MEF port")
    _replace(decoded, 0x18BD4, bytes.fromhex("40f2bb12"), bytes.fromhex("44f60b02"), "OTA version-check port")
    _replace(decoded, 0x19698, bytes.fromhex("40f2bb12"), bytes.fromhex("44f60b02"), "OTA download port")
    _replace(decoded, 0x18746, bytes.fromhex("44f68f12"), bytes.fromhex("44f69012"), "MQTT port")
    _replace(decoded, 0x20224, bytes.fromhex("40f2bb10"), bytes.fromhex("44f6f330"), "QMS port")
    _replace(decoded, 0x339E, bytes.fromhex("01f0fdfb"), bytes.fromhex("00bf00bf"), "SPIF log call #1")
    _replace(decoded, 0x33B8, bytes.fromhex("01f0f0fb"), bytes.fromhex("00bf00bf"), "SPIF log call #2")
    _replace(decoded, 0x36E8, STATUS_CAVE_SOURCE, STATUS_CAVE_PATCH, "STATUS_REPORT v/c/w/t extension")
    _replace(decoded, 0x16C60, bytes.fromhex("edf73cfe"), bytes.fromhex("ecf742fd"), "STATUS_REPORT extension hook")
    # Certificate download uses TCP 80 in the stock image. Branch through a
    # verified code cave so the full 18080 constant fits without moving code.
    _replace(
        decoded, 0x1D236,
        bytes.fromhex("40f6ff795020eef775fd"),
        bytes.fromhex("00f09fba00bf00bf00bf"),
        "certificate port trampoline",
    )
    _replace(
        decoded, 0x1D778,
        b"\0" * 16,
        bytes.fromhex("40f6ff7944f2a060eef7d3fafff75cbd"),
        "certificate port code cave",
    )
    _replace(decoded, 0x18E64, b"1.0.66", b"1.0.68", "firmware version")

    checksum = sum(decoded[:-4]) & 0xFFFFFFFF
    struct.pack_into("<I", decoded, len(decoded) - 4, checksum)
    output = _encode(decoded)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(output)
    os.chmod(temporary, 0o644)
    os.replace(temporary, destination)
    return {
        "filename": OUTPUT_NAME,
        "server_ip": address,
        "version": "1.0.68",
        "size": len(output),
        "sha256": hashlib.sha256(output).hexdigest(),
        "checksum": f"{checksum:08x}",
        "patch_stage": "direct-local",
    }


class FirmwarePatchManager:
    def __init__(self, data_dir, source_dir="/app/firmware"):
        self.data_dir = Path(data_dir)
        self.source = Path(source_dir) / SOURCE_NAME
        self.directory = self.data_dir / "firmware-patch"
        self.config_path = self.data_dir / "firmware-patch.json"
        self.output = self.directory / OUTPUT_NAME
        self.lock = threading.RLock()

    def _read(self):
        try:
            value = json.loads(self.config_path.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            value = {}
        return {"enabled": bool(value.get("enabled", False)), "server_ip": value.get("server_ip", "")}

    def status(self):
        with self.lock:
            config = self._read()
            result = {**config, "ready": False, "filename": OUTPUT_NAME, "certificate_port": 18080,
                      "mef_port": 18443, "mqtt_port": 18832, "qms_port": 19443}
            if self.output.is_file():
                result.update(size=self.output.stat().st_size,
                              sha256=hashlib.sha256(self.output.read_bytes()).hexdigest(), ready=True)
            return result

    def configure(self, enabled, server_ip):
        with self.lock:
            address = str(ipaddress.IPv4Address(server_ip)) if enabled else str(server_ip or "").strip()
            if enabled:
                metadata = build(self.source, self.output, address)
            else:
                metadata = {}
            temporary = self.config_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps({"enabled": bool(enabled), "server_ip": address}, indent=2), "utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.config_path)
            return {**self.status(), **metadata}
