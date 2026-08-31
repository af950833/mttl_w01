# MTTL-W01 local server

Local-only server for LG U+ MTTL-W01 smart strips. It provides certificate
download, MEF enrollment, automatic upgrades to the bundled stable 1.0.66
firmware, a TLS MQTT endpoint, and a multi-device
web dashboard. It does not use Docker Compose or a database.

## Data and certificates

Create two host directories. The data directory must be writable by UID 10001.
Each installation must use its own CA and server certificates. Generate them
once with the image before starting the server:

```sh
mkdir -p /home/USER/docker/mttl/data /home/USER/docker/mttl/certs
sudo chown -R 10001:10001 /home/USER/docker/mttl/data /home/USER/docker/mttl/certs
docker build -t mttl-local:latest .
docker run --rm \
  -v /home/USER/docker/mttl/certs:/certs \
  mttl-local:latest generate-certs
```

The command creates:

- `root-ca.crt`
- `root-ca.key`
- `mef.crt`, `mef.key`
- `brk2.crt`, `brk2.key`

Running the command again does not overwrite a complete certificate set. If
the directory contains only some of these files, generation stops without
replacing the existing CA. Keep `root-ca.key` private and do not commit any
generated certificate or key to Git.

Device state and energy snapshots are stored as JSON/JSONL below `/data`.
Credentials are omitted from dashboard API responses.

## Build and run

```sh
docker build -t mttl-local:latest .
docker run -d \
  --name mttl-local \
  --restart unless-stopped \
  --network host \
  -v /home/USER/docker/mttl/data:/data \
  -v /home/USER/docker/mttl/certs:/certs:ro \
  mttl-local:latest
```

Dashboard: `http://SERVER_IP:18833/`

The dashboard also serves the Android provisioning APK at
`/downloads/MTTL-W01-Provisioner.apk`. The app connects to the strip's
`ONLY_TAP_XXXXXXX` or `TONLY_TAP_XXXXXXX` setup network, derives its
`LGU_XXXXXXX` password, and sends the selected 2.4 GHz Wi-Fi credentials to
the strip over its local port 30300. Enable the router DNAT rules before local
provisioning.

The host-network ports are:

| Port | Purpose |
| ---: | --- |
| 18080/tcp | device CA download |
| 18443/tcp | TLS MEF enrollment and OTA blocking |
| 18832/tcp | TLS MQTT |
| 18833/tcp | dashboard and REST API |

## Firmware updates

The image bundles the original MTTL-W01 `1.0.66` firmware. When an MTTL-W01
reports a lower dotted-numeric version to the local MEF endpoint, the server
automatically offers `1.0.66` and serves the firmware from the original OTA
path. Devices already running `1.0.66` or a newer version receive no update.

The server verifies the bundled file before every offer and download:

```text
File:   comMTTL-W01_1.0.66.fwr
Size:   327944 bytes
SHA256: d780b578af69d52f3a05191a8e7d91a20e05085a912722327481cd5663682c04
```

Keep the strip powered while an update is in progress. The strip may reboot
more than once before reconnecting to the local MQTT server.

## Router DNAT targets

The router must match the original destination, not the strip's source IP:

| Original destination | Local target |
| --- | --- |
| `106.103.210.126:80` | `SERVER_IP:18080` |
| `106.103.210.126:443` | `SERVER_IP:18443` |
| `106.103.210.119:18831` | `SERVER_IP:18832` |

Router SSH settings and DNAT apply/remove controls are available in the web
dashboard. The manager creates only an `MTTL_DNAT` chain, verifies all three
rules after changes, and clears matching destination conntrack entries. The
router password is stored with mode 0600 in `/data/router-dnat.json` and is
never returned by the API. Do not expose the dashboard to the public Internet;
it currently assumes a trusted LAN.
