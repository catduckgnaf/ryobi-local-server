# Ryobi GDO Local Server

The door and Home Assistant do not store Ryobi's IP address. They look up the name `tti.tiwiconnect.com`. This add-on answers that lookup itself.

It includes **dnsmasq**, a small DNS server. That is the same job as one rewrite in AdGuard or Pi-hole, already built in. You do not install AdGuard for this. Leave **dns_enabled** on.

DNS is required. If nothing asks this add-on, `tti.tiwiconnect.com` still points at Ryobi and the add-on never sees the door or Home Assistant.

---

## 1. Install

**Settings → Add-ons → Add-on Store → ⋮ → Repositories**

```
https://github.com/catduckgnaf/ryobi-local-server
```

Install **Ryobi GDO Local Server**.

## 2. Configure and start

| Option | What to put |
|---|---|
| `device_id` | The opener id from the Ryobi integration (the `device_id` attribute on the cover). Often looks like a MAC, `c4be84734c7b`, not always `GDO_...` |
| `device_name` | Whatever you want on the dashboard |
| `dns_enabled` | **On.** This is the built-in DNS. |
| `server_port` | `80` |
| `fan_ports` | Leave empty for one fan. For a fan on port 2 and port 5, set `2,5`. The integration then shows Fan 2 and Fan 5. |
| `opener_mode` | `local`. This controls the opener with no Ryobi cloud. Verified 2026-11-01. |
| `cloud_relay` | **Off.** On relays the opener to Ryobi for protocol capture, and Home Assistant commands then do nothing. |
| `opener_cert_pem` / `opener_key_pem` | A certificate chain and key that chain to GlobalSign Root CA. See **Opener certificate** below. Without them the opener rejects TLS and never connects. Back them up: they are lost if the add-on is reinstalled. |

Start the add-on. In the **Log** tab you want these lines:

```
dnsmasq started
DNS is running. This add-on is the DNS server for tti.tiwiconnect.com.
Point your router's DNS to: 192.168.x.x
```

Copy that IP. It is your Home Assistant machine. The rest of the setup is telling the house to ask that IP.

If the log says dnsmasq did **not** stay running, port 53 is already taken. Something else (an AdGuard add-on, Pi-hole, systemd-resolved) is already the DNS server. Two programs cannot share port 53. Stop the other one, or turn `dns_enabled` off and add this single rewrite on the one that is already running:

- Domain: `tti.tiwiconnect.com`
- Answer: the Home Assistant IP from the log

Do not run both.

## 3. The only router change

In the router's LAN / DHCP settings, set the **DNS server** to the IP from the log.

That is the whole DNS change. Devices ask the router "who should I ask for names?" The router must say "ask Home Assistant." The add-on then answers `tti.tiwiconnect.com` with its own IP, and forwards every other name (Google, updates, everything else) to `1.1.1.1` and `8.8.8.8`.

Do not set the router DNS to `1.1.1.1`. Do not leave it blank. Blank means "use the router," and the router then asks the ISP, and the ISP still says Ryobi.

The router UI is in a different place on every box. You are looking for **DHCP**, **LAN**, or **DNS server**. Not "port forward." Not "DNS host name." One field: DNS server = the Home Assistant IP.

If the router has no DNS field and you already run UniFi, pfSense, OPNsense, or OpenWrt, add the one rewrite there instead and turn this add-on's `dns_enabled` off:

| Where | What |
|---|---|
| UniFi | Settings → Routing → DNS → Add static entry. Domain `tti.tiwiconnect.com`, IP = Home Assistant |
| pfSense / OPNsense | Services → DNS Resolver → Host Overrides. Host `tti`, Domain `tiwiconnect.com`, IP = Home Assistant |
| OpenWrt | Network → DHCP and DNS → Addresses: `/tti.tiwiconnect.com/<Home Assistant IP>` |
| AdGuard or Pi-hole | One rewrite, same name, same IP. Then `dns_enabled` off on this add-on |

