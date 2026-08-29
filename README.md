# ryobi-local-server

> **Local LAN emulator for the Ryobi GDO cloud API** — replaces `tti.tiwiconnect.com` on your network so the [ryobi_gdo](https://github.com/catduckgnaf/ryobi_gdo) Home Assistant integration works even when Ryobi's servers are down.

Addresses [issue #65](https://github.com/catduckgnaf/ryobi_gdo/issues/65) — _"Control the GD200 directly via LAN, bypassing the app completely."_

---

## How it Works

The Ryobi GD200 and the HA integration both communicate exclusively with `tti.tiwiconnect.com` via:

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
    ├── /state (POST)       ← webhook: push real state in
    └── /health             ← liveness check
    │
    └── [optional] polls real Ryobi cloud every 30s
        to keep state current (graceful degradation)
```

---

## Quick Start

### Option A: Python (direct)

```bash
git clone https://github.com/catduckgnaf/ryobi-local-server
cd ryobi-local-server

pip install -e .

cp config/config.yaml.example config/config.yaml
# Edit config/config.yaml with your device_id and credentials

# Run on port 8080 (no root required)
python -m server.main --port 8080
```

### Option B: Docker Compose (recommended)

```bash
cp config/config.yaml.example config/config.yaml
# Edit config/config.yaml

docker compose up -d
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

## Webhook: Push Real State In

Have a reed switch, tilt sensor, or ESP running ESPHome? Push real door state to the server:

```bash
# Door opened
curl -X POST http://192.168.1.100/state \
  -H "Content-Type: application/json" \
  -d '{"device_id": "GDO_XXXXXXXXXX", "door_state": "1"}'

# Door closed
curl -X POST http://192.168.1.100/state \
  -H "Content-Type: application/json" \
  -d '{"device_id": "GDO_XXXXXXXXXX", "door_state": "0"}'

# Multiple fields at once
curl -X POST http://192.168.1.100/state \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "GDO_XXXXXXXXXX",
    "door_state": "0",
    "light_state": false,
    "battery_level": 85,
    "wifi_rssi": -62
  }'
```

### State field reference

| Field | Type | Values |
|---|---|---|
| `door_state` | string | `"0"` closed, `"1"` open, `"2"` closing, `"3"` opening, `"4"` fault |
| `light_state` | bool | `true` / `false` |
| `battery_level` | int | `0`–`100` (percent) |
| `wifi_rssi` | int | e.g. `-65` (dBm) |
| `safety` | bool | `true` = safety sensor blocked |
| `motion` | bool | motion sensor triggered |
| `vacation_mode` | bool | vacation mode enabled |
| `park_assist` | bool | park assist laser enabled |
| `inflator` | bool | inflator module on |
| `bt_speaker` | bool | bluetooth speaker on |

The server immediately **pushes a WebSocket update** to all connected HA clients when state changes, so entities update in real-time.

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

## FAQ

**Q: Do I need to modify the ryobi_gdo HA integration?**  
A: No. Just redirect DNS. The integration talks to `tti.tiwiconnect.com` — your local server answers instead. Zero HA config changes needed.

**Q: What happens if Ryobi's cloud is down?**  
A: Nothing changes — your local server keeps running with last-known state. If `cloud_poll: true`, it keeps retrying and will sync again when the cloud recovers.

**Q: Does this work with the GD200 hardware communicating to the cloud?**  
A: The GDO hardware itself still connects out to Ryobi's cloud — we can't change its firmware. This server intercepts **HA's** connection to the cloud, not the device's. For hardware-level LAN control, you'd need a hardware relay + reed switch (completely different approach).

**Q: Is this secure?**  
A: It's designed for trusted LAN use only — no authentication by default. Set `enforce_token: true` and use a firewall to restrict access to trusted hosts. Never expose port 80 to the internet.

**Q: Can I add multiple doors?**  
A: Yes — add multiple entries under `devices:` in config.yaml.

---

## License

MIT
