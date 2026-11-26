"""TIMEOUT do Client tự phát hiện phải nêu đúng socket_timeout của instance (S2-FIX-03).

File test độc lập (tự có fake server nhỏ), không phụ thuộc test_client_reliability.py.
"""
import contextlib
import csv
import io
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from client.client import FileClient, run_safely  # noqa: E402


class SilentServer:
    """Chấp nhận kết nối, đọc request rồi im lặng cho tới khi test kết thúc."""

    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.release = threading.Event()
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
                sock.recv(65536)
            except OSError:
                pass
            self.release.wait(5)

    def close(self):
        self.release.set()
        self.listener.close()
        self.thread.join(timeout=5)


class TimeoutLabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.server = SilentServer()
        self.client = FileClient(csv_path=self.dir / "r.csv", auto_environment=False,
                                 socket_timeout=0.4, download_dir=self.dir / "dl")

    def tearDown(self):
        self.client.drop()
        self.server.close()
        self.tmp.cleanup()

    def test_console_message_uses_instance_timeout(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.client.connect(*self.server.address)
            run_safely(self.client, "list")
        self.assertIn("TIMEOUT: no response from server within 0.4 s", out.getvalue())
        self.assertNotIn("30 s", out.getvalue())
        self.assertFalse(self.client.connected)

    def test_csv_error_message_uses_instance_timeout(self):
        path = self.dir / "up.bin"
        path.write_bytes(b"x" * 1000)
        with contextlib.redirect_stdout(io.StringIO()):
            self.client.connect(*self.server.address)
            run_safely(self.client, f'upload "{path}"')   # server không bao giờ gửi READY
        with (self.dir / "r.csv").open(newline="", encoding="utf-8") as stream:
            row, = list(csv.DictReader(stream))
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(row["throughput_mbps"], "")
        self.assertTrue(row["error_message"].startswith("TIMEOUT: no response from server within 0.4 s"),
                        row["error_message"])


if __name__ == "__main__":
    unittest.main()
