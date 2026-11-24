"""Concurrency and resource-management tests for the multi-client TCP server (CN21-10)."""

import hashlib
import io
import json
import logging
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.protocol import Connection, encode_header
from common.transfer import MATCH, compare_checksums
from server.config import ServerConfig, load_config
from server.logging_config import EventFormatter
from server.server import FileServer


class ConcurrentTestClient:
    def __init__(self, address, timeout=5.0):
        self.socket = socket.create_connection(address, timeout=timeout)
        self.socket.settimeout(timeout)
        self.connection = Connection(self.socket)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        try:
            self.socket.close()
        except OSError:
            pass

    def send(self, command, **values):
        self.connection.send_header({"command": command, **values})

    def receive(self):
        return self.connection.receive_header()

    def upload(self, filename, data, *, send_sha256=True, chunk_size=16384):
        expected_sha256 = hashlib.sha256(data).hexdigest()
        header = {"command": "UPLOAD", "filename": filename, "file_size": len(data)}
        if send_sha256:
            header["sha256"] = expected_sha256
        self.connection.send_header(header)
        ready = self.receive()
        if ready is None or ready.get("status") != "READY":
            raise AssertionError(f"Expected READY, got {ready}")
        offset = 0
        while offset < len(data):
            piece = data[offset : offset + chunk_size]
            self.socket.sendall(piece)
            offset += len(piece)
        result = self.receive()
        return result, expected_sha256

    def download(self, filename):
        self.send("DOWNLOAD", filename=filename)
        header = self.receive()
        if header is None or header.get("status") != "OK":
            raise AssertionError(f"Expected OK, got {header}")
        file_size = header["file_size"]
        received = bytearray()
        while len(received) < file_size:
            chunk = self.connection.receive_chunk(min(16384, file_size - len(received)))
            received.extend(chunk)
        completion = self.receive()
        return bytes(received), completion


class ConcurrentServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.log_lock = threading.Lock()
        self.log_output = io.StringIO()
        self.logger = logging.Logger(self.id())

        class ThreadSafeStreamHandler(logging.StreamHandler):
            def __init__(self, stream, lock):
                super().__init__(stream)
                self._write_lock = lock

            def emit(self, record):
                with self._write_lock:
                    super().emit(record)

        handler = ThreadSafeStreamHandler(self.log_output, self.log_lock)
        handler.setFormatter(EventFormatter())
        self.logger.addHandler(handler)
        self.server = None
        self.thread = None
        self.server_errors = []

    def start_server(self, *, max_clients=10, client_timeout=2.0, chunk_size=4096):
        self.server = FileServer(
            ServerConfig(
                host="127.0.0.1",
                port=0,
                storage_dir=self.root / "storage",
                log_file=self.root / "server.log",
                chunk_size=chunk_size,
                max_file_size=10 * 1024 * 1024,
                client_timeout=client_timeout,
                max_clients=max_clients,
            ),
            self.logger,
        )
        self.server.start()
        self.address = self.server.address

        def run_server():
            try:
                self.server.serve_forever()
            except BaseException as exc:
                self.server_errors.append(exc)

        self.thread = threading.Thread(target=run_server, name="server-accept-thread", daemon=True)
        self.thread.start()

    def tearDown(self):
        if self.server is not None:
            self.server.close()
        if self.thread is not None:
            self.thread.join(timeout=5)
        try:
            if self.thread is not None:
                self.assertFalse(self.thread.is_alive(), "Server accept thread did not stop")
            self.assertEqual(self.server_errors, [])
        finally:
            self.temporary.cleanup()

    def log_records(self):
        with self.log_lock:
            lines = self.log_output.getvalue().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def wait_for_active_clients(self, expected_count, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.active_client_count == expected_count:
                return
            time.sleep(0.01)
        self.assertEqual(self.server.active_client_count, expected_count)

    def test_tc01_five_clients_parallel_commands(self):
        """TC01: 5 Client kết nối và thực hiện các lệnh song song."""
        self.start_server(max_clients=10, client_timeout=5.0)
        num_clients = 5
        ready_barrier = threading.Barrier(num_clients, timeout=5.0)
        command_barrier = threading.Barrier(num_clients, timeout=5.0)
        errors = []
        active_at_barrier = []

        def worker(index):
            try:
                payload = f"parallel-client-{index}-".encode("utf-8") * 1024
                expected_sha = hashlib.sha256(payload).hexdigest()
                filename = f"tc01_client_{index}.bin"
                with ConcurrentTestClient(self.address) as client:
                    client.send(
                        "UPLOAD",
                        filename=filename,
                        file_size=len(payload),
                        sha256=expected_sha,
                    )
                    ready = client.receive()
                    self.assertEqual(ready["status"], "READY")

                    # All 5 workers must have accepted and dispatched READY concurrently
                    # before any client transmits payload bytes.
                    ready_barrier.wait()
                    active_at_barrier.append(self.server.active_client_count)

                    client.socket.sendall(payload)
                    result = client.receive()
                    self.assertEqual(result["status"], "SUCCESS")
                    self.assertEqual(result["sha256"], expected_sha)

                    command_barrier.wait()
                    client.send("LIST")
                    listing = client.receive()
                    self.assertEqual(listing["status"], "OK")
                    for idx in range(num_clients):
                        self.assertIn(f"tc01_client_{idx}.bin", listing["files"])

                    downloaded, dl_result = client.download(filename)
                    self.assertEqual(dl_result["status"], "SUCCESS")
                    self.assertEqual(dl_result["sha256"], expected_sha)
                    self.assertEqual(downloaded, payload)

                    client.send("QUIT")
                    quit_resp = client.receive()
                    self.assertEqual(quit_resp, {"status": "OK", "command": "QUIT"})
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_clients)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive(), "Client worker thread hung")

        self.assertEqual(errors, [])
        self.assertEqual(active_at_barrier, [num_clients] * num_clients)

    def test_tc02_idle_and_timeout_client_does_not_block_other_clients(self):
        """TC02: Client A đang idle, Client B vẫn thực hiện LIST và UPLOAD thành công."""
        self.start_server(max_clients=5, client_timeout=0.6)
        with ConcurrentTestClient(self.address, timeout=3.0) as client_a:
            self.wait_for_active_clients(1)

            # While Client A is completely idle, Client B connects and performs LIST + UPLOAD.
            with ConcurrentTestClient(self.address, timeout=3.0) as client_b:
                self.wait_for_active_clients(2)
                client_b.send("LIST")
                self.assertEqual(client_b.receive(), {"status": "OK", "command": "LIST", "files": []})

                data = b"client-b-upload-while-a-is-idle" * 200
                result, expected_sha = client_b.upload("from_b.bin", data)
                self.assertEqual(result["status"], "SUCCESS")
                self.assertEqual(result["sha256"], expected_sha)

                client_b.send("LIST")
                self.assertEqual(client_b.receive()["files"], ["from_b.bin"])

                # Wait for Client A to hit inactivity timeout; Client B must stay unaffected.
                timeout_response = client_a.receive()
                self.assertEqual(timeout_response["status"], "ERROR")
                self.assertEqual(timeout_response["code"], "TIMEOUT")

                # Client B is still connected and can continue issuing commands.
                downloaded, dl_result = client_b.download("from_b.bin")
                self.assertEqual(dl_result["status"], "SUCCESS")
                self.assertEqual(downloaded, data)
                client_b.send("QUIT")
                self.assertEqual(client_b.receive(), {"status": "OK", "command": "QUIT"})

    def test_tc03_five_clients_upload_distinct_files_sha256_match(self):
        """TC03: 5 Client upload các file khác tên, tất cả SHA-256 MATCH."""
        self.start_server(max_clients=10, client_timeout=5.0, chunk_size=4096)
        num_clients = 5
        barrier = threading.Barrier(num_clients, timeout=5.0)
        results = {}
        errors = []

        def upload_worker(index):
            try:
                filename = f"distinct_{index}.bin"
                data = bytes(((index * 37 + b) % 256 for b in range(131072 + index * 113)))
                with ConcurrentTestClient(self.address) as client:
                    barrier.wait()
                    response, expected_sha = client.upload(filename, data, chunk_size=3000)
                    self.assertEqual(response["status"], "SUCCESS")
                    self.assertEqual(compare_checksums(expected_sha, response["sha256"]), MATCH)
                    results[filename] = (data, expected_sha, response["sha256"])
                    client.send("QUIT")
                    self.assertEqual(client.receive()["status"], "OK")
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=upload_worker, args=(i,)) for i in range(num_clients)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())

        self.assertEqual(errors, [])
        self.assertEqual(len(results), num_clients)
        for filename, (data, expected_sha, actual_sha) in results.items():
            stored_path = self.root / "storage" / filename
            self.assertTrue(stored_path.exists())
            stored_bytes = stored_path.read_bytes()
            self.assertEqual(stored_bytes, data)
            disk_sha = hashlib.sha256(stored_bytes).hexdigest()
            self.assertEqual(compare_checksums(expected_sha, disk_sha), MATCH)
            self.assertEqual(compare_checksums(actual_sha, disk_sha), MATCH)

    def test_tc04_abrupt_client_disconnect_does_not_crash_server(self):
        """TC04: Client bất ngờ ngắt kết nối, Server không crash."""
        self.start_server(max_clients=10, client_timeout=3.0)
        barrier = threading.Barrier(4, timeout=5.0)
        errors = []

        def abrupt_empty_disconnect():
            try:
                with socket.create_connection(self.address, timeout=3.0):
                    barrier.wait()
            except BaseException as exc:
                errors.append(exc)

        def abrupt_partial_header():
            try:
                with socket.create_connection(self.address, timeout=3.0) as sock:
                    barrier.wait()
                    sock.sendall(b'{"command":"UPLOAD","filename":"broken')
            except BaseException as exc:
                errors.append(exc)

        def abrupt_mid_upload():
            try:
                with ConcurrentTestClient(self.address) as client:
                    barrier.wait()
                    client.send("UPLOAD", filename="partial_drop.bin", file_size=65536)
                    ready = client.receive()
                    self.assertEqual(ready["status"], "READY")
                    client.socket.sendall(b"incomplete-payload-bytes")
            except BaseException as exc:
                errors.append(exc)

        def healthy_client():
            try:
                with ConcurrentTestClient(self.address) as client:
                    barrier.wait()
                    payload = b"healthy-client-data\n" * 512
                    result, expected_sha = client.upload("healthy.bin", payload)
                    self.assertEqual(result["status"], "SUCCESS")
                    self.assertEqual(result["sha256"], expected_sha)
                    downloaded, dl_result = client.download("healthy.bin")
                    self.assertEqual(dl_result["status"], "SUCCESS")
                    self.assertEqual(downloaded, payload)
                    client.send("QUIT")
                    self.assertEqual(client.receive()["status"], "OK")
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=abrupt_empty_disconnect),
            threading.Thread(target=abrupt_partial_header),
            threading.Thread(target=abrupt_mid_upload),
            threading.Thread(target=healthy_client),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())

        self.assertEqual(errors, [])
        self.wait_for_active_clients(0)
        self.assertFalse((self.root / "storage" / "partial_drop.bin").exists())
        self.assertEqual(list(self.server.storage.staging.iterdir()), [])

        # Confirm server still accepts new connections normally.
        with ConcurrentTestClient(self.address) as verify_client:
            verify_client.send("LIST")
            self.assertEqual(verify_client.receive()["files"], ["healthy.bin"])
            verify_client.send("QUIT")
            self.assertEqual(verify_client.receive()["status"], "OK")

    def test_tc05_over_capacity_rejected_with_server_busy(self):
        """TC05: Kết nối vượt max_clients nhận xử lý theo SERVER_BUSY."""
        max_clients = 5
        self.start_server(max_clients=max_clients, client_timeout=5.0)
        active_clients = []
        try:
            for i in range(max_clients):
                client = ConcurrentTestClient(self.address)
                active_clients.append(client)
                client.send("LIST")
                self.assertEqual(client.receive()["status"], "OK")

            self.wait_for_active_clients(max_clients)
            self.assertEqual(len(self.server.active_workers), max_clients)

            # 6th client connects and reads immediately -> SERVER_BUSY
            with ConcurrentTestClient(self.address, timeout=3.0) as extra_1:
                response = extra_1.receive()
                self.assertEqual(response["status"], "ERROR")
                self.assertEqual(response["code"], "SERVER_BUSY")
                self.assertIsNone(extra_1.receive())

            # Another over-capacity client sends a command first, then reads -> SERVER_BUSY
            with ConcurrentTestClient(self.address, timeout=3.0) as extra_2:
                extra_2.send("LIST")
                response = extra_2.receive()
                self.assertEqual(response["status"], "ERROR")
                self.assertEqual(response["code"], "SERVER_BUSY")
                self.assertIsNone(extra_2.receive())

            # Active workers must never exceed max_clients.
            self.assertEqual(self.server.active_client_count, max_clients)
            self.assertEqual(len(self.server.active_workers), max_clients)

            # Release one slot and verify a new client is accepted normally.
            released = active_clients.pop(0)
            released.send("QUIT")
            self.assertEqual(released.receive()["status"], "OK")
            released.close()
            self.wait_for_active_clients(max_clients - 1)

            with ConcurrentTestClient(self.address, timeout=3.0) as admitted:
                admitted.send("LIST")
                self.assertEqual(admitted.receive()["status"], "OK")
                admitted.send("QUIT")
                self.assertEqual(admitted.receive()["status"], "OK")
        finally:
            for client in active_clients:
                client.close()

        busy_logs = [r for r in self.log_records() if r.get("status") == "SERVER_BUSY"]
        self.assertGreaterEqual(len(busy_logs), 2)
        for record in busy_logs:
            self.assertTrue(record["connection_id"])
            self.assertEqual(record["client_ip"], "127.0.0.1")

    def test_tc06_clean_shutdown_with_multiple_active_clients(self):
        """TC06: Server shutdown khi nhiều Client đang kết nối, không còn Worker hoặc Socket bị treo."""
        self.start_server(max_clients=10, client_timeout=10.0)
        clients = []
        try:
            # 3 idle clients after LIST, 2 clients mid-upload waiting after READY
            for i in range(3):
                client = ConcurrentTestClient(self.address, timeout=3.0)
                clients.append(client)
                client.send("LIST")
                self.assertEqual(client.receive()["status"], "OK")

            for i in range(2):
                client = ConcurrentTestClient(self.address, timeout=3.0)
                clients.append(client)
                client.send("UPLOAD", filename=f"inflight_{i}.bin", file_size=32768)
                self.assertEqual(client.receive()["status"], "READY")
                client.socket.sendall(b"partial-inflight-bytes")

            self.wait_for_active_clients(5)
            workers_before = list(self.server.active_workers)
            self.assertEqual(len(workers_before), 5)

            # Trigger server shutdown while all 5 clients are active.
            self.server.close()
            self.thread.join(timeout=5.0)

            self.assertFalse(self.thread.is_alive(), "Accept loop thread still alive after close()")
            self.assertIsNone(self.server.listener)
            self.assertEqual(self.server.active_client_count, 0)
            self.assertEqual(self.server.active_workers, [])
            for worker in workers_before:
                self.assertFalse(worker.is_alive(), f"Worker {worker.name} still alive after close()")
            self.assertEqual(list(self.server.storage.staging.iterdir()), [])
        finally:
            for client in clients:
                client.close()

    def test_logging_includes_distinct_connection_ids_and_transfer_fields(self):
        self.start_server(max_clients=5, client_timeout=3.0)
        with ConcurrentTestClient(self.address) as client_1, ConcurrentTestClient(self.address) as client_2:
            res_1, _ = client_1.upload("log_1.bin", b"123456")
            res_2, _ = client_2.upload("log_2.bin", b"abcdefgh")
            self.assertEqual(res_1["status"], "SUCCESS")
            self.assertEqual(res_2["status"], "SUCCESS")
            client_1.send("QUIT")
            client_2.send("QUIT")
            client_1.receive()
            client_2.receive()

        self.wait_for_active_clients(0)
        records = self.log_records()
        uploads = [r for r in records if r.get("command") == "UPLOAD" and r.get("status") == "SUCCESS"]
        self.assertEqual(len(uploads), 2)
        conn_ids = {r["connection_id"] for r in uploads}
        self.assertEqual(len(conn_ids), 2)
        for record in uploads:
            self.assertTrue(record["connection_id"].startswith("conn-"))
            self.assertEqual(record["client_ip"], "127.0.0.1")
            self.assertIsInstance(record["client_port"], int)
            self.assertIn(record["filename"], ("log_1.bin", "log_2.bin"))
            self.assertEqual(record["transferred_bytes"], record["file_size"])

    def test_max_clients_config_validation_and_cli_override(self):
        default_cfg = ServerConfig()
        self.assertEqual(default_cfg.max_clients, 10)

        loaded_default = load_config([])
        self.assertEqual(loaded_default.max_clients, 10)

        overridden = load_config(["--max-clients", "25"])
        self.assertEqual(overridden.max_clients, 25)

        for invalid in (0, -1, True, False, 1.5, "10", 70000):
            with self.subTest(max_clients=invalid), self.assertRaises(ValueError):
                ServerConfig(max_clients=invalid)

    def test_ac05_file_busy_on_concurrent_upload_and_recoverable_session(self):
        """AC05: Client A giữ READY cho upload same.bin, Client B nhận FILE_BUSY trước READY và session vẫn dùng tiếp được."""
        self.start_server(max_clients=5, client_timeout=3.0)
        data_a = b"client-a-payload-bytes"
        sha_a = hashlib.sha256(data_a).hexdigest()
        data_b = b"client-b-retry-payload-bytes"
        sha_b = hashlib.sha256(data_b).hexdigest()

        with ConcurrentTestClient(self.address) as client_a, ConcurrentTestClient(self.address) as client_b:
            client_a.send("UPLOAD", filename="same.bin", file_size=len(data_a), sha256=sha_a)
            self.assertEqual(client_a.receive()["status"], "READY")
            self.assertTrue(self.server.storage.locks.is_locked("same.bin"))

            # Client B tries to upload the same file while Client A holds the lock.
            client_b.send("UPLOAD", filename="same.bin", file_size=len(data_b), sha256=sha_b)
            busy_resp = client_b.receive()
            self.assertEqual((busy_resp["status"], busy_resp["code"]), ("ERROR", "FILE_BUSY"))

            # Client B's connection remains alive (recoverable) for LIST or other files.
            client_b.send("LIST")
            self.assertEqual(client_b.receive(), {"status": "OK", "command": "LIST", "files": []})

            # Client A finishes uploading and releases the lock.
            client_a.socket.sendall(data_a)
            self.assertEqual(client_a.receive()["status"], "SUCCESS")
            self.assertFalse(self.server.storage.locks.is_locked("same.bin"))

            # Client B retries uploading same.bin on the same socket and succeeds.
            result_b, _ = client_b.upload("same.bin", data_b)
            self.assertEqual(result_b["status"], "SUCCESS")
            self.assertEqual(result_b["sha256"], sha_b)
            self.assertEqual((self.root / "storage" / "same.bin").read_bytes(), data_b)

            client_a.send("QUIT")
            client_b.send("QUIT")
            client_a.receive()
            client_b.receive()
        self.assertEqual(self.server.storage.locks.locked_count(), 0)

    def test_ac06_file_busy_on_download_while_upload_active(self):
        """AC06: Client A đang upload same.bin, Client B download cùng tên nhận FILE_BUSY trước OK."""
        self.start_server(max_clients=5, client_timeout=3.0)
        (self.root / "storage" / "same.bin").write_bytes(b"initial-content")
        data_a = b"updated-content-from-a"
        sha_a = hashlib.sha256(data_a).hexdigest()

        with ConcurrentTestClient(self.address) as client_a, ConcurrentTestClient(self.address) as client_b:
            client_a.send("UPLOAD", filename="same.bin", file_size=len(data_a), sha256=sha_a)
            self.assertEqual(client_a.receive()["status"], "READY")

            client_b.send("DOWNLOAD", filename="same.bin")
            busy_resp = client_b.receive()
            self.assertEqual((busy_resp["status"], busy_resp["code"]), ("ERROR", "FILE_BUSY"))

            # Finish Client A's upload, then Client B can download the updated file on the same connection.
            client_a.socket.sendall(data_a)
            self.assertEqual(client_a.receive()["status"], "SUCCESS")

            downloaded, dl_result = client_b.download("same.bin")
            self.assertEqual(dl_result["status"], "SUCCESS")
            self.assertEqual(downloaded, data_a)

            client_a.send("QUIT")
            client_b.send("QUIT")
            client_a.receive()
            client_b.receive()
        self.assertEqual(self.server.storage.locks.locked_count(), 0)

    def test_ac08_file_lock_released_after_checksum_mismatch_and_disconnect(self):
        """AC08: Mismatch/partial upload xóa staging, giữ file đích cũ và giải phóng lock để retry thành công."""
        self.start_server(max_clients=5, client_timeout=3.0)
        target = self.root / "storage" / "guarded.bin"
        target.write_bytes(b"original-safe-bytes")

        with ConcurrentTestClient(self.address) as client_a:
            client_a.send("UPLOAD", filename="guarded.bin", file_size=4, sha256="0" * 64)
            self.assertEqual(client_a.receive()["status"], "READY")
            client_a.socket.sendall(b"data")
            mismatch = client_a.receive()
            self.assertEqual((mismatch["status"], mismatch["code"]), ("ERROR", "CHECKSUM_MISMATCH"))
            self.assertEqual(self.server.storage.locks.locked_count(), 0)

            # Lock must already be released; retry valid upload on the same connection.
            new_data = b"valid-replacement-bytes"
            res, expected_sha = client_a.upload("guarded.bin", new_data)
            self.assertEqual(res["status"], "SUCCESS")
            self.assertEqual(res["sha256"], expected_sha)
            self.assertEqual(target.read_bytes(), new_data)
            client_a.send("QUIT")
            client_a.receive()
        self.assertEqual(self.server.storage.locks.locked_count(), 0)


if __name__ == "__main__":
    unittest.main()
