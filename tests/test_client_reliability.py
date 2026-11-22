"""Client reliability tests (Sprint 2) against a scripted fake server on loopback.

No dependency on the real server package: each test scripts exactly what the
server says, so error paths (FILE_BUSY, SERVER_BUSY, dropped connections,
bad checksums) can be triggered deterministically.
"""
import contextlib
import csv
import hashlib
import io
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from client.client import (  # noqa: E402
    ClientError, FileClient, ServerError, TransferInterrupted, build_parser,
    handle_command, run_safely,
)
from common.protocol import Connection  # noqa: E402


def sha(data):
    return hashlib.sha256(data).hexdigest()


class FakeServer:
    """Accepts one connection per handler, in order; each handler gets a Connection."""

    def __init__(self, *handlers):
        self.handlers = list(handlers)
        self.errors = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.listener.settimeout(5)
        self.address = self.listener.getsockname()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        for handler in self.handlers:
            try:
                sock, _ = self.listener.accept()
            except OSError:
                return
            sock.settimeout(5)
            try:
                handler(sock, Connection(sock))
            except BaseException as exc:  # reported by the test
                self.errors.append(exc)
            finally:
                sock.close()

    def close(self):
        self.listener.close()
        self.thread.join(timeout=5)


def read_payload(conn, size):
    data = bytearray()
    while len(data) < size:
        data.extend(conn.receive_chunk(size - len(data)))
    return bytes(data)


class ClientTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.downloads = self.root / "downloads"
        self.csv_path = self.root / "results.csv"
        self.server = None
        self.client = None

    def tearDown(self):
        if self.client is not None:
            self.client.drop()
        if self.server is not None:
            self.server.close()
            self.assertEqual(self.server.errors, [])
        self.temp.cleanup()

    def start(self, *handlers):
        self.server = FakeServer(*handlers)
        self.client = FileClient(csv_path=self.csv_path, environment_id="env-test",
                                 chunk_size=4096, download_dir=self.downloads,
                                 auto_environment=False)
        return self.client

    def connect(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.client.connect(*self.server.address)

    def local_file(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def run_command(self, line):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run_safely(self.client, line)
        return out.getvalue()

    def rows(self):
        with self.csv_path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))


