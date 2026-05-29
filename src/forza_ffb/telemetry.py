"""UDP listener for Forza "Data Out" telemetry.

Forza sends one-way UDP datagrams; we just bind and read. Pure standard library, so this
runs identically on Windows and (for testing) on Linux/WSL.
"""

from __future__ import annotations

import logging
import socket
from typing import Optional

from .packet import Telemetry, parse

log = logging.getLogger("forza_ffb.telemetry")


class TelemetryListener:
    """Bind a UDP socket and hand back parsed :class:`Telemetry` frames.

    Use as a context manager::

        with TelemetryListener("127.0.0.1", 2066) as rx:
            while True:
                frame = rx.recv()        # Telemetry, or None on receive timeout
    """

    def __init__(self, ip: str = "127.0.0.1", port: int = 2066, recv_timeout: float = 0.25):
        self.ip = ip
        self.port = port
        self.recv_timeout = recv_timeout
        self._sock: Optional[socket.socket] = None

    def open(self) -> "TelemetryListener":
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.ip, self.port))
        sock.settimeout(self.recv_timeout)
        self._sock = sock
        log.info("listening for Forza telemetry on %s:%d", self.ip, self.port)
        return self

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    @property
    def port_bound(self) -> int:
        """Actual bound port (useful when binding to port 0 in tests)."""
        assert self._sock is not None, "listener not open"
        return self._sock.getsockname()[1]

    def recv(self) -> Optional[Telemetry]:
        """Read one datagram. Returns ``None`` on receive timeout or a malformed packet."""
        assert self._sock is not None, "listener not open — call open() or use 'with'"
        try:
            data, _addr = self._sock.recvfrom(2048)
        except socket.timeout:
            return None
        try:
            return parse(data)
        except ValueError as exc:
            log.warning("ignoring malformed packet (%d bytes): %s", len(data), exc)
            return None

    def __enter__(self) -> "TelemetryListener":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()
