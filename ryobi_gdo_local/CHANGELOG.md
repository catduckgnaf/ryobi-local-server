# Changelog

## 1.2.0

- Docs: the recommended setup no longer needs any DNS changes. Point the
  ryobi_gdo integration's Server field at `http://<HA IP>` and you're done.
- Built-in DNS server and HTTPS listener are now off by default for new installs
  and marked experimental. Existing installs keep their saved options.
- New options: `https_enabled`, `https_port`, `advertise_ip`.
- Added `build.yaml` so the add-on builds on the Python base image on every arch.
- Dropped armhf, armv7 and i386, which Home Assistant no longer supports.
- Removed the unneeded `NET_ADMIN` privilege.
- Added a watchdog so Supervisor restarts the add-on if the server hangs.
- dnsmasq now binds only to the advertised IP, avoiding conflicts with other
  DNS services on the host, and a failed dnsmasq start is reported clearly.
- The startup log prints the exact Server value to enter in the integration.
- Server config is generated with jq, so device names with quotes no longer
  break it.
