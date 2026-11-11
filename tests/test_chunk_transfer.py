import hashlib
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common.protocol import Connection, PeerDisconnected
from common.transfer import (SUPPORTED_CHUNK_SIZES, MATCH, MISMATCH,
                             calculate_sha256, compare_checksums, receive_file_data,
                             recv_exact, send_file_data)


class TrickleSock:
    def __init__(self, data, step=3):
        self.data, self.step, self.pos = bytes(data), step, 0

    def recv(self, n):
        k = min(self.step, n, len(self.data) - self.pos)
        out = self.data[self.pos:self.pos + k]
        self.pos += k
        return out


class RecvExactTests(unittest.TestCase):
    def test_partial_recv_on_raw_socket(self):
        data = os.urandom(100)
        self.assertEqual(recv_exact(TrickleSock(data, 3), 100), data)

    def test_partial_recv_on_connection(self):
        data = os.urandom(100)
        self.assertEqual(recv_exact(Connection(TrickleSock(data, 7)), 100), data)

    def test_uses_bytes_left_in_connection_buffer_after_header(self):
        payload = b"HELLO-FILE-BYTES"
        conn = Connection(TrickleSock(b'{"command":"X"}\n' + payload, 64))
        self.assertEqual(conn.receive_header(), {"command": "X"})
        self.assertEqual(recv_exact(conn, len(payload)), payload)

    def test_closed_early_raises(self):
        with self.assertRaises(PeerDisconnected):
            recv_exact(TrickleSock(b"abc"), 10)

    def test_zero_bytes(self):
        self.assertEqual(recv_exact(TrickleSock(b""), 0), b"")


class Sha256Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_known_value(self):
        p = self.dir / "abc.txt"
        p.write_bytes(b"abc")
        self.assertEqual(calculate_sha256(p), hashlib.sha256(b"abc").hexdigest())

    def test_same_file_match_modified_mismatch(self):
        a, b = self.dir / "a.bin", self.dir / "b.bin"
        data = os.urandom(300_000)
        a.write_bytes(data)
        b.write_bytes(data)
        self.assertEqual(compare_checksums(calculate_sha256(a), calculate_sha256(b)), MATCH)
        mod = bytearray(data)
        mod[1234] ^= 0x01
        b.write_bytes(mod)
        self.assertEqual(compare_checksums(calculate_sha256(a), calculate_sha256(b)), MISMATCH)

    def test_chunk_size_does_not_change_hash(self):
        p = self.dir / "x.bin"
        p.write_bytes(os.urandom(777_777))
        hashes = {calculate_sha256(p, c) for c in SUPPORTED_CHUNK_SIZES}
        self.assertEqual(len(hashes), 1)

    def test_bad_chunk_size(self):
        p = self.dir / "x.bin"
        p.write_bytes(b"1")
        for bad in (0, -1, 1.5, "64"):
            with self.assertRaises(ValueError):
                calculate_sha256(p, bad)


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_transfer(self, src, chunk):
        a, b = socket.socketpair()
        a.settimeout(10)
        b.settimeout(10)
        size = src.stat().st_size
        out = {}

        def receiver():
            conn = Connection(b)
            h = conn.receive_header()
            dest = self.dir / ("recv_" + h["filename"])
            digest = receive_file_data(conn, dest, h["file_size"], chunk)
            out.update(dest=dest, result=compare_checksums(h["sha256"], digest))

        t = threading.Thread(target=receiver)
        t.start()
        Connection(a).send_header({"command": "UPLOAD", "filename": src.name, "file_size": size,
                                   "sha256": calculate_sha256(src, chunk)})
        sent = send_file_data(a, src, chunk)
        t.join(15)
        a.close()
        b.close()
        self.assertEqual(sent, size)
        return out

    def test_file_types_and_all_chunk_sizes(self):
        files = {
            "a.txt": ("Xin chào mạng máy tính\n" * 4000).encode("utf-8"),
            "b.png": b"\x89PNG\r\n\x1a\n" + os.urandom(150_000),
            "c.jpg": b"\xff\xd8\xff\xe0" + os.urandom(90_000) + b"\xff\xd9",
            "d.pdf": b"%PDF-1.4\n" + os.urandom(80_000) + b"\n%%EOF",
            "e.bin": os.urandom(1_000_003),
            "f.bin": b"",
        }
        for name, data in files.items():
            src = self.dir / name
            src.write_bytes(data)
            for chunk in SUPPORTED_CHUNK_SIZES:
                with self.subTest(file=name, chunk=chunk):
                    out = self.run_transfer(src, chunk)
                    self.assertEqual(out["result"], MATCH)
                    self.assertEqual(out["dest"].read_bytes(), data)

    def test_corrupted_data_is_mismatch(self):
        src = self.dir / "s.bin"
        data = os.urandom(50_000)
        src.write_bytes(data)
        a, b = socket.socketpair()
        a.settimeout(10)
        b.settimeout(10)
        out = {}

        def receiver():
            conn = Connection(b)
            h = conn.receive_header()
            out["digest"] = receive_file_data(conn, self.dir / "r.bin", h["file_size"], 4096)
            out["expected"] = h["sha256"]

        t = threading.Thread(target=receiver)
        t.start()
        Connection(a).send_header({"command": "UPLOAD", "filename": "s.bin", "file_size": len(data),
                                   "sha256": calculate_sha256(src)})
        a.sendall(bytes([data[0] ^ 0xFF]) + data[1:])
        t.join(15)
        a.close()
        b.close()
        self.assertEqual(compare_checksums(out["expected"], out["digest"]), MISMATCH)

    def test_connection_closed_mid_transfer(self):
        a, b = socket.socketpair()
        b.settimeout(5)
        a.sendall(b"only-10-by")
        a.close()
        with self.assertRaises(PeerDisconnected):
            receive_file_data(Connection(b), self.dir / "r.bin", 1000, 64)
        b.close()


if __name__ == "__main__":
    unittest.main()
