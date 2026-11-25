"""Test FILE_BUSY chay that qua FileServer (CN21-12)."""

import hashlib
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from common.protocol import Connection
from server.server import FileServer


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FileBusyServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        config = SimpleNamespace(
            host="127.0.0.1", port=0, storage_dir=self.tmp, log_file=None,
            chunk_size=65536, client_timeout=10, max_file_size=10 * 1024 * 1024,
            max_clients=8,
        )
        self.server = FileServer(config)
        self.server.start()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.address = self.server.address
        self.socks = []

    def tearDown(self):
        for sock in self.socks:
            try:
                sock.close()
            except OSError:
                pass
        self.server.close()
        self.thread.join(10)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def connect(self):
        sock = socket.create_connection(self.address, timeout=5)
        self.socks.append(sock)
        return sock, Connection(sock)

    def start_upload(self, conn, name, data):
        conn.send_header({
            "command": "UPLOAD", "filename": name,
            "file_size": len(data), "sha256": sha(data),
        })
        return conn.receive_header()

    def finish_upload(self, sock, conn, data):
        sock.sendall(data)
        return conn.receive_header()

    def test_second_upload_same_file_gets_file_busy(self):
        sock_a, conn_a = self.connect()
        sock_b, conn_b = self.connect()
        data_a, data_b = b"A" * 100, b"B" * 200

        self.assertEqual(self.start_upload(conn_a, "f.bin", data_a)["status"], "READY")
        reply = self.start_upload(conn_b, "f.bin", data_b)
        self.assertEqual((reply["status"], reply["code"]), ("ERROR", "FILE_BUSY"))

        self.assertEqual(self.finish_upload(sock_a, conn_a, data_a)["status"], "SUCCESS")

        # Het ban sau khi A xong: B upload lai tren cung ket noi duoc.
        self.assertEqual(self.start_upload(conn_b, "f.bin", data_b)["status"], "READY")
        self.assertEqual(self.finish_upload(sock_b, conn_b, data_b)["status"], "SUCCESS")
        self.assertEqual((Path(self.tmp) / "f.bin").read_bytes(), data_b)

    def test_download_while_uploading_same_file_gets_file_busy(self):
        sock_a, conn_a = self.connect()
        sock_b, conn_b = self.connect()
        old, new = b"old", b"N" * 50

        self.assertEqual(self.start_upload(conn_a, "f.bin", old)["status"], "READY")
        self.assertEqual(self.finish_upload(sock_a, conn_a, old)["status"], "SUCCESS")

        self.assertEqual(self.start_upload(conn_a, "f.bin", new)["status"], "READY")
        conn_b.send_header({"command": "DOWNLOAD", "filename": "f.bin"})
        reply = conn_b.receive_header()
        self.assertEqual((reply["status"], reply["code"]), ("ERROR", "FILE_BUSY"))

        self.assertEqual(self.finish_upload(sock_a, conn_a, new)["status"], "SUCCESS")
        self.assertEqual((Path(self.tmp) / "f.bin").read_bytes(), new)

    def test_different_files_do_not_block(self):
        sock_a, conn_a = self.connect()
        sock_b, conn_b = self.connect()
        data_a, data_b = b"A" * 100, b"B" * 100

        self.assertEqual(self.start_upload(conn_a, "a.bin", data_a)["status"], "READY")
        # A van dang giu khoa a.bin, B upload b.bin van phai thanh cong.
        self.assertEqual(self.start_upload(conn_b, "b.bin", data_b)["status"], "READY")
        self.assertEqual(self.finish_upload(sock_b, conn_b, data_b)["status"], "SUCCESS")
        self.assertEqual(self.finish_upload(sock_a, conn_a, data_a)["status"], "SUCCESS")
        self.assertEqual((Path(self.tmp) / "a.bin").read_bytes(), data_a)
        self.assertEqual((Path(self.tmp) / "b.bin").read_bytes(), data_b)

    def test_lock_released_when_client_disconnects(self):
        sock_a, conn_a = self.connect()
        sock_b, conn_b = self.connect()
        data = b"Z" * 100

        self.assertEqual(self.start_upload(conn_a, "f.bin", data)["status"], "READY")
        sock_a.close()  # client A rot giua luc upload

        deadline = time.monotonic() + 5
        done = False
        while time.monotonic() < deadline:
            reply = self.start_upload(conn_b, "f.bin", data)
            if reply["status"] == "READY":
                self.assertEqual(self.finish_upload(sock_b, conn_b, data)["status"], "SUCCESS")
                done = True
                break
            self.assertEqual(reply["code"], "FILE_BUSY")
            time.sleep(0.05)
        self.assertTrue(done, "FILE_BUSY khong duoc nha sau khi client ngat ket noi")
        self.assertEqual((Path(self.tmp) / "f.bin").read_bytes(), data)
        self.assertEqual(list((Path(self.tmp) / ".uploads").glob("*.part")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)