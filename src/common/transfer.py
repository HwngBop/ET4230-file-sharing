"""File-transfer helpers; use Connection for receives to preserve TCP buffering.

The application-layer protocol remains JSON+LF followed by exactly file_size
binary bytes. This module does not send or parse protocol headers.
"""

import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path

from common.protocol import PeerDisconnected

log = logging.getLogger("common.transfer")

KB = 1024
DEFAULT_CHUNK_SIZE = 64 * KB
SUPPORTED_CHUNK_SIZES = (4 * KB, 16 * KB, 64 * KB, 256 * KB, 1024 * KB)
MATCH = "MATCH"
MISMATCH = "MISMATCH"
_SHA256_HEX = re.compile(r"[0-9a-fA-F]{64}\Z")


def validate_chunk_size(chunk_size):
    if type(chunk_size) is not int or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer (bytes)")
    return chunk_size


def calculate_sha256(file_path, chunk_size=DEFAULT_CHUNK_SIZE):
    validate_chunk_size(chunk_size)
    digest = hashlib.sha256()
    with open(file_path, "rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def compare_checksums(expected_hex, actual_hex):
    """MATCH only when both values are valid 64-digit SHA-256 hex strings."""
    if not isinstance(expected_hex, str) or not _SHA256_HEX.fullmatch(expected_hex):
        return MISMATCH
    if not isinstance(actual_hex, str) or not _SHA256_HEX.fullmatch(actual_hex):
        return MISMATCH
    return MATCH if expected_hex.lower() == actual_hex.lower() else MISMATCH


def recv_exact(source, n_bytes):
    """Read exactly n_bytes, preserving buffered payload bytes for Connection."""
    if type(n_bytes) is not int or n_bytes < 0:
        raise ValueError("n_bytes must be a non-negative integer")
    read = source.receive_chunk if hasattr(source, "receive_chunk") else source.recv
    buf = bytearray()
    while len(buf) < n_bytes:
        part = read(n_bytes - len(buf))
        if not part:
            raise PeerDisconnected(
                f"Connection closed: need {n_bytes} bytes, got {len(buf)}"
            )
        buf.extend(part)
    return bytes(buf)


def send_file_data(sock, file_path, chunk_size=DEFAULT_CHUNK_SIZE, *, expected_size=None):
    """Send exactly expected_size file bytes; never send extra bytes into next frame.

    The caller must send the UPLOAD header and receive READY first. If an
    exception occurs after bytes were sent, close the connection (the peer may
    still be waiting for its remaining declared file bytes).
    """
    validate_chunk_size(chunk_size)
    if expected_size is None:
        expected_size = os.stat(file_path).st_size
    if type(expected_size) is not int or expected_size < 0:
        raise ValueError("expected_size must be a non-negative integer")
    remaining = expected_size
    with open(file_path, "rb") as stream:
        while remaining:
            block = stream.read(min(chunk_size, remaining))
            if not block:
                raise OSError("Source file became shorter than declared file_size")
            sock.sendall(block)
            remaining -= len(block)
        if stream.read(1):
            raise OSError("Source file became larger than declared file_size")
    log.info("sent %d bytes of %s (chunk=%d)", expected_size, file_path, chunk_size)
    return expected_size


def receive_file_data(conn, dest_path, file_size, chunk_size=DEFAULT_CHUNK_SIZE, *, expected_sha256=None):
    """Receive exact file bytes into a temp file, then atomically replace target.

    If expected_sha256 is passed, reject a mismatch BEFORE publishing the file.
    With expected_sha256=None, only size completeness is checked: the caller
    must not claim source-to-destination integrity verification.
    """
    validate_chunk_size(chunk_size)
    if type(file_size) is not int or file_size < 0:
        raise ValueError("file_size must be a non-negative integer")
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str)
        or not _SHA256_HEX.fullmatch(expected_sha256)
    ):
        raise ValueError("expected_sha256 must be 64 hexadecimal characters")

    target = Path(dest_path)
    digest = hashlib.sha256()
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=f".{target.name}.",
            suffix=".part", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            remaining = file_size
            while remaining:
                block = recv_exact(conn, min(chunk_size, remaining))
                written = stream.write(block)
                if written != len(block):
                    raise OSError("Short write while receiving file")
                digest.update(block)
                remaining -= written

        actual_hex = digest.hexdigest()
        if expected_sha256 is not None and compare_checksums(expected_sha256, actual_hex) != MATCH:
            raise ValueError("CHECKSUM_MISMATCH: received data differs from source")
        os.replace(temporary_path, target)
        log.info("received %d bytes -> %s (chunk=%d) sha256=%s", file_size, target, chunk_size, actual_hex)
        return actual_hex
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
