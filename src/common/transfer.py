import hashlib
import logging

from common.protocol import PeerDisconnected

log = logging.getLogger("common.transfer")

KB = 1024
DEFAULT_CHUNK_SIZE = 64 * KB
SUPPORTED_CHUNK_SIZES = (4 * KB, 16 * KB, 64 * KB, 256 * KB, 1024 * KB)
MATCH = "MATCH"
MISMATCH = "MISMATCH"


def validate_chunk_size(chunk_size):
    if type(chunk_size) is not int or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer (bytes)")
    return chunk_size


def calculate_sha256(file_path, chunk_size=DEFAULT_CHUNK_SIZE):
    validate_chunk_size(chunk_size)
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def compare_checksums(expected_hex, actual_hex):
    return MATCH if str(expected_hex).lower() == str(actual_hex).lower() else MISMATCH


def recv_exact(source, n_bytes):
    if type(n_bytes) is not int or n_bytes < 0:
        raise ValueError("n_bytes must be a non-negative integer")
    read = source.receive_chunk if hasattr(source, "receive_chunk") else source.recv
    buf = bytearray()
    while len(buf) < n_bytes:
        part = read(n_bytes - len(buf))
        if not part:
            raise PeerDisconnected(f"Connection closed: need {n_bytes} bytes, got {len(buf)}")
        buf.extend(part)
    return bytes(buf)


def send_file_data(sock, file_path, chunk_size=DEFAULT_CHUNK_SIZE):
    validate_chunk_size(chunk_size)
    sent = 0
    with open(file_path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            sock.sendall(block)
            sent += len(block)
    log.info("sent %d bytes of %s (chunk=%d)", sent, file_path, chunk_size)
    return sent


def receive_file_data(conn, dest_path, file_size, chunk_size=DEFAULT_CHUNK_SIZE):
    validate_chunk_size(chunk_size)
    if type(file_size) is not int or file_size < 0:
        raise ValueError("file_size must be a non-negative integer")
    h = hashlib.sha256()
    left = file_size
    with open(dest_path, "wb") as f:
        while left > 0:
            block = recv_exact(conn, min(chunk_size, left))
            f.write(block)
            h.update(block)
            left -= len(block)
    digest = h.hexdigest()
    log.info("received %d bytes -> %s (chunk=%d) sha256=%s", file_size, dest_path, chunk_size, digest)
    return digest
