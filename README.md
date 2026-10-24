# ryobi-local-server

> **Local LAN emulator for the Ryobi GDO cloud API** — replaces `tti.tiwiconnect.com` on your network so the [ryobi_gdo](https://github.com/catduckgnaf/ryobi_gdo) Home Assistant integration works even when Ryobi's servers are down.

Addresses [issue #65](https://github.com/catduckgnaf/ryobi_gdo/issues/65) — _"Control the GD200 directly via LAN, bypassing the app completely."_

**Compatible hardware:** Ryobi GDO125, GDO201, and GD200 garage-door openers.

## Experimental authenticated takeover (not hardware validated)

`opener_mode: takeover` relays registration to the real cloud, waits for explicit
cloud authorization, and then retains the opener WebSocket for local commands.
It still requires the cloud at every reconnect. It is **not cloud-independent**.
The existing `cloud_relay: true` / `OPENER_CLOUD_RELAY_IP` capture override wins;
leave it enabled to preserve the working cloud path. `auto` preserves legacy
behavior, `cloud` explicitly selects relay, and `local` selects the old emulator.

Takeover requires a trusted opener certificate and an externally resolved public
IPv4 address in `TTI_CLOUD_IP` (or `cloud_ip` in standalone YAML). TLS to the real
cloud verifies `tti.tiwiconnect.com`; it never follows the local DNS rewrite.
The add-on already resolves this public address for its SNI passthrough.

Only captured light on/off and door **open** commands are sent on the physical
socket. Close, vacation and fan commands are rejected rather than guessed.
Telemetry updates state; sending a command does not echo a successful operation.
Raw door value 1 was observed open; value 3 means moving with unknown direction.
Other unobserved values remain unknown. Existing persisted values are cached,
not proof of a live opener session.

Offline tests cover lifecycle, authorization failures, mode selection, captured
bytes and telemetry. They do not establish that a real opener stays connected
after cloud handoff. Deployment and live validation are separate steps: verify
home-WiFi phone fallback first, then light with returned telemetry; door operation
requires someone present. Never use unverified HA state for auto-close safety.

---

## Quick Start

DNS is required. The door and Home Assistant look up `tti.tiwiconnect.com`. This project answers that name with your server. The Home Assistant add-on includes that DNS server (dnsmasq, the same job as one AdGuard rewrite). Docker starts the same DNS as a second container. Details are in [DNS](#dns).

### Home Assistant add-on

[![Add the Ryobi GDO Local Server repository to your Home Assistant instance](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fcatduckgnaf%2Fryobi-local-server)

1. Add the repository and install **Ryobi GDO Local Server**.
2. Set `device_id`. Leave `dns_enabled` on. Start the add-on.
3. In the add-on log, copy `Point your router's DNS to: ...`.
4. On the router, set the LAN DNS server to that IP.
5. From a computer on the same Wi-Fi, `nslookup tti.tiwiconnect.com` must print that IP. A public address means the router change did not take. Stop there.
6. In the Ryobi integration, set **Host** to `http://tti.tiwiconnect.com`.

The `http://` does not skip DNS. DNS turns the name into your machine. The prefix makes Home Assistant use port 80. Without it, Home Assistant uses HTTPS and rejects the certificate the add-on generates.

Step by step, including a port-53 clash with an existing AdGuard: [add-on documentation](ryobi_gdo_local/DOCS.md).

### Docker

Linux only for the DNS container (`network_mode: host`). Mac and Windows Docker Desktop cannot answer LAN DNS this way. Use the add-on there.

```bash
git clone https://github.com/catduckgnaf/ryobi-local-server
cd ryobi-local-server
cp config/config.yaml.example config/config.yaml
# Edit config/config.yaml (device_id).
export RYOBI_HOST_IP=192.168.x.x   # this machine's LAN address, not a container IP
docker compose up -d
```

`ryobi-dns` is the same dnsmasq the add-on runs. Point the router's LAN DNS server at `RYOBI_HOST_IP`. Compose publishes port 80 for Home Assistant and port 443 for the opener. The opener uses TLS on 443 after the name lookup. Then:

```bash
nslookup tti.tiwiconnect.com
# Address must be RYOBI_HOST_IP
curl -sD- http://tti.tiwiconnect.com/health | head
```

In the Ryobi integration, set **Host** to `http://tti.tiwiconnect.com`.

If `ryobi-dns` exits immediately, port 53 is already taken. Free it, or do not start `ryobi-dns` and add the one rewrite on the DNS server you already run. Do not run two.

### Docker Troubleshooting & Mac Gotchas

- **Browser opens public Ryobi site, but `curl` returns the local server:** macOS Safari and Chrome enable **iCloud Private Relay** and **Secure DNS (DNS-over-HTTPS)** by default. They bypass your router's local DNS rewrite and query public resolvers directly. Disable iCloud Private Relay ("Limit IP Address Tracking") for your Wi-Fi network, turn off "Use secure DNS" in Chrome, or add `tti.tiwiconnect.com` to `/etc/hosts`.
- **Web UI says "No Devices":** The local server starts empty unless configured. Add your garage door's varName under `devices:` in `config/config.yaml`.
- **Physical opener won't connect:** The opener hardware connects over **TLS Port 443**, while Home Assistant uses **HTTP Port 80**. Ensure your Docker Compose publishes both ports (`80:80` and `443:443`).

---

## How it Works

The Ryobi GDO125, GDO201, and GD200 devices and the HA integration communicate exclusively with `tti.tiwiconnect.com` via:

| Protocol | Endpoint | Purpose |
|---|---|---|
| HTTP | `POST /api/login` | Get API key |
| HTTP | `GET /api/devices` | List devices |
| HTTP | `GET /api/devices/<id>` | Device detail + state |
| WS | `/api/wsrpc` | Real-time push/commands |

This server reimplements those endpoints locally. DNS for `tti.tiwiconnect.com` must answer with this machine, and the integration Host must be `http://tti.tiwiconnect.com` so it uses port 80. The add-on also listens on 443 with a certificate it generates. Home Assistant will not trust that certificate, which is why the host needs the `http://` prefix.

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

## DNS

The name `tti.tiwiconnect.com` is the whole product. The opener and Home Assistant ask some DNS server where that name is. Until the answer is your machine, they are talking to Ryobi.

The add-on starts dnsmasq on port 53. Docker starts the same program as the `ryobi-dns` container. Either one does exactly one special thing:

- `tti.tiwiconnect.com` → your machine's LAN IP
- every other name → `1.1.1.1` and `8.8.8.8`

A DNS server that nobody asks is unused. The router has to hand your machine out as the LAN DNS server. That is the step other people miss. The add-on cannot change the router.

Check, from a computer on the Wi-Fi, before you touch the integration:

```bash
nslookup tti.tiwiconnect.com
```

A private address (192.168..., 10..., 172.16...) means DNS is working. A public address means it is not. A VPN, Android Private DNS, or iCloud Private Relay ignores the router and keeps returning the public address. Turn those off while testing.

Then set the integration Host to `http://tti.tiwiconnect.com`. Home Assistant looks the name up, which is the DNS, and connects to port 80. Leaving the host as `tti.tiwiconnect.com` with no `http://` uses HTTPS, and Home Assistant rejects the certificate the server generates. The lookup can be right and the integration still fails.

### Already running AdGuard, Pi-hole, or UniFi

Port 53 can only have one listener. If something else is already your DNS, turn the add-on's `dns_enabled` off (and do not start `ryobi-dns`) and add one rewrite there:

- Domain: `tti.tiwiconnect.com`
- Answer: the machine running this server

Do not also point the router at this add-on. One DNS, one rewrite.

### Cloud polling

Leave `cloud_poll: false`. If you turn it on, this server process must still resolve `tti.tiwiconnect.com` to Ryobi's public address while every other device resolves it to you. The Compose file gives the application container `1.1.1.1` and `8.8.8.8` for that reason. A router that intercepts every DNS query makes that split impossible. Leave cloud polling off in that case.

---

## Configuration

Edit `config/config.yaml` (see [`config/config.yaml.example`](config/config.yaml.example) for all options):

```yaml
username: "your_ryobi_email@example.com"   # optional, used for cloud polling
password: "your_ryobi_password"             # optional

devices:
  - device_id: "GDO_XXXXXXXXXX"  # your Ryobi device varName
    name: "Garage Door"

cloud_poll: false
poll_interval: 30
enforce_token: false
```

### Finding your device_id

Your `device_id` is the `varName` Ryobi uses — looks like `GDO_XXXXXXXXXX`. Find it by:

1. **From HA integration**: Check the existing ryobi_gdo integration config entry
2. **From the real API**: `curl "https://tti.tiwiconnect.com/api/devices" --data "username=you@email.com&password=yourpass" | python3 -m json.tool | grep varName`

---

## Debug Endpoints

After DNS is in place these work with the name. Before that, use the machine's IP.

```bash
curl http://tti.tiwiconnect.com/health
curl http://tti.tiwiconnect.com/state
curl http://tti.tiwiconnect.com/api/devices
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

**Q: Do I need to change the Ryobi integration?**  
A: Yes. Set Host to `http://tti.tiwiconnect.com`. DNS makes that name point at this server. The `http://` makes Home Assistant use port 80 instead of rejecting the add-on's certificate.

**Q: What happens if Ryobi's cloud is down?**  
A: The local server keeps answering. Leave `cloud_poll: false` unless you have the split DNS described above.

**Q: Does the opener itself use this?**  
A: Only if the opener's DNS server is this one. `nslookup tti.tiwiconnect.com` from the same Wi-Fi the opener uses must return your machine. If it returns a public address, the opener will keep using Ryobi. The add-on log is the confirmation: a connection from the opener's IP. A command webhook (`examples/esphome_ryobi.yaml`) does not depend on the opener accepting the local certificate.

**Q: Is this secure?**  
A: It's designed for trusted LAN use only — no authentication by default. Set `enforce_token: true` and use a firewall to restrict access to trusted hosts. Never expose port 80 to the internet.

**Q: Can I add multiple doors?**  
A: Yes — add multiple entries under `devices:` in config.yaml.

---

## License

MIT
