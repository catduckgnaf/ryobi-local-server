## 1.2.5

- Fix: Prevent `opener_cert_pem` from writing literal `null` into certificate files when optional configuration is omitted.
- Fix: Add automatic fallback to self-signed `server.crt` / `server.key` if custom opener certificates fail to load.
- Fix: Ensure port 443 TLS listener stays active for physical GDO hardware connections.

# Changelog

## 1.2.4

### Features
- Keep phones and browsers connected to the Ryobi cloud through SNI pass-through.
- Offer experimental, explicitly enabled cloud-authenticated opener takeover. Cloud relay takes precedence and remains available for fallback.
- Send captured opener OPEN and light commands and display returned sparse telemetry without optimistic state updates.

### Fixes
- Support the physical opener's legacy TLS handshake and configured certificate chain.
- Reject incomplete opener authentication headers and ordinary-client telemetry injection in takeover mode.
- Reject disconnected or unsupported physical commands rather than reporting simulated success.
- Refuse relay/takeover startup when the cloud IPv4 address is missing or nonpublic, instead of silently routing the opener locally.
- Keep Wi-Fi SSID/IP values out of normal INFO logs and include the TLS bridge dependency in Python package metadata.

### Technical details and limits
- Add bounded authorization buffering, cloud TLS verification, disconnect cleanup, and bundled-source parity coverage.
- Offline suite: 73 tests passed before release packaging; final release validation is recorded in the release PR.
- Hardware takeover, phone-on-home-WiFi behavior, and physical commands are not yet validated. Every takeover reconnect still requires cloud authentication.
- No guessed CLOSE command, inferred movement direction, or cloud-independent startup is included. Keep cloud relay enabled until separately authorized live validation.
- Implementation: PR #8 and the preceding TLS/SNI branch work.
