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

The add-on log shows the WebSocket command and the dashboard changes. That means Home Assistant reached the add-on. It does not, by itself, prove the physical door moved. If the opener never connects (nothing in the log from the opener's IP), it is still talking to Ryobi. The usual causes are: the opener got a different DNS server, Private DNS, or it refused the add-on's certificate. The log is the check. A public address from `nslookup` on a phone next to the opener means the opener will miss it too.

To drive a relay or an ESP from a command anyway, set `command_webhook_url`. See `examples/esphome_ryobi.yaml` in the repository.

---

## Docker

The Home Assistant add-on is the setup above. Docker does not include the DNS server unless you start the `ryobi-dns` service in this repository's `docker-compose.yml`. See the README section **Docker**.
