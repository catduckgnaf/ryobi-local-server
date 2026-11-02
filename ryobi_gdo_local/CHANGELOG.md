## 1.2.8 (2026-11-01)

- Fix: Door state from opener telemetry now maps closed (0) and closing (2) as well as open (1) and opening (3). Before, any value except open was reported as unknown, so Home Assistant kept showing **open** after the door closed. Confirmed against live telemetry on 2026-11-01 ET: at 22:48 the door went opening to open (position 1 to 94), and at 22:53 it went closing to closed (94 to 0).
- Door commands are unchanged. Only the captured OPEN is sent; CLOSE is still rejected.
- Tests: 87 offline tests pass.

## 1.2.7 (2026-11-01)

- Fix: An ordinary Home Assistant or app connection that sends `srvWebSocketAuth` with a `varName` no longer claims the physical opener's command socket. Commands with no physical opener now return a JSON-RPC error and change no state (#10).
- Fix: A command the server cannot deliver to the opener returns a JSON-RPC error instead of an OK acknowledgement (#10).
- Docs: README and DOCS describe the opener modes, the verified local-only setup, and the certificate requirement.
- Verified live 2026-11-01 on a GD200 (fw 1.0.7) in `opener_mode: local` with `cloud_relay: false`: local authorization on connect, and a light on/off round trip confirmed by opener telemetry.
- Tests: 85 offline tests pass.

## 1.2.6 (2026-11-01)

- Fix: Local mode now authorizes the physical opener immediately after the WebSocket upgrade. The real cloud speaks first (`authorizedWebSocket` about 3 s after the 101, captured 2026-11-01 through cloud relay); the opener only sends `wskClientRegister`/`wskServerRegister` after that. The old server waited for `wskServerRegister`, so both sides waited and the opener dropped the session after about 20 s. Fixes the local half of #13.
- Fix: Takeover no longer rejects the cloud's authorization when it arrives before the opener's registration frame (`cloud authorization preceded opener registration`, `takeover.py:116`). That ordering is the normal one. Fixes #13.
- Fix: Commands fail closed and the stale socket is dropped when the opener's WebSocket has closed.
- Tests: regression test for authorize-on-connect; 84 offline tests pass.

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
