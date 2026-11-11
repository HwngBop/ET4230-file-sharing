"""End-to-end TCP smoke test: upload, list, download, SHA-256, quit.

Run from repository root (client machine):
    python scripts/smoke_test.py --host 192.168.1.10 --size 10485760
"""
import argparse
import hashlib
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common.protocol import Connection, PeerDisconnected, ProtocolError


def require_response(connection, status, command):
    response = connection.receive_header()
    if response is None or response.get("status") != status or response.get("command") != command:
        raise RuntimeError(f"Unexpected response for {command}: {response}")
    return response


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Actual server IPv4 address")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--filename", default="sprint1-smoke.bin")
    parser.add_argument("--size", type=int, default=10485760, help="Payload size in bytes (default 10 MiB)")
    args = parser.parse_args(argv)
    if args.size < 0 or not 1 <= args.port <= 65535:
        parser.error("size must be nonnegative and port must be between 1 and 65535")
    if args.size > 128 * 1024 * 1024:
        parser.error("smoke-test size capped at 128 MiB to limit RAM use")

    payload = os.urandom(args.size)
    expected = hashlib.sha256(payload).hexdigest()
    try:
        with socket.create_connection((args.host, args.port), timeout=30) as sock:
            sock.settimeout(30)
            connection = Connection(sock)
            started = time.perf_counter()
            connection.send_header({
                "command": "UPLOAD", "filename": args.filename,
                "file_size": len(payload), "sha256": expected,
            })
            require_response(connection, "READY", "UPLOAD")
            sock.sendall(payload)
            confirmation = require_response(connection, "SUCCESS", "UPLOAD")
            if confirmation.get("sha256") != expected:
                raise RuntimeError("Server upload checksum mismatch")
            upload_sec = time.perf_counter() - started
            print(f"UPLOAD OK: {args.filename}, SHA-256 MATCH, {upload_sec:.3f}s")

            connection.send_header({"command": "LIST"})
            listing = require_response(connection, "OK", "LIST")
            if args.filename not in listing.get("files", []):
                raise RuntimeError("Uploaded file is missing from LIST")
            print("LIST OK")

            started = time.perf_counter()
            connection.send_header({"command": "DOWNLOAD", "filename": args.filename})
            metadata = require_response(connection, "OK", "DOWNLOAD")
            if metadata.get("file_size") != len(payload):
                raise RuntimeError("Download file_size differs from upload")
            received_hash = hashlib.sha256()
            received = bytearray()
            while len(received) < len(payload):
                chunk = connection.receive_chunk(min(65536, len(payload) - len(received)))
                received_hash.update(chunk)
                received.extend(chunk)
            confirmation = require_response(connection, "SUCCESS", "DOWNLOAD")
            if confirmation.get("sha256") != received_hash.hexdigest():
                raise RuntimeError("Server and client download SHA-256 disagree")
            if received_hash.hexdigest() != expected or received != payload:
                raise RuntimeError("Downloaded file differs from upload")
            download_sec = time.perf_counter() - started
            print(f"DOWNLOAD OK: SHA-256 MATCH, {download_sec:.3f}s")

            connection.send_header({"command": "QUIT"})
            require_response(connection, "OK", "QUIT")
            print("QUIT OK")
            print(f"Upload: {args.size*8/upload_sec/1e6:.2f} Mbps; Download: {args.size*8/download_sec/1e6:.2f} Mbps")
    except (OSError, RuntimeError, PeerDisconnected, ProtocolError) as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
