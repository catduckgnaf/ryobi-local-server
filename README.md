# ryobi-local-server

A local stand-in for Ryobi's cloud API (`tti.tiwiconnect.com`) so the [ryobi_gdo](https://github.com/catduckgnaf/ryobi_gdo) Home Assistant integration keeps working on your LAN when Ryobi's servers don't. Works with the GDO125, GDO201, and GD200.

Addresses [ryobi_gdo#65](https://github.com/catduckgnaf/ryobi_gdo/issues/65).

## Read this first: you probably don't need DNS

The ryobi_gdo integration has a **Server** field (called Host in older versions). Point it at this server's IP and Home Assistant talks to it directly over plain HTTP. No router changes, no Pi-hole rewrites, no certificates.

DNS redirection is only needed for the experimental mode where the **opener itself** is tricked into talking to this server. That lives in [docs/DNS.md](docs/DNS.md), away from everyone who doesn't need it.

## What actually moves the door

The server holds the door's state and answers Home Assistant. Something still has to move the real door and report whether it's open. Pick one:

| Option | What you need | Status |
|---|---|---|
| ESP or Pi relay | An ESP8266/ESP32 with a relay on the wall button terminals and a reed switch. The server POSTs commands to it; it POSTs state back. See [examples/esphome_ryobi.yaml](examples/esphome_ryobi.yaml). | Works, fully offline |
| Opener connects directly | DNS redirect plus HTTPS, see [docs/DNS.md](docs/DNS.md). Depends on the opener accepting a self-signed certificate. | Experimental |
| Cloud polling (Docker only) | Ryobi credentials and internet. Mirrors state from Ryobi's cloud; read only. | Works while the cloud does |

Without any of these, you get a nice dashboard of a door that isn't connected to anything.

## Install: Home Assistant add-on

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fcatduckgnaf%2Fryobi-local-server)

