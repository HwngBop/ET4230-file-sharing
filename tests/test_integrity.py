"""New Sprint 1 checksum/integration regression tests; no external packages required."""
import hashlib
import logging
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common.protocol import Connection, MAX_HEADER_BYTES, ProtocolError, encode_header
from server.config import ServerConfig
from server.server import FileServer


class IntegrityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.server = FileServer(ServerConfig(
            host="127.0.0.1", port=0, storage_dir=root / "storage",
            log_file=root / "server.log", client_timeout=2.0,
        ), logging.getLogger("test_integrity"))
        self.server.start()
        self.errors = []
        def run():
            try:
                self.server.serve_forever()
            except BaseException as exc:
                self.errors.append(exc)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.close()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.errors, [])
        self.temp.cleanup()

    def connected(self):
        sock = socket.create_connection(self.server.address, timeout=2)
        sock.settimeout(2)
        return sock, Connection(sock)

    def test_binary_roundtrip_and_legacy_without_sha(self):
        data = bytes(range(256)) * 1024 + b'\x00\n\xff'
        expected = hashlib.sha256(data).hexdigest()
        sock, conn = self.connected()
        with sock:
            conn.send_header({"command":"UPLOAD", "filename":"roundtrip.bin", "file_size":len(data), "sha256":expected})
            self.assertEqual(conn.receive_header()["status"], "READY")
            sock.sendall(data)
            confirmation = conn.receive_header()
            self.assertEqual(confirmation["status"], "SUCCESS")
            self.assertEqual(confirmation["sha256"], expected)
            conn.send_header({"command":"DOWNLOAD", "filename":"roundtrip.bin"})
            header = conn.receive_header()
            self.assertEqual(header["status"], "OK")
            received = bytearray()
            while len(received) < len(data):
                received.extend(conn.receive_chunk(min(8192, len(data)-len(received))))
            end = conn.receive_header()
            self.assertEqual(end["status"], "SUCCESS")
            self.assertEqual(end["sha256"], expected)
            self.assertEqual(received, data)
            conn.send_header({"command":"QUIT"})
            self.assertEqual(conn.receive_header()["status"], "OK")

        sock, conn = self.connected()
        with sock:
            conn.send_header({"command":"UPLOAD","filename":"old-client.txt","file_size":3})
            self.assertEqual(conn.receive_header()["status"], "READY")
            sock.sendall(b"abc")
            result = conn.receive_header()
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["sha256"], hashlib.sha256(b"abc").hexdigest())
            conn.send_header({"command":"QUIT"})
            conn.receive_header()

    def test_sha_mismatch_does_not_overwrite_old_file(self):
        old_data=b"existing data"
        self.server.storage.path_for("sample.bin").write_bytes(old_data)
        sock, conn = self.connected()
        with sock:
            conn.send_header({"command":"UPLOAD", "filename":"sample.bin", "file_size":4,
                              "sha256":hashlib.sha256(b"good").hexdigest()})
            self.assertEqual(conn.receive_header()["status"], "READY")
            sock.sendall(b"evil")
            result=conn.receive_header()
            self.assertEqual((result["status"],result["code"]),("ERROR","CHECKSUM_MISMATCH"))
            self.assertEqual(self.server.storage.path_for("sample.bin").read_bytes(), old_data)
            conn.send_header({"command":"LIST"})
            self.assertEqual(conn.receive_header()["status"],"OK")
            conn.send_header({"command":"QUIT"})
            conn.receive_header()
        self.assertEqual(list(self.server.storage.staging.iterdir()), [])

    def test_invalid_checksum_before_ready(self):
        sock, conn = self.connected()
        with sock:
            conn.send_header({"command":"UPLOAD", "filename":"bad.bin", "file_size":4, "sha256":"garbage"})
            result=conn.receive_header()
            self.assertEqual((result["status"],result["code"]),("ERROR","INVALID_CHECKSUM"))
            conn.send_header({"command":"QUIT"})
            conn.receive_header()

    def test_header_bounds_and_chunk_argument(self):
        with self.assertRaises(ProtocolError):
            encode_header({"data":"x"*(MAX_HEADER_BYTES+10)})
        sock,conn=self.connected()
        with sock:
            with self.assertRaises(ValueError):
                conn.receive_chunk(0)
            conn.send_header({"command":"QUIT"})
            self.assertEqual(conn.receive_header()["status"],"OK")


if __name__ == "__main__":
    unittest.main()
