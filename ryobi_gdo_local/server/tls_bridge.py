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
import socket
import threading

from tlslite.api import HandshakeSettings, SessionCache, TLSConnection, X509CertChain, parsePEMKey

LOGGER = logging.getLogger(__name__)


def _handshake_settings() -> HandshakeSettings:
    settings = HandshakeSettings()
    settings.minVersion = (3, 1)
    settings.maxVersion = (3, 3)
    settings.defaultCurve = "secp256r1"
    return settings


class OpenerTLSBridge:
    """Terminate TLS for the opener and relay it to the plain HTTP site."""

    def __init__(self, host: str, port: int, certfile: str, keyfile: str, upstream_port: int) -> None:
        self._host = host
        self._port = port
        self._upstream_port = upstream_port
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
            upstream = socket.create_connection(("127.0.0.1", self._upstream_port), timeout=10)
        except OSError as err:
            LOGGER.error("Could not reach the HTTP site on port %d: %s", self._upstream_port, err)
            tls.close()
            return
        upstream.settimeout(None)

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
                    if first:
                        # aiohttp answers "Connection: upgrade"; the cloud and
                        # most embedded clients expect "Upgrade".
                        data = data.replace(b"\r\nConnection: upgrade\r\n", b"\r\nConnection: Upgrade\r\n", 1)
                        first = False
                    LOGGER.debug("to opener %s: %s", addr, _preview(data))
                    tls.sendall(data)
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("to opener %s ended: %r", addr, err)
            finally:
                close_both()

        threading.Thread(target=to_opener, daemon=True).start()
        try:
            while data := tls.recv(16384):
                LOGGER.debug("from opener %s: %s", addr, _preview(data))
                upstream.sendall(data)
        except Exception as err:  # noqa: BLE001
            LOGGER.debug("from opener %s ended: %r", addr, err)
        finally:
            close_both()
            LOGGER.info("Opener TLS connection from %s closed", addr)


def _preview(data: bytes, limit: int = 600) -> str:
    """Printable text when the bytes are text, hex otherwise."""
    head = data[:limit]
    text = head.decode("latin-1")
    if all(ch.isprintable() or ch in "\r\n\t" for ch in text):
        return f"{len(data)}B {text!r}"
    return f"{len(data)}B hex {head.hex()}"
