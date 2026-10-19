# DNS redirect mode (experimental)

**Stop. You probably don't need this.** If all you want is Home Assistant talking to the local server, set the integration's Server field to `http://<server ip>` and close this page.

This mode is for redirecting the **garage door opener itself** so it connects to the local server instead of Ryobi's cloud. Whether that works depends on the opener's firmware accepting a self-signed certificate, which is not confirmed for every model. If you test it, please report what you find in an issue.

## How it works

1. The opener looks up `tti.tiwiconnect.com`.
2. Your DNS answers with the local server's IP instead of Ryobi's.
3. The opener connects to port 443 on that IP. The server answers with a self-signed certificate for `tti.tiwiconnect.com`.
4. If the opener accepts it, it authenticates over the websocket and the server forwards Home Assistant's commands to it.

So you need two things: HTTPS on port 443, and a DNS answer.

**HTTPS:** add-on: `https_enabled: true`, `https_port: 443`. Docker: `SSL_ENABLED=true` and publish `443:8443`.

**DNS:** pick exactly one option below. Replace `SERVER_IP` with the LAN IP of the machine running the server (HA host or Docker host, never a container IP).

Leave the integration's Server field pointing at `http://SERVER_IP` either way. Home Assistant verifies certificates and will reject the self-signed one.

## Option A: a DNS server you already run (best)

Only the record changes; nothing else on your network is affected.

**AdGuard Home:** Filters → DNS rewrites → Add. Domain `tti.tiwiconnect.com`, answer `SERVER_IP`.

**Pi-hole:** Local DNS → DNS Records. Domain `tti.tiwiconnect.com`, IP `SERVER_IP`.

**UniFi (UDM, UCG, UXG, recent Network app):** Settings → Routing → DNS (in some versions Policy Table → Create New Policy → DNS). Type A record, domain `tti.tiwiconnect.com`, IP `SERVER_IP`.

**pfSense:** Services → DNS Resolver → Host Overrides → Add. Host `tti`, domain `tiwiconnect.com`, IP `SERVER_IP`. Save, Apply.

**OPNsense:** Services → Unbound DNS → Overrides → Hosts → Add. Same values.

**OpenWrt:** Network → DHCP and DNS → General → Addresses: `/tti.tiwiconnect.com/SERVER_IP`. Save & Apply.

**DD-WRT:** Services → Services → Additional DNS Options: `address=/tti.tiwiconnect.com/SERVER_IP`.

Clients may also use a hardcoded DNS server (many IoT devices try 8.8.8.8). If the opener ignores your rewrite, block outbound port 53 for its IP at the firewall so it falls back to the router.

## Option B: the built-in DNS server

Use this only if your router can't do Option A. It runs dnsmasq that answers `tti.tiwiconnect.com` with `SERVER_IP` and forwards everything else to 1.1.1.1 and 8.8.8.8.

**Add-on:** set `dns_enabled: true`.
**Docker (Linux only):** set `ADVERTISE_IP=SERVER_IP` in `.env`, then `docker compose --profile dns up -d`.

Then make the **opener** use `SERVER_IP` as its DNS server. Most routers can't set DNS per device, which leaves two choices:

- Set `SERVER_IP` as the DNS server your router hands out to everyone. This works, but now your whole network's internet depends on that box. Reboot Home Assistant and everyone's Netflix stops. Set the router's secondary DNS to the router itself or 1.1.1.1 and accept that some lookups of the Ryobi host will slip through to the real cloud.
- Put the opener on a separate VLAN or guest network whose DHCP hands out `SERVER_IP` as DNS. Cleaner, needs a router that supports it.

Don't enable the built-in DNS if AdGuard Home, Pi-hole, or anything else already uses port 53 on the same machine. Use Option A in that tool instead.

## Verify

```bash
# Should print SERVER_IP
nslookup tti.tiwiconnect.com SERVER_IP          # built-in DNS
nslookup tti.tiwiconnect.com                    # whatever your network uses

# Should return {"status": "ok"} (the -k skips the self-signed cert check)
curl -k https://SERVER_IP/health
```

Then watch the server log with `log_level: debug`. If the opener connects you'll see a websocket client connect from its IP followed by an auth message with its varName. If you see nothing, it's either still resolving the real cloud (DNS) or rejecting the certificate (firmware), and there isn't much to be done about the second one.

## Undo

Remove the DNS record or turn off `dns_enabled`, and power cycle the opener. It goes back to Ryobi's cloud on its own.
