"""
TLS front end for the physical opener on port 443.

The GDO200's ClientHello offers one suite, TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256,
and one extension, signature_algorithms (SHA-1 only). It sends no
supported_groups extension. OpenSSL only picks an ECDHE curve from the
client's supported_groups list, so with none it drops the only suite and
answers NO_SHARED_CIPHER however the cipher string is set.

tlslite-ng falls back to a default curve when the extension is missing
(RFC 4492 section 5.1.1), so this bridge finishes the handshake with
tlslite-ng and relays the plaintext to the HTTP site on localhost.
"""

from __future__ import annotations

import logging
import os
import socket
import ssl
import threading
import time

from tlslite.api import HandshakeSettings, SessionCache, TLSConnection, X509CertChain, parsePEMKey

LOGGER = logging.getLogger(__name__)

CLOUD_HOST = "tti.tiwiconnect.com"
UPGRADE_DELAY = float(os.environ.get("OPENER_UPGRADE_DELAY", "0.25"))


def _handshake_settings() -> HandshakeSettings:
    settings = HandshakeSettings()
    settings.minVersion = (3, 1)
    settings.maxVersion = (3, 3)
    settings.defaultCurve = "secp256r1"
    return settings


class OpenerTLSBridge:
    """Terminate TLS for the opener and relay it to the plain HTTP site."""

    def __init__(
        self,
        host: str,
        port: int,
        certfile: str,
        keyfile: str,
        upstream_port: int,
        cloud_relay_ip: str = "",
    ) -> None:
        self._host = host
        self._port = port
        self._upstream_port = upstream_port
        # Capture mode: relay the opener's own session to the Ryobi cloud and
        # log it, to learn what the cloud says to the opener.
        self._cloud_relay_ip = cloud_relay_ip
        with open(certfile, encoding="utf-8") as handle:
            self._chain = X509CertChain()
            self._chain.parsePemList(handle.read())
        with open(keyfile, encoding="utf-8") as handle:
            self._key = parsePEMKey(handle.read(), private=True)
        self._settings = _handshake_settings()
        # The cloud's ServerHello carries a 32-byte session ID; tlslite-ng
        # only sends one when it has a session cache.
        self._sessions = SessionCache()
        self._sock: socket.socket | None = None

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._host, self._port))
        sock.listen(16)
        self._sock = sock
        threading.Thread(target=self._accept_loop, name="opener-tls", daemon=True).start()

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while True:
            raw, addr = self._sock.accept()
            threading.Thread(target=self._serve, args=(raw, addr), daemon=True).start()

    def _serve(self, raw: socket.socket, addr: tuple) -> None:
        raw.settimeout(30)
        tls = TLSConnection(raw)
        try:
            tls.handshakeServer(
                certChain=self._chain,
                privateKey=self._key,
                settings=self._settings,
                sessionCache=self._sessions,
            )
        except Exception as err:  # noqa: BLE001 - any failure ends this connection
            LOGGER.warning("TLS handshake failed from %s: %r", addr, err)
            raw.close()
            return
        raw.settimeout(None)
        LOGGER.info(
            "TLS handshake OK from %s: %s, %s",
            addr, tls.getVersionName(), tls.getCipherName(),
        )

        try:
            if self._cloud_relay_ip:
                cloud = socket.create_connection((self._cloud_relay_ip, 443), timeout=10)
                upstream = ssl.create_default_context().wrap_socket(cloud, server_hostname=CLOUD_HOST)
                LOGGER.info("Relaying opener %s to the Ryobi cloud at %s", addr, self._cloud_relay_ip)
            else:
                upstream = socket.create_connection(("127.0.0.1", self._upstream_port), timeout=10)
        except OSError as err:
            LOGGER.error("Could not open the upstream for opener %s: %s", addr, err)
            tls.close()
            return
        upstream.settimeout(None)
        from_log = _TrafficLog("from opener", addr)
        to_log = _TrafficLog("to opener", addr)

        def close_both() -> None:
            for closer in (tls.close, upstream.close):
                try:
                    closer()
                except Exception:  # noqa: BLE001
                    pass

        def to_opener() -> None:
            first = True
            try:
                while data := upstream.recv(16384):
                    if first and not self._cloud_relay_ip:
                        data = _cloud_style_upgrade(data)
                        # The cloud's 101 arrives after an internet round trip.
                        # Answered within a millisecond or two, the opener
                        # usually never starts talking.
                        time.sleep(UPGRADE_DELAY)
                        first = False
                    to_log.feed(data)
                    tls.sendall(data)
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("to opener %s ended: %r", addr, err)
            finally:
                close_both()

        threading.Thread(target=to_opener, daemon=True).start()
        try:
            while data := tls.recv(16384):
                from_log.feed(data)
                upstream.sendall(data)
        except Exception as err:  # noqa: BLE001
            LOGGER.debug("from opener %s ended: %r", addr, err)
        finally:
            close_both()
            LOGGER.info("Opener TLS connection from %s closed", addr)


