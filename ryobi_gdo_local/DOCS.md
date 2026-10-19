# Ryobi GDO Local Server

A local stand-in for Ryobi's cloud API so the ryobi_gdo integration keeps working when Ryobi's servers don't. Works with the GDO125, GDO201, and GD200.

## Setup

1. **Find your device ID.** It's Ryobi's `varName` for your opener. While Ryobi's cloud still works, run this from any computer:
   ```bash
   curl -s -X GET https://tti.tiwiconnect.com/api/devices \
     --data-urlencode "username=you@example.com" \
     --data-urlencode "password=yourpassword" \
     | grep -o '"varName": *"[^"]*"'
   ```
   The integration's device dropdown during setup shows the same thing.

2. **Configure the add-on.** On the **Configuration** tab set `device_id`. Leave everything else alone for now.

3. **Start it** and open the **Log** tab. You'll see:
   ```
   In the Ryobi integration, set Server to:  http://192.168.1.50
   ```

4. **Point the integration at it.** Settings → Devices & services → Ryobi GDO → **Configure**, paste that address into **Server**, submit. For a new install, put it in the **Server** field during setup; any username and password work.

5. Click **Ryobi GDO** in the sidebar to see live state.

That's it. No DNS, no router settings, no certificates.

## Making it control the real door

The add-on holds state and answers Home Assistant. On its own it doesn't touch the physical opener. Two ways to connect it:

**ESP relay (recommended).** An ESP8266/ESP32 with a relay across the wall button terminals and a reed switch on the door. Set `command_webhook_url` to the ESP's endpoint; the add-on POSTs `{"command": "open", "device_id": "...", "module": "garageDoor", "attr": "doorState", "value": "1"}` there. The ESP reports state back with a POST to `http://<HA IP>/state`. A ready ESPHome config is in the repository's `examples/esphome_ryobi.yaml`.

**Opener connects directly (experimental).** Redirect the opener's DNS so it talks to this add-on. Needs `https_enabled` and usually `dns_enabled`, and only works if the opener accepts a self-signed certificate. See [docs/DNS.md](https://github.com/catduckgnaf/ryobi-local-server/blob/main/docs/DNS.md).

## Options

| Option | Default | What it does |
|---|---|---|
| `device_id` | required | Opener varName |
| `device_name` | `Garage Door` | Friendly name |
| `log_level` | `info` | `debug` logs every DNS query and websocket message |
| `server_port` | `80` | HTTP port the integration connects to |
| `command_webhook_url` | empty | Where to POST door and light commands |
| `command_webhook_timeout` | `3` | Seconds to wait for the webhook |
| `https_enabled` | `false` | Experimental. HTTPS/WSS with a self-signed cert on `https_port` |
| `https_port` | `443` | Must be 443 for DNS redirect mode |
| `dns_enabled` | `false` | Experimental. dnsmasq answering `tti.tiwiconnect.com` with this host's IP |
| `dns_port` | `53` | |
| `advertise_ip` | auto | Override the detected LAN IP (hosts with several network interfaces) |

## Troubleshooting

**Integration can't connect.** Open `http://<HA IP>/health` from your phone on Wi-Fi. If that fails, check `server_port` isn't used by another add-on (NGINX Proxy Manager likes port 80). Change `server_port` to something like `8088` and use `http://<HA IP>:8088` in the integration.

**Certificate or TLS errors in the HA log.** The integration's Server field is missing `http://`, or still says `tti.tiwiconnect.com`. Fix the Server value.

**Door state never changes.** Nothing is reporting real state. See *Making it control the real door*.

**`dnsmasq failed to start`.** Port 53 is already taken, almost always by the AdGuard Home or Pi-hole add-on. Turn `dns_enabled` off; if you really need the redirect, add it in AdGuard/Pi-hole instead.

**`Failed to start HTTPS listener on port 443`.** Another add-on (NGINX, Caddy) owns 443. You only need HTTPS for the experimental mode, so turn `https_enabled` off.

## Support

- [Issues](https://github.com/catduckgnaf/ryobi-local-server/issues)
- [ryobi_gdo integration](https://github.com/catduckgnaf/ryobi_gdo)