class UploadTests(ClientTestCase):
    def test_tc01_normal_upload(self):
        data = bytes(range(256)) * 100
        received = {}

        def handler(sock, conn):
            header = conn.receive_header()
            conn.send_header({"status": "READY", "command": "UPLOAD",
                              "filename": header["filename"], "file_size": header["file_size"]})
            received["data"] = read_payload(conn, header["file_size"])
            conn.send_header({"status": "SUCCESS", "command": "UPLOAD", "filename": header["filename"],
                              "file_size": header["file_size"], "sha256": sha(received["data"])})
            received["header"] = header

        client = self.start(handler)
        self.connect()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            client.upload(str(self.local_file("a.bin", data)))
        self.assertEqual(received["data"], data)
        self.assertEqual(received["header"]["sha256"], sha(data))
        self.assertIn("SHA-256 MATCH", out.getvalue())
        row, = self.rows()
        self.assertEqual((row["status"], row["checksum_match"]), ("SUCCESS", "true"))
        self.assertNotEqual(row["throughput_mbps"], "")

    def test_tc02_file_busy_before_ready_sends_no_payload(self):
        seen = []

        def handler(sock, conn):
            seen.append(conn.receive_header())
            conn.send_header({"status": "ERROR", "code": "FILE_BUSY", "message": "File is being written"})
            # If the client wrongly sent the payload, this next read would see binary garbage.
            seen.append(conn.receive_header())
            conn.send_header({"status": "OK", "command": "LIST", "files": []})

        client = self.start(handler)
        self.connect()
        path = self.local_file("busy.bin", b"\x00PAYLOAD-SHOULD-NOT-BE-SENT" * 50)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(ServerError) as ctx:
                client.upload(str(path))
        self.assertEqual(ctx.exception.code, "FILE_BUSY")
        self.assertTrue(ctx.exception.recoverable)
        self.assertNotIn("SHA-256 MATCH", out.getvalue())
        self.assertTrue(client.connected, "FILE_BUSY is recoverable: session must stay open")
        with contextlib.redirect_stdout(io.StringIO()):
            client.list_files()
        self.assertEqual([h["command"] for h in seen], ["UPLOAD", "LIST"])
        row, = self.rows()
        self.assertEqual(row["status"], "FAILED")
        self.assertIn("FILE_BUSY", row["error_message"])
        self.assertEqual(row["throughput_mbps"], "")

    def test_tc03_server_busy_is_reported_and_socket_closed(self):
        def handler(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "ERROR", "code": "SERVER_BUSY", "message": "Too many clients"})

        client = self.start(handler)
        self.connect()
        output = self.run_command("list")
        self.assertIn("SERVER_BUSY", output)
        self.assertIn("Too many clients", output)
        self.assertIn("connect", output)
        self.assertFalse(client.connected)

    def test_server_busy_on_upload_never_sends_payload(self):
        def handler(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "ERROR", "code": "SERVER_BUSY", "message": "Busy"})
            sock.settimeout(1)
            leaked = sock.recv(1)
            if leaked:
                raise AssertionError("Payload leaked after SERVER_BUSY")

        client = self.start(handler)
        self.connect()
        path = self.local_file("x.bin", b"x" * 20000)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ServerError):
            client.upload(str(path))
        self.assertFalse(client.connected)
        self.assertEqual(self.rows()[0]["status"], "FAILED")

    def test_upload_checksum_mismatch_from_server_is_not_a_match(self):
        data = b"hello world" * 1000

        def handler(sock, conn):
            header = conn.receive_header()
            conn.send_header({"status": "READY", "command": "UPLOAD",
                              "filename": header["filename"], "file_size": header["file_size"]})
            read_payload(conn, header["file_size"])
            conn.send_header({"status": "ERROR", "code": "CHECKSUM_MISMATCH", "message": "Hash differs"})

        client = self.start(handler)
        self.connect()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(ServerError) as ctx:
            client.upload(str(self.local_file("m.bin", data)))
        self.assertEqual(ctx.exception.code, "CHECKSUM_MISMATCH")
        self.assertNotIn("SHA-256 MATCH", out.getvalue())
        row, = self.rows()
        self.assertEqual((row["status"], row["checksum_match"]), ("FAILED", "false"))
        self.assertEqual(row["throughput_mbps"], "")

    def test_upload_hash_comes_from_sha256_file(self):
        """sha256_file is the single source of the upload hash (other tests patch it)."""
        def handler(sock, conn):
            header = conn.receive_header()
            conn.send_header({"status": "READY", "command": "UPLOAD",
                              "filename": header["filename"], "file_size": header["file_size"]})
            data = read_payload(conn, header["file_size"])
            if sha(data) != header["sha256"]:
                conn.send_header({"status": "ERROR", "code": "CHECKSUM_MISMATCH", "message": "Hash differs"})
            else:
                conn.send_header({"status": "SUCCESS", "command": "UPLOAD", "filename": header["filename"],
                                  "file_size": len(data), "sha256": sha(data)})

        client = self.start(handler)
        self.connect()
        path = self.local_file("h.bin", b"hash me" * 200)
        with patch("client.client.sha256_file", return_value="0" * 64):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ServerError) as ctx:
                client.upload(str(path))
        self.assertEqual(ctx.exception.code, "CHECKSUM_MISMATCH")
        row, = self.rows()
        self.assertEqual((row["status"], row["checksum_match"], row["throughput_mbps"]), ("FAILED", "false", ""))

    def test_upload_success_with_wrong_server_hash_is_failed(self):
        def handler(sock, conn):
            header = conn.receive_header()
            conn.send_header({"status": "READY", "command": "UPLOAD",
                              "filename": header["filename"], "file_size": header["file_size"]})
            read_payload(conn, header["file_size"])
            conn.send_header({"status": "SUCCESS", "command": "UPLOAD", "filename": header["filename"],
                              "file_size": header["file_size"], "sha256": sha(b"something else")})

        client = self.start(handler)
        self.connect()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(ClientError):
            client.upload(str(self.local_file("w.bin", b"data" * 100)))
        self.assertNotIn("SHA-256 MATCH", out.getvalue())
        self.assertEqual(self.rows()[0]["status"], "FAILED")

    def test_connection_lost_mid_upload_is_failed_and_socket_closed(self):
        def handler(sock, conn):
            header = conn.receive_header()
            conn.send_header({"status": "READY", "command": "UPLOAD",
                              "filename": header["filename"], "file_size": header["file_size"]})
            conn.receive_chunk(1024)  # take a little, then vanish

        client = self.start(handler)
        self.connect()
        path = self.local_file("big.bin", b"\xab" * (8 * 1024 * 1024))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(TransferInterrupted):
            client.upload(str(path))
        self.assertFalse(client.connected)
        self.assertNotIn("SHA-256 MATCH", out.getvalue())
        row, = self.rows()
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(row["throughput_mbps"], "")
        self.assertNotEqual(row["error_message"], "")
        self.assertRegex(row["error_message"], r"^(CONNECTION_OR_IO_ERROR|TIMEOUT):")

    def test_connection_lost_before_confirmation_is_unverified(self):
        def handler(sock, conn):
            header = conn.receive_header()
            conn.send_header({"status": "READY", "command": "UPLOAD",
                              "filename": header["filename"], "file_size": header["file_size"]})
            read_payload(conn, header["file_size"])  # then close without SUCCESS

        client = self.start(handler)
        self.connect()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(TransferInterrupted) as ctx:
            client.upload(str(self.local_file("u.bin", b"abc" * 1000)))
        self.assertIn("unverified", str(ctx.exception))
        self.assertEqual(self.rows()[0]["status"], "FAILED")

    def test_unreadable_local_file_keeps_the_session(self):
        seen = []

        def handler(sock, conn):
            seen.append(conn.receive_header())
            conn.send_header({"status": "OK", "command": "QUIT"})

        client = self.start(handler)
        self.connect()
        path = self.local_file("locked.bin", b"data")
        with patch("client.client.open", side_effect=PermissionError("file is locked"), create=True):
            output = self.run_command(f'upload "{path}"')
        self.assertIn("Cannot read local file", output)
        self.assertTrue(client.connected, "a local file problem must not drop the connection")
        self.run_command("quit")
        self.assertEqual([h["command"] for h in seen], ["QUIT"])

    def test_missing_local_file_does_not_crash(self):
        client = self.start(lambda sock, conn: None)
        self.connect()
        output = self.run_command("upload does-not-exist.bin")
        self.assertIn("Local file does not exist", output)
        self.assertTrue(client.connected)


