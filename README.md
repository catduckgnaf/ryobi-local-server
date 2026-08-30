# ryobi-local-server

> **Local LAN emulator for the Ryobi GDO cloud API** — replaces `tti.tiwiconnect.com` on your network so the [ryobi_gdo](https://github.com/catduckgnaf/ryobi_gdo) Home Assistant integration works even when Ryobi's servers are down.

Addresses [issue #65](https://github.com/catduckgnaf/ryobi_gdo/issues/65) — _"Control the GD200 directly via LAN, bypassing the app completely."_

**Compatible hardware:** Ryobi GDO125, GDO201, and GD200 garage-door openers.

---

## Quick Start

### Home Assistant add-on

[![Add the Ryobi GDO Local Server repository to your Home Assistant instance](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fcatduckgnaf%2Fryobi-local-server)

Click the button to open Home Assistant's **Add-on repository** dialog with this repository pre-filled. Select **Add**, then install **Ryobi GDO Local Server** from the add-on store.

The add-on does not need a separate `dnsmasq` installation or DNS sidecar. Its built-in DNS service handles the `tti.tiwiconnect.com` redirect when `dns_enabled` is enabled.

### Docker Compose

```bash
git clone https://github.com/catduckgnaf/ryobi-local-server
cd ryobi-local-server
cp config/config.yaml.example config/config.yaml
# Edit config/config.yaml, then:
docker compose up -d
```

The standalone Docker image requires an external DNS rewrite or a separate `dnsmasq` sidecar. See [Docker Compose: DNS, HTTPS, and cloud polling](#docker-compose-dns-https-and-cloud-polling) before enabling it.

---

## How it Works

The Ryobi GDO125, GDO201, and GD200 devices and the HA integration communicate exclusively with `tti.tiwiconnect.com` via:

| Protocol | Endpoint | Purpose |
|---|---|---|
| HTTPS | `POST /api/login` | Get API key |
| HTTPS | `GET /api/devices` | List devices |
| HTTPS | `GET /api/devices/<id>` | Device detail + state |
| WSS | `/api/wsrpc` | Real-time push/commands |

This server **fully reimplements those four endpoints** locally. You redirect DNS for `tti.tiwiconnect.com` to your server's local IP, and all traffic stays on your LAN. Ryobi's cloud becomes optional.

```
Home Assistant
    │  HTTP + WSS
    ▼
ryobi-local-server  (your machine, port 80)
    ├── /api/login          ← returns a local API key
    ├── /api/devices        ← returns device list from memory
    ├── /api/devices/<id>   ← returns full deviceTypeMap
    └── /api/wsrpc (WS)    ← real-time commands + push updates
    │
    ├── /state (GET)        ← debug: view current state
    └── /health             ← liveness check
    │
    └── [optional] polls real Ryobi cloud every 30s
        to keep state current (graceful degradation)
```

---

## Docker Compose: DNS, HTTPS, and cloud polling

The standalone Docker image is not equivalent to the Home Assistant add-on:

- The add-on includes and starts `dnsmasq` for the LAN DNS redirect.
- The standalone Docker image does **not** include `dnsmasq`.
- The standalone Docker Compose example serves HTTP on host port `80` via container port `8080`.
- The standalone Docker image does not start an HTTPS listener on host port `443` unless you provide a certificate and pass the SSL arguments to `server.main`.

The local server replaces `tti.tiwiconnect.com`. Docker Compose does not provide that DNS redirect by itself. Use one of these approaches:

- Use an existing Pi-hole, AdGuard Home, UniFi, pfSense, or OpenWrt DNS rewrite.
- Run a separate `dnsmasq` sidecar on Linux with host networking and host port 53.
- Build `dnsmasq` into a custom image and supervise it separately from the Python process.

For a DNS sidecar, the rewrite must point to the **Docker host's LAN IP**, not the container IP:

```conf
no-resolv
server=1.1.1.1
server=8.8.8.8
address=/tti.tiwiconnect.com/DOCKER_HOST_LAN_IP
listen-address=0.0.0.0
bind-interfaces
```

The DNS service must be reachable on both UDP and TCP port 53. On Linux, a Compose sidecar can use `network_mode: host`; verify that another service is not already using port 53. Docker Desktop on macOS and Windows has different host-network behavior and should use an external DNS service instead.

The HA integration connects to `https://tti.tiwiconnect.com` on port 443. A Docker deployment therefore also needs either:

- A TLS reverse proxy on host port 443 that forwards to the local server and supports WebSockets; or
- The local server's optional SSL listener, with a certificate for `tti.tiwiconnect.com` and an explicit `--ssl-port`, `--ssl-cert`, and `--ssl-key` configuration.

If HA logs show `TLSV1_UNRECOGNIZED_NAME`, `wrong version number`, or a connection failure on port 443, check DNS and TLS routing first. The usual cause is that `tti.tiwiconnect.com` resolves to the local Docker host, but port 443 is not serving a TLS endpoint for that hostname. This is not normally a bad Ryobi password.

#### Cloud polling and split DNS

For local-only operation, leave cloud polling disabled:

```yaml
cloud_poll: false
```

If `cloud_poll: true`, the Ryobi application container must resolve `tti.tiwiconnect.com` to Ryobi's public service while Home Assistant and the GDO resolve it to the local server. Do not point the application container at the local DNS rewrite. In Compose, configure public DNS for the application container only when the network permits direct public DNS resolution:

```yaml
services:
  ryobi-local-server:
    # ...existing settings...
    dns:
      - 1.1.1.1
      - 8.8.8.8
```

If the router forcibly intercepts all DNS queries, use a resolver that provides split-DNS views or leave `cloud_poll` disabled. A single global rewrite sends the cloud proxy back to the local emulator and creates a DNS/TLS loop.

After deployment, verify both paths separately:

```bash
# From the application container: should resolve the public Ryobi service
docker compose exec ryobi-local-server getent hosts tti.tiwiconnect.com

# From a LAN client using the local DNS service: should resolve to DOCKER_HOST_LAN_IP
dig @DOCKER_HOST_LAN_IP tti.tiwiconnect.com
```

---

## Configuration

Edit `config/config.yaml` (see [`config/config.yaml.example`](config/config.yaml.example) for all options):

```yaml
username: "your_ryobi_email@example.com"   # optional, used for cloud polling
password: "your_ryobi_password"             # optional

devices:
  - device_id: "GDO_XXXXXXXXXX"  # your Ryobi device varName
    name: "Garage Door"

cloud_poll: true      # poll real Ryobi cloud every 30s for live state
poll_interval: 30
enforce_token: false  # set true in production
```

### Finding your device_id

Your `device_id` is the `varName` Ryobi uses — looks like `GDO_XXXXXXXXXX`. Find it by:

1. **From HA integration**: Check the existing ryobi_gdo integration config entry
2. **From the real API**: `curl "https://tti.tiwiconnect.com/api/devices" --data "username=you@email.com&password=yourpass" | python3 -m json.tool | grep varName`

---

## DNS Redirect Setup

The key step is making `tti.tiwiconnect.com` resolve to your local server instead of the real Ryobi cloud. Choose the method that best matches your network:

### 🌟 Method 1: Standard Router / DHCP (No Custom Router Flashing)
The add-on contains a built-in DNS forwarder (`dnsmasq`) on port 53.
* In your router's DHCP / LAN settings, set **Primary DNS** to your Home Assistant machine's IP (e.g. `192.168.1.50`).
* Normal web traffic is resolved through Cloudflare (`1.1.1.1`) and Google (`8.8.8.8`), while `tti.tiwiconnect.com` is automatically caught and pointed to Home Assistant.

### 🛡️ Method 2: Pi-hole or AdGuard Home
* **Pi-hole**: Navigate to **Local DNS → DNS Records → Add**:
  * Domain: `tti.tiwiconnect.com`
  * IP Address: `<Server IP>`
* **AdGuard Home**: Navigate to **Filters → DNS rewrites → Add DNS rewrite**:
  * Domain: `tti.tiwiconnect.com`
  * Answer: `<Server IP>`

### 🌐 Method 3: Ubiquiti UniFi (UDM-Pro / UDM-SE / UCG / Gateway)
* **Via UniFi Controller UI**:
  1. Open **Settings → Routing → DNS**.
  2. Click **Add Static DNS Entry**.
  3. Domain: `tti.tiwiconnect.com`
  4. IP Address: `<Server IP>`
* **Via SSH / Persistent Service**:
  ```sh
  cat << 'EOF' > /data/udapi-config/ryobi-dns.sh
  #!/bin/sh
  echo 'address=/tti.tiwiconnect.com/<SERVER_IP>' > /run/dnsmasq.dhcp.conf.d/ryobi_dns.conf
  echo 'address=/tti.tiwiconnect.com/<SERVER_IP>' >> /run/dnsmasq.dns.conf.d/main.conf
  killall -HUP dnsmasq || true
  EOF
  chmod +x /data/udapi-config/ryobi-dns.sh
  /data/udapi-config/ryobi-dns.sh
  ```

### 🔒 Method 4: pfSense / OPNsense
1. Go to **Services → DNS Resolver → General Settings**.
2. Under **Host Overrides**, click **Add**.
3. Set **Host**: `tti`, **Domain**: `tiwiconnect.com`, **IP Address**: `<Server IP>`.
4. Click **Save** and **Apply Changes**.

### 📡 Method 5: OpenWrt / DD-WRT
* In OpenWrt: **Network → DHCP and DNS → General Settings → Addresses**:
  `/tti.tiwiconnect.com/<Server IP>`
* In DD-WRT: **Services → Services → Additional DNS Options**:
  `address=/tti.tiwiconnect.com/<Server IP>`

### 📶 Method 6: Dedicated Home Assistant Wi-Fi AP (100% Router-Free)
If you have a Wi-Fi dongle or Raspberry Pi running Home Assistant:
1. Install the **Access Point** add-on in Home Assistant.
2. Broadcast a dedicated SSID (e.g. `Ryobi-Garage-WiFi`).
3. Pair the Ryobi opener directly to that SSID — Home Assistant handles DNS and DHCP directly without touching your home router.

---

## Debug Endpoints

```bash
# View current state of all devices
curl http://localhost:8080/state

# Health check
curl http://localhost:8080/health

# List devices
curl http://localhost:8080/api/devices
```

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## Architecture

```
server/
├── main.py         # CLI entrypoint (argparse, config loading, server start)
├── app.py          # aiohttp Application factory (routes, startup/cleanup hooks)
├── routes.py       # All HTTP + WebSocket handlers
├── state.py        # In-memory state store (thread-safe, WS broadcast, persistence)
├── models.py       # GarageDoorState dataclass + Ryobi JSON response builders
└── ryobi_proxy.py  # Optional: background task that polls real Ryobi cloud
```

---

## Open Work

Camera support is still a TODO. Firmware and camera-protocol inspection is ongoing. If you have relevant Ryobi firmware, protocol documentation, or useful captures, please open an issue with the details you can share.

---

## FAQ

**Q: Do I need to modify the ryobi_gdo HA integration?**  
A: No. Just redirect DNS. The integration talks to `tti.tiwiconnect.com` — your local server answers instead. Zero HA config changes needed.

**Q: What happens if Ryobi's cloud is down?**  
A: Nothing changes — your local server keeps running with last-known state. If `cloud_poll: true`, it keeps retrying and will sync again when the cloud recovers.

**Q: Does this work with GDO125, GDO201, and GD200 hardware communicating to the cloud?**

A: The GDO hardware itself still connects out to Ryobi's cloud — we can't change its firmware. This server intercepts **HA's** connection to the cloud, not the device's. For hardware-level LAN control, you'd need a hardware relay + reed switch (completely different approach).

**Q: Is this secure?**  
A: It's designed for trusted LAN use only — no authentication by default. Set `enforce_token: true` and use a firewall to restrict access to trusted hosts. Never expose port 80 to the internet.

**Q: Can I add multiple doors?**  
A: Yes — add multiple entries under `devices:` in config.yaml.

---

## License

MIT
