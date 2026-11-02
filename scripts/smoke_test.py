"""Verify a running Sprint 1 server over localhost or a LAN connection."""

import argparse
import os
import socket
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.protocol import Connection, PeerDisconnected, ProtocolError


def require_response(connection, status, command):
    response = connection.receive_header(max_bytes=None)
    if response is None or response.get("status") != status or response.get("command") != command:
        raise RuntimeError(f"Unexpected response for {command}: {response}")
    return response


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Actual server IPv4 address")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--filename", default="sprint1-smoke.bin", help="Server file to create or overwrite")
    parser.add_argument("--size", type=int, default=1048576, help="Payload size in bytes")
    args = parser.parse_args(argv)
    if args.size < 0 or not 1 <= args.port <= 65535:
        parser.error("size must be nonnegative and port must be between 1 and 65535")
    payload = os.urandom(args.size)
    try:
        with socket.create_connection((args.host, args.port), timeout=30) as sock:
            connection = Connection(sock)
            connection.send_header({"command": "UPLOAD", "filename": args.filename, "file_size": len(payload)})
            require_response(connection, "READY", "UPLOAD")
            sock.sendall(payload)
            require_response(connection, "SUCCESS", "UPLOAD")
            print(f"UPLOAD OK: {args.filename}, {len(payload)} bytes")

            connection.send_header({"command": "LIST"})
            listing = require_response(connection, "OK", "LIST")
            if args.filename not in listing["files"]:
                raise RuntimeError("Uploaded file is missing from LIST")
            print(f"LIST OK: {listing['files']}")

            connection.send_header({"command": "DOWNLOAD", "filename": args.filename})
            metadata = require_response(connection, "OK", "DOWNLOAD")
            if metadata.get("file_size") != len(payload):
                raise RuntimeError("Download file_size differs from upload")
            received = bytearray()
            while len(received) < len(payload):
                received.extend(connection.receive_chunk(min(65536, len(payload) - len(received))))
            require_response(connection, "SUCCESS", "DOWNLOAD")
            if received != payload:
                raise RuntimeError("Downloaded bytes differ from uploaded bytes")
            print(f"DOWNLOAD OK: {len(received)} bytes match exactly")

            connection.send_header({"command": "QUIT"})
            require_response(connection, "OK", "QUIT")
            print("QUIT OK")
    except (OSError, RuntimeError, PeerDisconnected, ProtocolError) as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