Pick one place. A rewrite in AdGuard plus this add-on's dnsmasq plus a router DNS change will fight, and the lookup will randomly still return Ryobi.

## 4. Make devices actually notice

Phones and the opener cache DNS until the DHCP lease renews. Reboot the phone you test with, or toggle Wi-Fi. The opener may need a power cycle. Reboot Home Assistant too if it was already running. Home Assistant has its own DNS cache.

Android "Private DNS" and iCloud Private Relay ignore your router. Turn those off while testing or the phone will never ask the add-on.

## 5. Prove the name lookup before opening Home Assistant

On a computer joined to the same Wi-Fi, not a VPN:

```bash
nslookup tti.tiwiconnect.com
```

The address must be the Home Assistant IP from the log. A public address means this computer is not using the add-on. Stop here and fix the router. Nothing in Home Assistant will work until this prints the private IP.

Run it once more **on the Home Assistant machine** (Settings → Add-ons → Terminal & SSH, or the host shell):

```bash
nslookup tti.tiwiconnect.com
```

Same answer. If the laptop is right and Home Assistant is wrong, Home Assistant is not using the router DNS. Settings → System → Network → DNS: set it to the same IP, or clear it so Home Assistant takes DNS from DHCP.

## 6. Tell the Ryobi integration to use that name

**Settings → Devices & services → Ryobi Garage Door → Configure** (the gear, then Configure).

Set **Host** to:

```
http://tti.tiwiconnect.com
```

The name is the DNS lookup. The `http://` is required so Home Assistant uses port 80, which is where the add-on is listening. If you leave Host as `tti.tiwiconnect.com` with no prefix, Home Assistant uses HTTPS on port 443 and rejects the certificate this add-on generates. That looks like a DNS failure. It is not. The lookup worked and the certificate check failed.

Username and password can be the real Ryobi ones. With the add-on they are not checked against Ryobi.

## 7. Prove Home Assistant is talking to the add-on

In the add-on log, within a minute:

```
GET /api/devices/<your device_id>
```

with status 200. In Home Assistant the sensor **Server Connection Type** should say **Local Server**.

If nslookup is correct and the log never shows that GET, the integration Host is still the cloud name without `http://`, or Home Assistant itself resolved a different address than your laptop. Repeat step 5 on the Home Assistant machine.

---

## What you should see when a command is sent

In `local` mode a healthy opener logs `Opener <id> connected`, then `authorized locally`, then `registered`. After a light command, a `State change ... light_state` line follows the opener's own telemetry. That telemetry is the proof the hardware acted.