class DownloadTests(ClientTestCase):
    @staticmethod
    def serve_download(data, claimed_sha=None, send=None, finish=True):
        def handler(sock, conn):
            header = conn.receive_header()
            conn.send_header({"status": "OK", "command": "DOWNLOAD",
                              "filename": header["filename"], "file_size": len(data)})
            sock.sendall(data if send is None else send)
            if finish:
                conn.send_header({"status": "SUCCESS", "command": "DOWNLOAD", "filename": header["filename"],
                                  "file_size": len(data), "sha256": claimed_sha or sha(data)})
        return handler

    def test_download_success_publishes_file(self):
        data = bytes(range(256)) * 300
        client = self.start(self.serve_download(data))
        self.connect()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            client.download("d.bin")
        self.assertEqual((self.downloads / "d.bin").read_bytes(), data)
        self.assertFalse((self.downloads / "d.bin.part").exists())
        self.assertIn("SHA-256 MATCH", out.getvalue())
        self.assertEqual(self.rows()[0]["status"], "SUCCESS")

    def test_tc04_interrupted_download_removes_part_file_and_keeps_old_file(self):
        self.downloads.mkdir()
        (self.downloads / "d.bin").write_bytes(b"GOOD OLD FILE")
        data = b"z" * 10000
        client = self.start(self.serve_download(data, send=data[:4000], finish=False))
        self.connect()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(TransferInterrupted):
            client.download("d.bin")
        self.assertFalse((self.downloads / "d.bin.part").exists())
        self.assertEqual((self.downloads / "d.bin").read_bytes(), b"GOOD OLD FILE")
        self.assertFalse(client.connected)
        row, = self.rows()
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(row["throughput_mbps"], "")
        self.assertIn("CONNECTION_OR_IO_ERROR", row["error_message"])

    def test_tc05_checksum_mismatch_does_not_overwrite_old_file(self):
        self.downloads.mkdir()
        (self.downloads / "d.bin").write_bytes(b"GOOD OLD FILE")
        data = b"corrupted?" * 500
        client = self.start(self.serve_download(data, claimed_sha=sha(b"what the server really had")))
        self.connect()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(ClientError) as ctx:
            client.download("d.bin")
        self.assertIn("CHECKSUM_MISMATCH", str(ctx.exception))
        self.assertNotIn("SHA-256 MATCH", out.getvalue())
        self.assertEqual((self.downloads / "d.bin").read_bytes(), b"GOOD OLD FILE")
        self.assertFalse((self.downloads / "d.bin.part").exists())
        row, = self.rows()
        self.assertEqual((row["status"], row["checksum_match"]), ("FAILED", "false"))

    def test_download_missing_checksum_is_failed_not_match(self):
        def handler(sock, conn):
            header = conn.receive_header()
            conn.send_header({"status": "OK", "command": "DOWNLOAD", "filename": header["filename"], "file_size": 3})
            sock.sendall(b"abc")
            conn.send_header({"status": "SUCCESS", "command": "DOWNLOAD", "filename": header["filename"], "file_size": 3})

        client = self.start(handler)
        self.connect()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ClientError):
            client.download("n.bin")
        self.assertFalse((self.downloads / "n.bin").exists())
        self.assertFalse((self.downloads / "n.bin.part").exists())

    def test_download_file_busy_before_ok_is_recoverable(self):
        def handler(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "ERROR", "code": "FILE_BUSY", "message": "File is currently in use"})
            conn.receive_header()
            conn.send_header({"status": "OK", "command": "LIST", "files": ["same.bin"]})

        client = self.start(handler)
        self.connect()
        self.assertIn("FILE_BUSY", self.run_command("download same.bin"))
        self.assertTrue(client.connected)
        self.assertFalse((self.downloads / "same.bin").exists())
        self.assertFalse((self.downloads / "same.bin.part").exists())
        self.assertIn("same.bin", self.run_command("list"))
        self.assertEqual(self.rows()[0]["status"], "FAILED")

    def test_download_file_not_found_is_recoverable(self):
        def handler(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "ERROR", "code": "FILE_NOT_FOUND", "message": "Requested file does not exist"})
            conn.receive_header()
            conn.send_header({"status": "OK", "command": "LIST", "files": ["a.txt"]})

        client = self.start(handler)
        self.connect()
        output = self.run_command("download nope.bin")
        self.assertIn("FILE_NOT_FOUND", output)
        self.assertTrue(client.connected)
        self.assertIn("a.txt", self.run_command("list"))

    def test_each_instance_uses_its_own_download_dir(self):
        data = b"shared name" * 10
        first = FileClient(csv_path=self.root / "one.csv", environment_id="e", download_dir=self.root / "c1",
                           auto_environment=False)
        second = FileClient(csv_path=self.root / "two.csv", environment_id="e", download_dir=self.root / "c2",
                            auto_environment=False)
        for client in (first, second):
            self.server = FakeServer(self.serve_download(data))
            with contextlib.redirect_stdout(io.StringIO()):
                client.connect(*self.server.address)
                client.download("same.bin")
            client.drop()
            self.server.close()
            self.assertEqual(self.server.errors, [])
        self.server = None
        self.assertTrue((self.root / "c1" / "same.bin").exists())
        self.assertTrue((self.root / "c2" / "same.bin").exists())

    def test_download_dir_command_line_option(self):
        args = build_parser().parse_args(["--download-dir", str(self.root / "mine")])
        self.assertEqual(args.download_dir, self.root / "mine")


