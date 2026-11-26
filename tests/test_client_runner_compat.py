"""TC06 (S2-FIX-03): FileClient phải tiếp tục tương thích với concurrent runner.

scripts/run_concurrent.py kế thừa FileClient (WorkerClient), ghi đè read_response()
và measured_transfer(), rồi gọi FileClient(...) bằng một bộ keyword cố định. Các test
này khóa chặt "hợp đồng" đó: nếu ai đổi chữ ký hoặc luồng gọi hàm ở một phía thì
test đỏ ngay, thay vì đợi tới lúc chạy runner mới phát hiện.
"""
import ast
import contextlib
import csv
import hashlib
import inspect
import io
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from client.client import FileClient, ServerError  # noqa: E402
from common.csv_logger import CONCURRENT_FIELDS  # noqa: E402
from common.protocol import Connection  # noqa: E402
import run_concurrent  # noqa: E402

# Các tham số mà ticket S2-FIX-03 yêu cầu giữ nguyên.
REQUIRED_KWARGS = {"num_clients", "client_id", "session_id", "csv_fields", "socket_timeout"}


def runner_client_kwargs():
    """Đọc từ chính mã nguồn runner: những keyword nào được truyền vào client_factory(...)."""
    tree = ast.parse((ROOT / "scripts" / "run_concurrent.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "client_factory"):
            names.update(kw.arg for kw in node.keywords if kw.arg)
    return names


class ConstructorAndMethodContract(unittest.TestCase):
    def test_runner_still_passes_the_keywords_the_ticket_lists(self):
        names = runner_client_kwargs()
        self.assertTrue(names, "không tìm thấy lời gọi client_factory(...) trong run_scenario")
        self.assertTrue(REQUIRED_KWARGS <= names, f"runner thiếu keyword: {REQUIRED_KWARGS - names}")

    def test_file_client_accepts_every_keyword_the_runner_passes(self):
        params = inspect.signature(FileClient.__init__).parameters
        for name in runner_client_kwargs() - {"gate"}:  # gate chỉ dành cho WorkerClient
            self.assertIn(name, params, f"FileClient.__init__ không nhận '{name}' mà runner truyền vào")

    def test_worker_client_adds_only_gate(self):
        extra = set(inspect.signature(run_concurrent.WorkerClient.__init__).parameters) - {"self", "kwargs"}
        self.assertEqual(extra, {"gate"})

    def test_method_signatures_match_runner_calls(self):
        anything = object()
        inspect.signature(FileClient.connect).bind(anything, "127.0.0.1", 5000)  # client.connect(host, port)
        inspect.signature(FileClient.upload).bind(anything, "path")              # client.upload(str(target))
        inspect.signature(FileClient.download).bind(anything, "name")            # client.download(name)
        inspect.signature(FileClient.quit).bind(anything)                        # client.quit()
        inspect.signature(FileClient.read_response).bind(anything)               # hook ghi đè bởi runner
        inspect.signature(FileClient.measured_transfer).bind(anything, "upload", "name")  # hook ghi đè bởi runner


class RecordingGate:
    """Thay ReadyGate: ghi lại thời điểm Client gọi wait() so với phía Server."""

    def __init__(self, server):
        self.server = server
        self.calls = []

    def wait(self, client_id):
        self.calls.append((client_id, self.server.ready_sent, self.server.payload_bytes))

    def abort(self):
        pass


class ScriptedServer:
    """Một kết nối, chạy kịch bản handler(sock, conn, self)."""

    def __init__(self, handler):
        self.ready_sent = False
        self.payload_bytes = 0
        self.errors = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.handler = handler
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @property
    def address(self):
        return self.listener.getsockname()

    def _run(self):
        try:
            sock, _ = self.listener.accept()
        except OSError:
            return
        with sock:
            sock.settimeout(5)
            try:
                self.handler(sock, Connection(sock), self)
            except BaseException as exc:  # noqa: BLE001 - báo lại ở tearDown
                self.errors.append(exc)

    def close(self):
        self.listener.close()
        self.thread.join(timeout=5)


class RunnerHooksAgainstRealClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.server = None
        self.client = None

    def tearDown(self):
        if self.client:
            self.client.drop()
        if self.server:
            self.server.close()
            self.assertEqual(self.server.errors, [])
        self.tmp.cleanup()

    def start(self, handler):
        self.server = ScriptedServer(handler)
        self.gate = RecordingGate(self.server)
        self.client = run_concurrent.WorkerClient(
            gate=self.gate, csv_path=self.dir / "transfers.csv", environment_id="env-1",
            num_clients=5, client_id="client-03", session_id="session-xyz",
            csv_fields=CONCURRENT_FIELDS, socket_timeout=5,
            download_dir=self.dir / "downloads", auto_environment=False)
        with contextlib.redirect_stdout(io.StringIO()):
            self.client.connect(*self.server.address)
        return self.client

    def source(self, data=b"S" * 5000):
        path = self.dir / "src.bin"
        path.write_bytes(data)
        return path

    def rows(self):
        with (self.dir / "transfers.csv").open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, CONCURRENT_FIELDS)
            return list(reader)

    def call(self, function, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return function(*args)

    # ---- happy path: hook READY gate + CSV có client_id/session_id/num_clients
    def test_gate_hook_runs_after_ready_before_payload_and_csv_is_complete(self):
        data = b"S" * 5000

        def handler(sock, conn, srv):
            request = conn.receive_header()
            srv.ready_sent = True
            conn.send_header({"status": "READY", "command": "UPLOAD", "filename": request["filename"],
                              "file_size": request["file_size"]})
            remaining = request["file_size"]
            digest = hashlib.sha256()
            while remaining:
                chunk = conn.receive_chunk(min(remaining, 4096))
                srv.payload_bytes += len(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            conn.send_header({"status": "SUCCESS", "command": "UPLOAD", "filename": request["filename"],
                              "file_size": request["file_size"], "sha256": digest.hexdigest()})

        client = self.start(handler)
        self.call(client.upload, str(self.source(data)))

        self.assertEqual(self.gate.calls, [("client-03", True, 0)])  # sau READY, trước byte payload đầu tiên
        entry, = client.transfers
        self.assertEqual(entry["status"], "SUCCESS")
        self.assertIsNotNone(entry["transfer_start_s"])
        self.assertIsNotNone(entry["transfer_end_s"])
        row, = self.rows()
        self.assertEqual((row["status"], row["checksum_match"]), ("SUCCESS", "true"))
        self.assertNotEqual(row["throughput_mbps"], "")
        self.assertEqual((row["client_id"], row["session_id"], row["num_clients"], row["environment_id"]),
                         ("client-03", "session-xyz", "5", "env-1"))

    # ---- FILE_BUSY: recoverable, không chạm gate, không gửi payload, ghi FAILED
    def test_file_busy_is_recoverable_and_logged_failed(self):
        def handler(sock, conn, srv):
            conn.receive_header()
            conn.send_header({"status": "ERROR", "code": "FILE_BUSY", "message": "File is currently in use"})
            second = conn.receive_header()          # nếu payload lọt ra, dòng này sẽ lỗi INVALID_HEADER
            assert second == {"command": "LIST"}, second
            conn.send_header({"status": "OK", "command": "LIST", "files": []})

        client = self.start(handler)
        with self.assertRaises(ServerError) as ctx:
            self.call(client.upload, str(self.source()))
        self.assertEqual(ctx.exception.code, "FILE_BUSY")
        self.assertTrue(ctx.exception.recoverable)
        self.assertTrue(client.connected)
        self.assertEqual(self.gate.calls, [])        # gate chỉ chạy sau READY
        self.assertEqual(client.transfers[0]["status"], "FAILED")
        row, = self.rows()
        self.assertEqual((row["status"], row["throughput_mbps"], row["checksum_match"]), ("FAILED", "", ""))
        self.assertTrue(row["error_message"].startswith("Server error FILE_BUSY"))
        self.call(client.list_files)                 # cùng kết nối vẫn dùng được

    # ---- SERVER_BUSY: fatal; các lần thử sau vẫn phải sinh đủ dòng FAILED cho runner đếm
    def test_server_busy_is_fatal_and_every_later_attempt_still_logs_a_failed_row(self):
        def handler(sock, conn, srv):
            conn.send_header({"status": "ERROR", "code": "SERVER_BUSY", "message": "max_clients"})

        client = self.start(handler)
        self.assertTrue(client.connected)            # connect không chờ greeting
        with self.assertRaises(ServerError) as ctx:
            self.call(client.upload, str(self.source()))
        self.assertEqual(ctx.exception.code, "SERVER_BUSY")
        self.assertFalse(ctx.exception.recoverable)
        self.assertFalse(client.connected)
        with self.assertRaises(Exception):           # runner không tự reconnect: lần thử sau lỗi "Not connected"
            self.call(client.upload, str(self.source()))
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["FAILED", "FAILED"])  # runner đối chiếu số dòng kỳ vọng
        self.assertTrue(all(r["throughput_mbps"] == "" for r in rows))
        self.assertTrue(all(r["client_id"] == "client-03" for r in rows))
        self.assertEqual(self.gate.calls, [])

    # ---- failed_attempt() của runner (upload lỗi thì download bị bỏ qua) vẫn ghi FAILED
    def test_runner_failed_attempt_helper_logs_failed_without_throughput(self):
        client = self.start(lambda sock, conn, srv: None)
        client.failed_attempt("download", "x.bin", 1234, "Skipped: upload did not succeed")
        row, = self.rows()
        self.assertEqual((row["direction"], row["status"], row["throughput_mbps"], row["file_size_bytes"]),
                         ("download", "FAILED", "", "1234"))
        self.assertEqual(row["error_message"], "Skipped: upload did not succeed")


if __name__ == "__main__":
    unittest.main()