The add-on log shows the WebSocket command and the dashboard changes. That means Home Assistant reached the add-on. It does not, by itself, prove the physical door moved. If the opener never connects (nothing in the log from the opener's IP), it is still talking to Ryobi. The usual causes are: the opener got a different DNS server, Private DNS, or it refused the add-on's certificate. The log is the check. A public address from `nslookup` on a phone next to the opener means the opener will miss it too.

To drive a relay or an ESP from a command anyway, set `command_webhook_url`. See `examples/esphome_ryobi.yaml` in the repository.

---

## Opener certificate (required for `local` mode)

The opener only finishes TLS with a certificate that chains to **GlobalSign Root CA**. It does not check the hostname, so a certificate for a domain you own works. A self-signed certificate is rejected: the opener resets the connection right after the Certificate message, and no add-on setting changes that. Google Trust Services (GTS) certificates chain to GlobalSign and are the verified option (2026-10-21). Let's Encrypt chains to ISRG and has not been tested.

You need:
1. A domain on Cloudflare, for example `ryobi-gdo.example.com`. The name does not need to resolve to anything; it only proves ownership through a DNS TXT record.
2. A Cloudflare API token (below).
3. A Google Trust Services ACME account (an EAB key, below).
4. [lego](https://go-acme.github.io/lego/) on any computer.

### Get the Cloudflare API token

1. Log in at https://dash.cloudflare.com, open the profile icon (top right) → **My Profile** → **API Tokens**.
2. **Create Token** → template **Edit zone DNS** → **Use template**.
3. Permissions: `Zone` / `DNS` / `Edit`. Add a second row `Zone` / `Zone` / `Read` (lego uses it to find the zone).
4. Zone Resources: `Include` / `Specific zone` / your domain. Leave the rest at default.
5. **Continue to summary** → **Create Token**. Copy the token now; Cloudflare shows it once. Store it in a password manager. It never goes into the add-on options.
6. Optional check: Cloudflare shows a `curl` test on the same page. It should say the token is valid and active.

Revoke it from the same page whenever you like. It is only needed again at renewal.

### Get a Google Trust Services EAB key (once)

In a Google Cloud project: enable the **Public Certificate Authority API**, then in Cloud Shell run:

```bash
gcloud publicca external-account-keys create
```

It prints a `keyId` and a `b64MacKey`. Each pair works for one account registration only.

### Issue the certificate

```bash
export CF_DNS_API_TOKEN=<the Cloudflare token>
lego --server https://dv.acme-v02.api.pki.goog/directory \
  --eab --kid <keyId> --hmac <b64MacKey> \
  --email you@example.com --accept-tos \
  --dns cloudflare --dns.resolvers 1.1.1.1:53 \
  --key-type rsa2048 --preferred-chain "GlobalSign Root CA" \
  --domains ryobi-gdo.example.com run
```

The files land in `.lego/certificates/`. Paste the **full** `ryobi-gdo.example.com.crt` (all certificates in it) into `opener_cert_pem` and `ryobi-gdo.example.com.key` into `opener_key_pem`. Restart the add-on. The log should show `Opener <id> connected` and `authorized locally` within a minute or two.

**Renewal:** GTS certificates last 90 days. Before expiry run the same command with `renew` instead of `run`, from the same folder and with `CF_DNS_API_TOKEN` set. The EAB flags are not needed again. Then paste the new files in. Keep a copy of the PEMs outside Home Assistant: reinstalling the add-on clears the options.

---

## What works in local mode

Verified 2026-11-01 on a GD200 (firmware 1.0.7) with no Ryobi cloud. "Telemetry" is the opener's own status message; "command" is Home Assistant controlling it.

| Integration entity | Opener module (type / port) | Telemetry | Command |
|---|---|---|---|
| Cover (door) | 5 / 7 | Yes: closed, open, closing, opening, fault, position | Open and close, verified live |
| Light switch | 5 / 7 | Yes | On and off, verified live |
| Battery sensor | 6 / 8 | Received, but the value is unverified (always 100); see [#15](https://github.com/catduckgnaf/ryobi-local-server/issues/15) | n/a |
| Wi-Fi signal sensor | `wifiClientStatusSet` | Yes, but only seen at connect, so it may be stale; see [#16](https://github.com/catduckgnaf/ryobi-local-server/issues/16) | n/a |
| Server connection sensors | add-on link | Yes | n/a |
| Park assist (binary sensor and switch) | 1 / 3 | Yes (on/off) | Rejected, not captured |
| Bluetooth speaker | 2 / 2 | Opener sends it, not decoded | Rejected |
| Inflator | 4 / 0 | Opener sends it, not decoded | Rejected |
| Fan, fan speed | not fitted on the test opener | No | Rejected |
| Camera | possibly 7 / 9 | No (also broken on cloud); see [#17](https://github.com/catduckgnaf/ryobi-local-server/issues/17) | No |
| Motion, safety beam, vacation mode, microphone | unknown | No | Rejected |

Rejected commands return an error and change nothing. They are not guessed. Mapping the rest is tracked in the GitHub issues.

---

## Docker

The Home Assistant add-on is the setup above. Docker does not include the DNS server unless you start the `ryobi-dns` service in this repository's `docker-compose.yml`. See the README section **Docker**.