class RecoveryTests(ClientTestCase):
    def test_tc06_reconnect_after_fatal_error(self):
        def failing(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "ERROR", "code": "TIMEOUT", "message": "Client inactivity timeout"})

        def healthy(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "OK", "command": "LIST", "files": ["after.txt"]})

        client = self.start(failing, healthy)
        self.connect()
        output = self.run_command("list")
        self.assertIn("TIMEOUT", output)
        self.assertFalse(client.connected)
        self.assertIn("Not connected", self.run_command("list"))
        self.connect()  # a brand-new session on the same FileClient
        self.assertTrue(client.connected)
        self.assertIn("after.txt", self.run_command("list"))

    def test_unknown_error_code_is_treated_as_fatal(self):
        def handler(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "ERROR", "code": "SOMETHING_NEW", "message": "?"})

        client = self.start(handler)
        self.connect()
        self.assertIn("SOMETHING_NEW", self.run_command("list"))
        self.assertFalse(client.connected)

    def test_malformed_error_code_does_not_crash(self):
        def handler(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "ERROR", "code": ["not", "a", "string"], "message": 5})

        client = self.start(handler)
        self.connect()
        self.assertIn("Error", self.run_command("list"))
        self.assertFalse(client.connected)

    def test_server_closes_without_reply_is_reported(self):
        client = self.start(lambda sock, conn: conn.receive_header())
        self.connect()
        output = self.run_command("list")
        self.assertIn("Connection closed", output)
        self.assertFalse(client.connected)

    def test_server_not_reachable(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        self.client = FileClient(csv_path=self.csv_path, environment_id="e", auto_environment=False)
        output = self.run_command(f"connect 127.0.0.1 {port}")
        self.assertIn("Server not reachable", output)
        self.assertFalse(self.client.connected)

    def test_client_cannot_be_used_by_two_threads_at_once(self):
        client = self.start(lambda sock, conn: conn.receive_header())
        self.connect()
        with client.exclusive():  # another thread is "in the middle of" an operation
            with self.assertRaises(RuntimeError):
                client.list_files()
        # once the other operation is over the client is usable again
        self.assertTrue(client.connected)

    def test_client_can_be_handed_to_another_thread(self):
        def handler(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "OK", "command": "LIST", "files": ["x.txt"]})

        client = self.start(handler)
        self.connect()  # connected on the main thread...
        result = {}

        def worker():
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    client.list_files()  # ...used on a worker thread
                result["out"] = out.getvalue()
            except BaseException as exc:
                result["error"] = exc

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertNotIn("error", result)
        self.assertIn("x.txt", result["out"])


