"""
Bitcoin P2P handshake reachability check.

Confirms a claimed (ip, port) is a real, listening Bitcoin node by performing
the Bitcoin protocol handshake: send a `version` message, then read frames
until the peer's own `version` comes back. The peer's version payload is
parsed so the caller learns the node's advertised user agent, protocol
version, and best block height -- enough to tell a real node from a socket
that merely accepts connections.

This is the first, thinnest bar described in the whitepaper. It does NOT
prove uptime, sync status, or that the node will still be there tomorrow.
For continuous tracking, model a crawler on Bitnodes (github.com/ayeowch/bitnodes).

Reference: https://developer.bitcoin.org/reference/p2p_networking.html

Limitations to close before production:
- Clearnet IPv4/IPv6 only. .onion needs a SOCKS5 connection through Tor.
- The same machine can answer for many claimed entries; pair with per-subnet
  or per-ASN caps and a minimum node age if Sybil entries become a problem.
"""

from __future__ import annotations

import socket
import struct
import hashlib
import time
from dataclasses import dataclass

MAGIC_MAINNET = bytes.fromhex("f9beb4d9")
MAGIC_TESTNET = bytes.fromhex("0b110907")
PROTOCOL_VERSION = 70016
HEADER_LEN = 24


@dataclass
class NodeCheck:
    reachable: bool
    address: str
    port: int
    protocol_version: int | None = None
    user_agent: str | None = None
    start_height: int | None = None
    services: int | None = None
    latency_ms: float | None = None
    error: str | None = None

    def __str__(self) -> str:
        if not self.reachable:
            return f"{self.address}:{self.port} UNREACHABLE ({self.error})"
        return (
            f"{self.address}:{self.port} OK  "
            f"agent={self.user_agent!r} height={self.start_height} "
            f"proto={self.protocol_version} {self.latency_ms:.0f}ms"
        )


def _checksum(payload: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]


def _build_message(magic: bytes, command: str, payload: bytes) -> bytes:
    cmd = command.encode("ascii").ljust(12, b"\x00")
    return magic + cmd + struct.pack("<I", len(payload)) + _checksum(payload) + payload


def _net_addr() -> bytes:
    # services(8) + ip(16) + port(2); zeroed is accepted for a probe
    return b"\x00" * 26


def _version_payload() -> bytes:
    return (
        struct.pack("<i", PROTOCOL_VERSION)
        + struct.pack("<Q", 0)                       # services
        + struct.pack("<q", int(time.time()))        # timestamp
        + _net_addr()                                # addr_recv
        + _net_addr()                                # addr_from
        + struct.pack("<Q", 0)                       # nonce
        + b"\x00"                                     # user agent (0-len varstr)
        + struct.pack("<i", 0)                        # start height
        + b"\x00"                                     # relay
    )


def _read_varint(buf: bytes, offset: int) -> tuple[int, int]:
    first = buf[offset]
    if first < 0xFD:
        return first, offset + 1
    if first == 0xFD:
        return struct.unpack_from("<H", buf, offset + 1)[0], offset + 3
    if first == 0xFE:
        return struct.unpack_from("<I", buf, offset + 1)[0], offset + 5
    return struct.unpack_from("<Q", buf, offset + 1)[0], offset + 9


def _parse_version_payload(payload: bytes) -> dict:
    proto = struct.unpack_from("<i", payload, 0)[0]
    services = struct.unpack_from("<Q", payload, 4)[0]
    offset = 4 + 8 + 8 + 26 + 26 + 8  # proto, services, time, addr_recv, addr_from, nonce
    ua_len, offset = _read_varint(payload, offset)
    user_agent = payload[offset:offset + ua_len].decode("ascii", "replace")
    offset += ua_len
    start_height = struct.unpack_from("<i", payload, offset)[0]
    return {
        "protocol_version": proto,
        "services": services,
        "user_agent": user_agent,
        "start_height": start_height,
    }


def check_node(ip: str, port: int = 8333, timeout: float = 5.0,
               magic: bytes = MAGIC_MAINNET) -> NodeCheck:
    """Probe a node; return a structured result describing what answered."""
    start = time.monotonic()
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(_build_message(magic, "version", _version_payload()))

            buffer = b""
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk

                # Parse complete frames out of the buffer.
                while len(buffer) >= HEADER_LEN:
                    if buffer[:4] != magic:
                        # resync to next magic if framing slipped
                        idx = buffer.find(magic, 1)
                        if idx == -1:
                            buffer = b""
                            break
                        buffer = buffer[idx:]
                        continue
                    length = struct.unpack_from("<I", buffer, 16)[0]
                    if len(buffer) < HEADER_LEN + length:
                        break  # wait for the rest of this frame
                    command = buffer[4:16].rstrip(b"\x00").decode("ascii", "replace")
                    payload = buffer[HEADER_LEN:HEADER_LEN + length]
                    buffer = buffer[HEADER_LEN + length:]

                    if command == "version":
                        info = _parse_version_payload(payload)
                        # be a good peer: acknowledge
                        try:
                            sock.sendall(_build_message(magic, "verack", b""))
                        except OSError:
                            pass
                        return NodeCheck(
                            reachable=True, address=ip, port=port,
                            latency_ms=(time.monotonic() - start) * 1000,
                            **info,
                        )
            return NodeCheck(reachable=False, address=ip, port=port,
                             error="no version reply")
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        return NodeCheck(reachable=False, address=ip, port=port, error=str(exc))


if __name__ == "__main__":
    import sys
    ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8333
    print(check_node(ip, port))
