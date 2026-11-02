"""Shared framing for JSON commands and length-delimited binary payloads."""

import json


MAX_HEADER_BYTES = 65536


class ProtocolError(Exception):
    def __init__(self, code, message, *, fatal=False):
        super().__init__(message)
        self.code = code
        self.fatal = fatal


class PeerDisconnected(Exception):
    """The peer closed the connection before a complete frame arrived."""


class Connection:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = bytearray()
        self.sending_payload = False

    def receive_header(self, max_bytes=MAX_HEADER_BYTES):
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                if max_bytes is not None and newline + 1 > max_bytes:
                    raise ProtocolError("HEADER_TOO_LARGE", f"Header exceeds {max_bytes} bytes", fatal=True)
                raw = bytes(self.buffer[:newline])
                del self.buffer[:newline + 1]
                break
            if max_bytes is not None and len(self.buffer) >= max_bytes:
                raise ProtocolError("HEADER_TOO_LARGE", f"Header exceeds {max_bytes} bytes", fatal=True)
            read_size = 65536 if max_bytes is None else min(65536, max_bytes - len(self.buffer))
            data = self.sock.recv(read_size)
            if not data:
                if self.buffer:
                    raise PeerDisconnected("Peer disconnected during a header")
                return None
            self.buffer.extend(data)
        try:
            header = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise ProtocolError("INVALID_HEADER", "Header must be a UTF-8 JSON object", fatal=True) from exc
        if not isinstance(header, dict):
            raise ProtocolError("INVALID_HEADER", "Header must be a JSON object", fatal=True)
        return header

    def receive_chunk(self, maximum):
        if self.buffer:
            data = bytes(self.buffer[:maximum])
            del self.buffer[:maximum]
            return data
        data = self.sock.recv(maximum)
        if not data:
            raise PeerDisconnected("Peer disconnected before all file bytes arrived")
        return data

    def send_header(self, header):
        self.sock.sendall(encode_header(header))


def encode_header(header):
    return (json.dumps(header, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