class ListQuitTests(ClientTestCase):
    def test_tc07_list_and_quit_like_sprint1(self):
        def handler(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "OK", "command": "LIST", "files": ["a.txt", "b.bin"]})
            header = conn.receive_header()
            assert header == {"command": "QUIT"}
            conn.send_header({"status": "OK", "command": "QUIT"})

        client = self.start(handler)
        self.connect()
        listing = self.run_command("list")
        self.assertIn("a.txt", listing)
        self.assertIn("b.bin", listing)
        farewell = self.run_command("quit")
        self.assertIn("Disconnected from server.", farewell)
        self.assertFalse(client.connected)

    def test_invalid_command_message(self):
        self.client = FileClient(csv_path=self.csv_path, environment_id="e", auto_environment=False)
        self.assertIn("Invalid command", self.run_command("frobnicate"))
        self.assertFalse(handle_command(self.client, "quit"))


class ErrorContractTests(ClientTestCase):
    """S2-01 additions: D03 (SERVER_BUSY right after accept), strict no-payload, error codes."""

    def test_server_busy_sent_right_after_accept_before_any_command(self):
        def busy(sock, conn):  # D03: do not read a command; send SERVER_BUSY and close
            conn.send_header({"status": "ERROR", "code": "SERVER_BUSY",
                              "message": "Server has reached max_clients limit"})

        client = self.start(busy)
        started = time.monotonic()
        self.connect()  # must not block waiting for a greeting
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(client.connected)  # TCP established; the refusal arrives with the first command
        out = self.run_command("list")
        # On Windows the close may surface as a reset instead of the JSON error frame.
        self.assertTrue("SERVER_BUSY" in out or "CONNECTION_OR_IO_ERROR" in out, out)
        self.assertFalse(client.connected)

    def test_reconnect_after_server_busy(self):
        def busy(sock, conn):
            conn.send_header({"status": "ERROR", "code": "SERVER_BUSY", "message": "full"})

        def healthy(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "OK", "command": "LIST", "files": ["ok.txt"]})

        client = self.start(busy, healthy)
        self.connect()
        self.run_command("list")
        self.assertFalse(client.connected)
        self.connect()  # manual reconnect = brand-new session
        self.assertTrue(client.connected)
        self.assertIn("ok.txt", self.run_command("list"))

    def test_server_busy_on_upload_after_accept_sends_no_payload(self):
        def busy(sock, conn):
            conn.send_header({"status": "ERROR", "code": "SERVER_BUSY", "message": "full"})
            sock.settimeout(1)
            try:
                data = sock.recv(65536)  # the UPLOAD header may arrive; payload must not
            except OSError:
                return
            if len(data) > 4096:
                raise AssertionError("payload leaked after SERVER_BUSY")

        client = self.start(busy)
        self.connect()
        path = self.local_file("big.bin", b"x" * (2 * 1024 * 1024))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                client.upload(str(path))
            except (ServerError, ClientError, OSError):
                pass
        self.assertFalse(client.connected)
        self.assertNotIn("SHA-256 MATCH", out.getvalue())
        self.assertEqual(self.rows()[0]["status"], "FAILED")

    def test_file_busy_no_bytes_follow_the_upload_header(self):
        """Strict TC02: after FILE_BUSY nothing but the next command reaches the server."""
        upload_returned = threading.Event()
        checked = threading.Event()  # server finished inspecting; only now may the client send LIST
        leaked = {}

        def handler(sock, conn):
            conn.receive_header()
            conn.send_header({"status": "ERROR", "code": "FILE_BUSY", "message": "File is currently in use"})
            if not upload_returned.wait(5):
                raise AssertionError("client.upload never returned")
            leaked["buffered"] = bytes(conn.buffer)  # bytes read together with the header
            sock.settimeout(0.3)
            try:
                leaked["socket"] = sock.recv(65536)  # client has not sent LIST yet: must time out
            except socket.timeout:
                leaked["socket"] = b""
            checked.set()
            sock.settimeout(5)
            self.assertEqual(conn.receive_header(), {"command": "LIST"})
            conn.send_header({"status": "OK", "command": "LIST", "files": []})

        client = self.start(handler)
        self.connect()
        path = self.local_file("busy.bin", b"PAYLOAD" * 1000)
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                with self.assertRaises(ServerError):
                    client.upload(str(path))
            finally:
                upload_returned.set()
            self.assertTrue(client.connected)
            self.assertTrue(checked.wait(5))
            client.list_files()
        self.assertEqual(leaked, {"buffered": b"", "socket": b""})

    def test_silent_server_is_reported_as_timeout(self):
        release = threading.Event()
        client = self.start(lambda sock, conn: (conn.receive_header(), release.wait(5)))
        self.connect()
        client.sock.settimeout(0.3)
        try:
            out = self.run_command("list")
        finally:
            release.set()
        self.assertIn("TIMEOUT", out)
        self.assertFalse(client.connected)

    def test_download_stalled_is_timeout_cleans_part_and_logs_code(self):
        release = threading.Event()
        data = b"z" * 10000

        def handler(sock, conn):
            header = conn.receive_header()
            conn.send_header({"status": "OK", "command": "DOWNLOAD",
                              "filename": header["filename"], "file_size": len(data)})
            sock.sendall(data[:1000])
            release.wait(5)  # stall: neither more bytes nor close

        self.downloads.mkdir()
        (self.downloads / "d.bin").write_bytes(b"GOOD OLD FILE")
        client = self.start(handler)
        self.connect()
        client.sock.settimeout(0.3)
        try:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(TransferInterrupted) as ctx:
                client.download("d.bin")
        finally:
            release.set()
        self.assertIn("TIMEOUT", str(ctx.exception))
        self.assertFalse((self.downloads / "d.bin.part").exists())
        self.assertEqual((self.downloads / "d.bin").read_bytes(), b"GOOD OLD FILE")
        self.assertFalse(client.connected)
        row, = self.rows()
        self.assertEqual(row["status"], "FAILED")
        self.assertTrue(row["error_message"].startswith("TIMEOUT"))
        self.assertEqual(row["throughput_mbps"], "")

    def test_server_closes_silently_is_connection_or_io_error(self):
        client = self.start(lambda sock, conn: conn.receive_header())
        self.connect()
        out = self.run_command("list")
        self.assertIn("CONNECTION_OR_IO_ERROR", out)
        self.assertIn("connect", out)
        self.assertFalse(client.connected)


if __name__ == "__main__":
    unittest.main()