def _cloud_style_upgrade(data: bytes) -> bytes:
    """
    Rewrite aiohttp's 101 response the way the Ryobi cloud sends it.

    The opener stays silent after aiohttp's 101 (Accept in the middle, a
    Server header after it) but talks at once after the cloud's, which ends
    with Sec-WebSocket-Accept:
      Date, Connection: Upgrade, Upgrade: websocket, Sec-WebSocket-Accept
    """
    head, sep, rest = data.partition(b"\r\n\r\n")
    if not sep or not head.startswith(b"HTTP/1.1 101"):
        return data
    headers = {}
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        headers[name.strip().lower()] = value.strip()
    accept = headers.get(b"sec-websocket-accept")
    if accept is None:
        return data
    lines = [b"HTTP/1.1 101 Switching Protocols"]
    if b"date" in headers:
        lines.append(b"Date: " + headers[b"date"])
    lines += [b"Connection: Upgrade", b"Upgrade: websocket", b"Sec-WebSocket-Accept: " + accept]
    return b"\r\n".join(lines) + b"\r\n\r\n" + rest


class _TrafficLog:
    """Debug-log one direction: the HTTP upgrade, then each WebSocket frame."""

    def __init__(self, direction: str, addr: tuple) -> None:
        self._label = f"{direction} {addr}"
        self._buf = b""
        self._in_frames = False

    def feed(self, data: bytes) -> None:
        if not LOGGER.isEnabledFor(logging.DEBUG):
            return
        self._buf += data
        if not self._in_frames:
            head, sep, rest = self._buf.partition(b"\r\n\r\n")
            if not sep:
                return
            LOGGER.debug("%s: %r", self._label, head.decode("latin-1"))
            self._buf, self._in_frames = rest, True
        while frame := self._next_frame():
            opcode, payload = frame
            if opcode == 1:
                shown = payload[:2000].decode("utf-8", "replace")
            else:
                shown = payload[:400].hex()
            LOGGER.debug("%s: ws op=%d %dB %s", self._label, opcode, len(payload), shown)

    def _next_frame(self) -> tuple[int, bytes] | None:
        buf = self._buf
        if len(buf) < 2:
            return None
        opcode, masked, size, pos = buf[0] & 0x0F, buf[1] & 0x80, buf[1] & 0x7F, 2
        if size == 126:
            if len(buf) < 4:
                return None
            size, pos = int.from_bytes(buf[2:4], "big"), 4
        elif size == 127:
            if len(buf) < 10:
                return None
            size, pos = int.from_bytes(buf[2:10], "big"), 10
        mask = b""
        if masked:
            mask, pos = buf[pos:pos + 4], pos + 4
        if len(buf) < pos + size:
            return None
        payload = buf[pos:pos + size]
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._buf = buf[pos + size:]
        return opcode, payload
