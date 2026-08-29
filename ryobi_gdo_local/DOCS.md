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

### 3. Choose your DNS Redirection Method

The physical Ryobi opener and Home Assistant look up `tti.tiwiconnect.com`. Choose **one** of the methods below to route traffic locally:

---

#### 🌟 Option 1: No Advanced Router Required — Set Home Assistant as Network DNS (Easiest UI)
The add-on has a built-in DNS forwarder (`dnsmasq`) running on port 53:
1. In your standard ISP router's DHCP / LAN settings, set **Primary DNS Server** to your Home Assistant IP (e.g. `192.168.1.50`).
2. The add-on will answer normal internet DNS requests through Cloudflare (`1.1.1.1`) and Google (`8.8.8.8`) while automatically intercepting `tti.tiwiconnect.com` and pointing it to Home Assistant.
3. **No custom firewall rules or router flashing needed.**

---

#### 🛡️ Option 2: AdGuard Home or Pi-hole (Zero Router Tweaks)
If you run AdGuard Home or Pi-hole (standalone or via Home Assistant add-on):
* **AdGuard Home**: Go to **Filters → DNS rewrites → Add DNS rewrite**:
  * Domain: `tti.tiwiconnect.com`
  * Answer: `<Home Assistant IP>`
* **Pi-hole**: Go to **Local DNS → DNS Records → Add**:
  * Domain: `tti.tiwiconnect.com`
  * IP Address: `<Home Assistant IP>`

---

#### 🌐 Option 3: UniFi Dream Machine (UDM-Pro / SE / UCG / Gateway)
* **Via UniFi Web UI**:
  1. Navigate to **Settings → Routing → DNS**.
  2. Click **Add Static DNS Entry**.
  3. Set Domain Name: `tti.tiwiconnect.com`
  4. Set IP Address: `<Home Assistant LAN IP>`
* **Via SSH / Persistent Script**:
  ```sh
  cat << 'EOF' > /data/udapi-config/ryobi-dns.sh
  #!/bin/sh
  echo 'address=/tti.tiwiconnect.com/<HA_IP>' > /run/dnsmasq.dhcp.conf.d/ryobi_dns.conf
  echo 'address=/tti.tiwiconnect.com/<HA_IP>' >> /run/dnsmasq.dns.conf.d/main.conf
  killall -HUP dnsmasq || true
  EOF
  chmod +x /data/udapi-config/ryobi-dns.sh
  /data/udapi-config/ryobi-dns.sh
  ```

---

#### 🔒 Option 4: pfSense / OPNsense
1. Go to **Services → DNS Resolver → General Settings**.
2. Scroll to **Host Overrides** and click **Add**.
3. Set:
   * **Host**: `tti`
   * **Domain**: `tiwiconnect.com`
   * **IP Address**: `<Home Assistant IP>`
4. Save and Apply Changes.

---

#### 📡 Option 5: OpenWrt
1. Go to **Network → DHCP and DNS → General Settings**.
2. Under **Addresses**, enter:
   ```
   /tti.tiwiconnect.com/<Home Assistant IP>
   ```
3. Click **Save & Apply**.

---

#### 📶 Option 6: Dedicated Home Assistant Wi-Fi Access Point (100% Router-Free)
If you have a Wi-Fi adapter or Raspberry Pi running Home Assistant:
1. Install the **Access Point** add-on in Home Assistant.
2. Broadcast a dedicated SSID (e.g. `Ryobi-Garage-WiFi`).
3. Pair the Ryobi opener directly to that SSID. Home Assistant handles DNS and DHCP directly.

---

### 4. Start the add-on

Start the add-on and verify in the **Log** tab:
```
[INFO] Generating self-signed TLS certificate for tti.tiwiconnect.com...
[INFO] HTTP Server running on 0.0.0.0:80
[INFO] HTTPS/WSS Server running on 0.0.0.0:443 (TLS active)
[INFO] Ingress Server running on 0.0.0.0:8099
[INFO] Ryobi Local Server is fully initialized.
```

### 5. Open HA sidebar

Click **Ryobi GDO** in the Home Assistant sidebar to monitor real-time door status, battery level, WiFi RSSI, and accessory controls.

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
