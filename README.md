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

The key step: make `tti.tiwiconnect.com` resolve to your local server instead of the real Ryobi cloud.

### Option 1: Pi-hole / AdGuard Home (recommended)

Add a **Local DNS** record:

```
Domain:  tti.tiwiconnect.com
Answer:  <IP of your server>   e.g. 192.168.1.100
```

In Pi-hole: **Local DNS → DNS Records → Add**  
In AdGuard: **Filters → DNS rewrites → Add DNS rewrite**

### Option 2: dnsmasq (e.g. on your router)

Add to `/etc/dnsmasq.conf` (or `/etc/dnsmasq.d/ryobi.conf`):
```
address=/tti.tiwiconnect.com/192.168.1.100
```

### Option 3: `/etc/hosts` on the HA machine only

Add to `/etc/hosts` on your Home Assistant server:
```
192.168.1.100   tti.tiwiconnect.com
```

> **Note:** Port matters. If the integration connects to port 443 (HTTPS/WSS), you'll need a TLS-terminating reverse proxy (nginx/Caddy) in front of this server. If you can point the HA integration at `http://` instead, port 80 works directly without TLS.

### Option 4: Reverse proxy + self-signed cert (for HTTPS/WSS)

If the integration requires HTTPS, use nginx or Caddy to terminate TLS with a self-signed cert:

```nginx
server {
    listen 443 ssl;
    server_name tti.tiwiconnect.com;
    ssl_certificate     /etc/ssl/certs/ryobi-local.crt;
    ssl_certificate_key /etc/ssl/private/ryobi-local.key;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

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