1. Click the button, select **Add**, then install **Ryobi GDO Local Server**.
2. On the **Configuration** tab set `device_id` ([how to find it](#finding-your-device-id)). Start the add-on.
3. The **Log** tab prints the exact value to use, for example:
   ```
   In the Ryobi integration, set Server to:  http://192.168.1.50
   ```
4. [Point the integration at it](#connect-the-integration).

Full add-on docs: [ryobi_gdo_local/DOCS.md](ryobi_gdo_local/DOCS.md).

## Install: Docker (Unraid, Synology, any Linux box)

```bash
git clone https://github.com/catduckgnaf/ryobi-local-server
cd ryobi-local-server
cp .env.example .env      # set RYOBI_DEVICE_ID, that's it
docker compose up -d
curl http://localhost:8080/health   # {"status": "ok"}
```

Then set the integration's Server field to `http://<docker-host-ip>:8080`.

Compose pulls `ghcr.io/catduckgnaf/ryobi-local-server:latest` (amd64 and arm64) and falls back to building locally if the image isn't available.

**Unraid:** install the *Docker Compose Manager* plugin and use the compose file above, or add a container by hand:

| Field | Value |
|---|---|
| Repository | `ghcr.io/catduckgnaf/ryobi-local-server:latest` |
| Network | Bridge |
| Port | Host `8080` to container `8080` |
| Path | `/mnt/user/appdata/ryobi-local-server` to `/data` |
| Variable | `RYOBI_DEVICE_ID` = your device ID |
| Extra Parameters | `--user 99:100` (so it can write to appdata) |

### Docker settings

Everything for one door can be set with environment variables (see [.env.example](.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `RYOBI_DEVICE_ID` | none, required | Opener varName |
| `RYOBI_DEVICE_NAME` | `Ryobi GDO` | Friendly name |
| `RYOBI_USERNAME` / `RYOBI_PASSWORD` | empty | If set, HA must log in with exactly these. Also used for cloud polling. |
| `RYOBI_CLOUD_POLL` | `false` | Mirror state from Ryobi's cloud |
| `RYOBI_POLL_INTERVAL` | `30` | Seconds between cloud polls |
| `RYOBI_COMMAND_WEBHOOK_URL` | empty | Where to POST open/close/light commands |
| `RYOBI_ENFORCE_TOKEN` | `false` | Reject websocket clients without a valid token |
| `SSL_ENABLED` | `false` | Serve HTTPS on 8443 (DNS redirect mode only) |
| `LOG_LEVEL` | `INFO` | `DEBUG` when things get weird |

For multiple doors or custom module lists, copy `config/config.yaml.example` to `config/config.yaml`. It's mounted at `/config` and environment variables override it.

## Connect the integration

**New install:** Settings → Devices & services → Add integration → Ryobi GDO. Enter any username and password (unless you set `RYOBI_USERNAME`/`RYOBI_PASSWORD`), and put the server address in **Server**.

**Existing install:** Settings → Devices & services → Ryobi GDO → **Configure** (or ⋮ → **Reconfigure**), change **Server**. The integration reloads on its own.

| Where the server runs | Server value |
|---|---|
| HA add-on, default port | `http://192.168.1.50` |
| Docker on another box | `http://192.168.1.20:8080` |

Use the IP, not a hostname, and include `http://`. Without a scheme the integration guesses HTTP only for IPs and `host:port`; anything else gets HTTPS and fails.

## Finding your device ID

The device ID is Ryobi's `varName` for your opener. The integration shows it in a dropdown during setup, or ask Ryobi's API directly from any machine with curl:

```bash
curl -s -X GET https://tti.tiwiconnect.com/api/devices \
  --data-urlencode "username=you@example.com" \
  --data-urlencode "password=yourpassword" \
  | grep -o '"varName": *"[^"]*"'
```

Do this while Ryobi's cloud still works. Write it down. Future you will be grateful.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Integration says cannot connect | Wrong Server value. Open `http://<ip>:<port>/health` in a browser from another device. If that fails, it's the network or firewall, not the integration. |
| `TLSV1_UNRECOGNIZED_NAME`, `certificate verify failed`, `wrong version number` | Server has no `http://` (so it tried HTTPS), or you left it at `tti.tiwiconnect.com` with a DNS redirect. Set it to `http://<ip>`. |
| Login rejected (401) | You set `RYOBI_USERNAME`/`RYOBI_PASSWORD` and HA is using different ones. |
| Door state never changes | Nothing is reporting real state. See [What actually moves the door](#what-actually-moves-the-door). |
| `Failed to persist state` in logs | `/data` isn't writable. On Unraid add `--user 99:100`. |
| Add-on log: `dnsmasq failed to start` | Port 53 is taken, usually by the AdGuard or Pi-hole add-on. Turn off `dns_enabled` (you likely don't need it). |

Debug endpoints, on whatever port you use:

```bash
curl http://<ip>:<port>/health        # liveness
curl http://<ip>:<port>/state         # everything the server knows
curl http://<ip>:<port>/api/devices   # what the integration sees
```

## Security

Trusted LAN only. There's no auth by default. Don't port forward this to the internet; if you need remote access, Home Assistant already has that solved.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The server source lives in `ryobi_gdo_local/server/` because the Home Assistant builder can only see files inside the add-on folder. The standalone `Dockerfile` and pip use the same copy.

```
ryobi_gdo_local/
├── config.yaml, build.yaml, run.sh   # HA add-on
└── server/
    ├── main.py         # CLI entrypoint, config loading
    ├── app.py          # aiohttp app factory
    ├── routes.py       # HTTP + WebSocket handlers
    ├── state.py        # In-memory state, WS broadcast, persistence
    ├── models.py       # Ryobi JSON response builders
    ├── dashboard.py    # Ingress dashboard
    └── ryobi_proxy.py  # Optional cloud polling
Dockerfile, docker/     # Standalone image
dns/                    # Optional dnsmasq sidecar
```

Camera support is still a TODO. If you have firmware, protocol docs, or captures, open an issue.

## License

MIT
