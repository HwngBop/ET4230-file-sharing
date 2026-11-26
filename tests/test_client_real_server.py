"""S2-FIX-03: Client Reliability với FileServer + FileStorage THẬT (không dùng FakeServer).

TC01  SERVER_BUSY khi vượt max_clients (fatal), rồi reconnect thủ công
TC02  FILE_BUSY (recoverable): không gửi payload, LIST được, retry thành công
      (+ DOWNLOAD gặp FILE_BUSY: không tạo .part, giữ nguyên file cũ)
TC03  Upload bị ngắt giữa payload: FAILED, Server không công bố file dở, khóa được nhả
TC04  Download bị ngắt giữa chừng: .part bị xóa, file hoàn chỉnh cũ còn nguyên
TC05  Reconnect sau lỗi fatal (dùng lại chính FileClient đó)
Cộng một ca hồi quy Sprint 1: connect/upload/list/download/quit + FILE_NOT_FOUND.

Việc ngắt kết nối giữa chừng làm bằng một TCP proxy nhỏ nằm giữa Client và Server
thật, nên Server vẫn là mã thật, chỉ có đường truyền bị cắt.
"""
import contextlib
import csv
import hashlib
import io
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from client.client import FileClient, ServerError, TransferInterrupted  # noqa: E402
from common.protocol import Connection  # noqa: E402
from server.server import FileServer  # noqa: E402

MiB = 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


class CuttingProxy:
    """Chuyển tiếp đúng một kết nối; cắt đứt sau `cut_after` byte theo hướng chỉ định.

    direction = "c2s": đếm byte Client -> Server (làm đứt upload).
    direction = "s2c": đếm byte Server -> Client (làm đứt download).
    """

    def __init__(self, target, direction, cut_after):
        assert direction in ("c2s", "s2c")
        self.target, self.direction, self.cut_after = target, direction, cut_after
        self.cut = threading.Event()
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def address(self):
        return self.listener.getsockname()

    def _serve(self):
        try:
            client, _ = self.listener.accept()
        except OSError:
            return
        try:
            upstream = socket.create_connection(self.target, timeout=5)
        except OSError:
            client.close()
            return
        for sock in (client, upstream):
            sock.settimeout(10)
        pumps = [
            threading.Thread(target=self._pump, args=(
                client, upstream, self.cut_after if self.direction == "c2s" else None), daemon=True),
            threading.Thread(target=self._pump, args=(
                upstream, client, self.cut_after if self.direction == "s2c" else None), daemon=True),
        ]
        for pump in pumps:
            pump.start()
        for pump in pumps:
            pump.join()

    def _pump(self, source, destination, limit):
        sent = 0
        try:
            while True:
                data = source.recv(65536)
                if not data:
                    break
                if limit is not None and sent + len(data) >= limit:
                    data = data[:limit - sent]
                    if data:
                        destination.sendall(data)
                    self.cut.set()
                    break
                destination.sendall(data)
                sent += len(data)
        except OSError:
            pass
        finally:
            for sock in (source, destination):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

    def close(self):
        try:
            self.listener.close()
        except OSError:
            pass
        self.thread.join(timeout=5)


class RealServerTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.storage = self.root / "server-storage"
        self.server = None
        self.thread = None
        self.clients, self.socks, self.proxies = [], [], []
        self.last_output = ""

    def tearDown(self):
        for client in self.clients:
            client.drop()
        for sock in self.socks:
            with contextlib.suppress(OSError):
                sock.close()
        for proxy in self.proxies:
            proxy.close()
        if self.server is not None:
            self.server.close()
            self.thread.join(10)
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- hạ tầng
    def start_server(self, max_clients=8):
        config = SimpleNamespace(
            host="127.0.0.1", port=0, storage_dir=str(self.storage), log_file=None,
            chunk_size=65536, client_timeout=10, max_file_size=64 * MiB, max_clients=max_clients)
        self.server = FileServer(config)
        self.server.start()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def quiet(self, function, *args):
        """Chạy một thao tác của Client, giữ lại những gì nó in ra."""
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                return function(*args)
        finally:
            self.last_output = buffer.getvalue()

    def new_client(self, name, address=None):
        client = FileClient(csv_path=self.root / f"{name}.csv", auto_environment=False,
                            socket_timeout=5, download_dir=self.root / f"dl-{name}")
        self.clients.append(client)
        self.quiet(client.connect, *(address or self.server.address))
        return client

    def proxy(self, direction, cut_after):
        proxy = CuttingProxy(self.server.address, direction, cut_after)
        self.proxies.append(proxy)
        return proxy

    def make_file(self, name, size, folder="local"):
        path = self.root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = os.urandom(size)
        path.write_bytes(data)
        return path, data

    def rows(self, client):
        with client.csv_path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    def stored_files(self):
        """Mọi file thật sự nằm trong thư mục Storage (kể cả file tạm), không phụ thuộc tên thư mục staging."""
        if not self.storage.exists():
            return []
        return sorted(p.relative_to(self.storage).as_posix() for p in self.storage.rglob("*") if p.is_file())

    def wait_until(self, predicate, message, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail(message)

    def raw_upload_start(self, name, data):
        """'Client A' bằng socket thô: gửi UPLOAD, nhận READY rồi dừng, tức đang GIỮ khóa file."""
        sock = socket.create_connection(self.server.address, timeout=5)
        self.socks.append(sock)
        conn = Connection(sock)
        conn.send_header({"command": "UPLOAD", "filename": name, "file_size": len(data), "sha256": sha(data)})
        self.assertEqual(conn.receive_header()["status"], "READY")
        return sock, conn


class TC01_ServerBusy(RealServerTestCase):
    def test_server_busy_is_fatal_then_manual_reconnect(self):
        self.start_server(max_clients=2)
        c1, c2 = self.new_client("c1"), self.new_client("c2")
        self.quiet(c1.list_files)
        self.quiet(c2.list_files)
        self.wait_until(lambda: self.server.active_client_count == 2, "Server chưa ghi nhận đủ 2 client")

        c3 = self.new_client("c3")                    # TCP vẫn thành công: Client không chờ greeting
        self.assertTrue(c3.connected)
        with self.assertRaises(ServerError) as ctx:
            self.quiet(c3.list_files)                 # SERVER_BUSY đến trước command
        self.assertEqual(ctx.exception.code, "SERVER_BUSY")
        self.assertFalse(ctx.exception.recoverable)
        self.assertFalse(c3.connected)                # fatal: Client tự đóng socket

        path, _ = self.make_file("busy.bin", 200_000)
        c4 = self.new_client("c4")
        with self.assertRaises(ServerError) as ctx:
            self.quiet(c4.upload, str(path))          # upload gặp SERVER_BUSY: không có payload nào được công bố
        self.assertEqual(ctx.exception.code, "SERVER_BUSY")
        self.assertNotIn("SHA-256 MATCH", self.last_output)
        self.assertEqual(self.stored_files(), [])
        row, = self.rows(c4)
        self.assertEqual((row["status"], row["throughput_mbps"]), ("FAILED", ""))
        self.assertTrue(row["error_message"].startswith("Server error SERVER_BUSY"), row["error_message"])

        # TC05 (một phần): có chỗ trống thì reconnect thủ công bằng chính FileClient đó
        self.quiet(c1.quit)
        self.wait_until(lambda: self.server.active_client_count < 2, "Server không nhả slot sau QUIT")
        self.quiet(c3.connect, *self.server.address)
        self.quiet(c3.list_files)
        self.assertTrue(c3.connected)


class TC02_FileBusy(RealServerTestCase):
    def test_upload_file_busy_is_recoverable_then_list_and_retry(self):
        self.start_server()
        data_a = os.urandom(50_000)
        sock_a, conn_a = self.raw_upload_start("shared.bin", data_a)   # A giữ khóa "shared.bin"

        b = self.new_client("b")
        path_b, data_b = self.make_file("shared.bin", 120_000, folder="b")
        with self.assertRaises(ServerError) as ctx:
            self.quiet(b.upload, str(path_b))
        self.assertEqual(ctx.exception.code, "FILE_BUSY")
        self.assertTrue(ctx.exception.recoverable)
        self.assertTrue(b.connected)                                   # recoverable: giữ kết nối
        self.assertNotIn("SHA-256 MATCH", self.last_output)
        self.quiet(b.list_files)                                       # luồng sạch => không có payload nào lọt ra sau header

        sock_a.sendall(data_a)                                         # A hoàn tất, khóa được nhả
        self.assertEqual(conn_a.receive_header()["status"], "SUCCESS")

        self.quiet(b.upload, str(path_b))                              # retry trên CÙNG kết nối
        self.assertIn("SHA-256 MATCH", self.last_output)
        self.assertEqual((self.storage / "shared.bin").read_bytes(), data_b)
        statuses = [row["status"] for row in self.rows(b)]
        self.assertEqual(statuses, ["FAILED", "SUCCESS"])
        failed = self.rows(b)[0]
        self.assertEqual(failed["throughput_mbps"], "")
        self.assertTrue(failed["error_message"].startswith("Server error FILE_BUSY"))

    def test_download_file_busy_creates_no_part_and_keeps_old_download(self):
        self.start_server()
        old = os.urandom(80_000)
        (self.storage).mkdir(parents=True, exist_ok=True)
        (self.storage / "shared.bin").write_bytes(old)
        b = self.new_client("b")
        self.quiet(b.download, "shared.bin")
        target = b.download_dir / "shared.bin"
        self.assertEqual(target.read_bytes(), old)

        sock_a, conn_a = self.raw_upload_start("shared.bin", b"N" * 1000)   # A giữ khóa
        with self.assertRaises(ServerError) as ctx:
            self.quiet(b.download, "shared.bin")
        self.assertEqual(ctx.exception.code, "FILE_BUSY")
        self.assertTrue(b.connected)
        self.assertEqual(sorted(p.name for p in b.download_dir.iterdir()), ["shared.bin"])  # không có .part
        self.assertEqual(target.read_bytes(), old)                                           # file cũ còn nguyên
        self.assertNotIn("SHA-256 MATCH", self.last_output)

        sock_a.sendall(b"N" * 1000)
        self.assertEqual(conn_a.receive_header()["status"], "SUCCESS")
        self.quiet(b.download, "shared.bin")                                                 # retry thành công
        self.assertEqual(target.read_bytes(), b"N" * 1000)


class TC03_UploadInterrupted(RealServerTestCase):
    def test_upload_cut_mid_payload_fails_cleanly_and_client_can_reconnect(self):
        self.start_server()
        path, data = self.make_file("big.bin", 3 * MiB)
        proxy = self.proxy("c2s", 1 * MiB)
        client = self.new_client("up", address=proxy.address)

        with self.assertRaises(TransferInterrupted) as ctx:
            self.quiet(client.upload, str(path))
        self.assertTrue(proxy.cut.is_set(), "proxy chưa cắt: test không đo đúng tình huống")
        self.assertNotIn("SHA-256 MATCH", self.last_output)
        self.assertFalse(client.connected)
        self.assertIn("CONNECTION_OR_IO_ERROR", str(ctx.exception))
        row, = self.rows(client)
        self.assertEqual((row["status"], row["throughput_mbps"], row["checksum_match"]), ("FAILED", "", ""))
        self.assertTrue(row["error_message"].startswith("CONNECTION_OR_IO_ERROR"), row["error_message"])

        # Server không được công bố file dở và không để lại file tạm
        self.wait_until(lambda: self.stored_files() == [],
                        f"Server còn file sau khi upload bị ngắt: {self.stored_files()}")

        # TC05: reconnect thủ công; khóa file đã được nhả nên upload cùng tên thành công
        self.quiet(client.connect, *self.server.address)
        self.quiet(client.upload, str(path))
        self.assertIn("SHA-256 MATCH", self.last_output)
        self.assertEqual((self.storage / "big.bin").read_bytes(), data)
        self.assertEqual([r["status"] for r in self.rows(client)], ["FAILED", "SUCCESS"])


class TC04_DownloadInterrupted(RealServerTestCase):
    def test_download_cut_mid_payload_removes_part_and_keeps_old_complete_file(self):
        self.start_server()
        self.storage.mkdir(parents=True, exist_ok=True)
        data = os.urandom(3 * MiB)
        (self.storage / "big.bin").write_bytes(data)

        client = self.new_client("down")                       # lần 1 trực tiếp: có file hoàn chỉnh
        self.quiet(client.download, "big.bin")
        target = client.download_dir / "big.bin"
        self.assertEqual(sha(target.read_bytes()), sha(data))
        self.quiet(client.quit)

        proxy = self.proxy("s2c", 1 * MiB)                      # lần 2 qua proxy: bị cắt ở 1 MiB
        self.quiet(client.connect, *proxy.address)
        with self.assertRaises(TransferInterrupted) as ctx:
            self.quiet(client.download, "big.bin")
        self.assertTrue(proxy.cut.is_set(), "proxy chưa cắt: test không đo đúng tình huống")
        self.assertNotIn("SHA-256 MATCH", self.last_output)
        self.assertFalse(client.connected)
        self.assertIn("CONNECTION_OR_IO_ERROR", str(ctx.exception))
        self.assertEqual(sorted(p.name for p in client.download_dir.iterdir()), ["big.bin"])  # .part đã bị xóa
        self.assertEqual(sha(target.read_bytes()), sha(data))                                 # file cũ nguyên vẹn
        self.assertEqual((self.storage / "big.bin").read_bytes(), data)                       # Storage không bị ảnh hưởng

        rows = self.rows(client)
        self.assertEqual([r["status"] for r in rows], ["SUCCESS", "FAILED"])
        self.assertEqual((rows[1]["throughput_mbps"], rows[1]["checksum_match"]), ("", ""))
        self.assertTrue(rows[1]["error_message"].startswith("CONNECTION_OR_IO_ERROR"))

        # TC05: reconnect thủ công, khóa file đã nhả nên tải lại bình thường
        self.quiet(client.connect, *self.server.address)
        self.quiet(client.download, "big.bin")
        self.assertIn("SHA-256 MATCH", self.last_output)
        self.assertEqual(sha(target.read_bytes()), sha(data))


class Sprint1Regression(RealServerTestCase):
    def test_connect_upload_list_download_quit_and_file_not_found(self):
        self.start_server()
        path, data = self.make_file("roundtrip.bin", 1 * MiB + 17)
        client = self.new_client("reg")

        self.quiet(client.upload, str(path))
        self.assertIn("SHA-256 MATCH", self.last_output)
        self.quiet(client.list_files)
        self.assertIn("roundtrip.bin", self.last_output)
        self.quiet(client.download, "roundtrip.bin")
        self.assertIn("SHA-256 MATCH", self.last_output)
        self.assertEqual((client.download_dir / "roundtrip.bin").read_bytes(), data)

        with self.assertRaises(ServerError) as ctx:                 # lỗi recoverable: phiên vẫn mở
            self.quiet(client.download, "khong-co.bin")
        self.assertEqual(ctx.exception.code, "FILE_NOT_FOUND")
        self.assertTrue(client.connected)
        self.quiet(client.list_files)

        rows = self.rows(client)
        self.assertEqual([r["status"] for r in rows], ["SUCCESS", "SUCCESS", "FAILED"])
        for row in rows[:2]:
            self.assertEqual(row["checksum_match"], "true")
            self.assertNotEqual(row["throughput_mbps"], "")
        self.assertEqual(rows[2]["throughput_mbps"], "")

        self.quiet(client.quit)
        self.assertIn("Disconnected from server", self.last_output)
        self.assertFalse(client.connected)


if __name__ == "__main__":
    unittest.main()
