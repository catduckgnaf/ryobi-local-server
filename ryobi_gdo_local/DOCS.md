# Ryobi GDO Local Server — Home Assistant Add-on

Fully local TiwiConnect emulator for the Ryobi GD200 garage door opener.

- ✅ Runs a complete Ryobi cloud API server on your Home Assistant machine  
- ✅ Built-in DNS server (`dnsmasq`) auto-redirects `tti.tiwiconnect.com` to local  
- ✅ **Zero internet required** — works even if Ryobi's cloud is completely dead  
- ✅ Real-time dashboard in the HA sidebar  
- ✅ Webhook endpoint for reed switch / tilt sensor state pushes  
- ✅ Outgoing command webhook to trigger a physical relay (Pi/ESP) when HA opens the door  

---

## How It Works

```
Home Assistant (ryobi_gdo integration)
    │  tries to reach tti.tiwiconnect.com
    ▼
[DNS] tti.tiwiconnect.com → 192.168.1.x (your HA machine)  ← dnsmasq does this
    ▼
Ryobi GDO Local Server (this addon, port 80)
    ├── /api/login      ← returns local API key
    ├── /api/devices    ← returns your device from config
    ├── /api/wsrpc (WS) ← real-time push + command handling
    ├── /state  (POST)  ← reed switch / sensor pushes real door state
    └── /       (GET)   ← live dashboard (HA sidebar)
```

---

## Installation

### 1. Add this repository to HA

In Home Assistant:  
**Settings → Add-ons → Add-on Store → ⋮ menu → Repositories**  
Add: `https://github.com/catduckgnaf/ryobi-local-server`

Then install **Ryobi GDO Local Server** from the store.

### 2. Configure the add-on

Go to the **Configuration** tab and set:

| Option | Description |
|---|---|
| `device_id` | Your Ryobi device varName (e.g. `GDO_XXXXXXXXXX`) |
| `device_name` | Friendly name (e.g. `Garage Door`) |
| `dns_enabled` | `true` to run dnsmasq on port 53 |
| `server_port` | HTTP port (default `80`) |
| `command_webhook_url` | Optional — URL on Pi/ESP to trigger physical relay |

**Finding your device_id:**  
If you previously used the ryobi_gdo integration, check your existing config entry. Or from another machine:
```bash
curl -s "https://tti.tiwiconnect.com/api/devices" \
  --data "username=you@email.com&password=yourpass" \
  | python3 -m json.tool | grep varName
```

### 3. Set DNS redirect

Point your router's DNS to your Home Assistant machine's IP. This makes *all* devices on your network resolve `tti.tiwiconnect.com` locally.

**Router (recommended):** Set primary DNS = `<HA machine IP>` in your DHCP/DNS settings.

**Just the HA machine** (simpler, works for integration-only use): The add-on automatically configures its own DNS inside the container — the ryobi_gdo integration on the same HA instance will use the local server without any router changes.

### 4. Start the add-on

Start it — check the **Log** tab for:
```
DNS redirect active: tti.tiwiconnect.com -> 192.168.1.x
Ryobi GDO Local Server is running!
  API:     http://192.168.1.x:80/api/devices
  State:   http://192.168.1.x:80/state
  Health:  http://192.168.1.x:80/health
```

### 5. Open HA sidebar

Click **Ryobi GDO** in the sidebar — you'll see the live dashboard with current door state.

---

## Pushing Real State (Reed Switch / Tilt Sensor)

The addon can't magically know if the door is actually open or closed without a sensor. Push state from your hardware:

```bash
# Door opened (reed switch triggered open)
curl -X POST http://homeassistant.local/state \
  -H "Content-Type: application/json" \
  -d '{"device_id": "GDO_XXXXXXXXXX", "door_state": "1"}'

# Door closed
curl -X POST http://homeassistant.local/state \
  -H "Content-Type: application/json" \
  -d '{"device_id": "GDO_XXXXXXXXXX", "door_state": "0"}'
```

See [`examples/esphome_ryobi.yaml`](../../examples/esphome_ryobi.yaml) for a complete ESPHome config.

---

## State Fields

| Field | Type | Values |
|---|---|---|
| `door_state` | string | `"0"` closed · `"1"` open · `"2"` closing · `"3"` opening |
| `light_state` | bool | `true` / `false` |
| `battery_level` | int | 0–100% |
| `wifi_rssi` | int | dBm e.g. `-65` |
| `safety` | bool | `true` = sensor blocked |
| `motion` | bool | motion detected |

---

## Support

- [Issues](https://github.com/catduckgnaf/ryobi-local-server/issues)
- [ryobi_gdo integration](https://github.com/catduckgnaf/ryobi_gdo)
