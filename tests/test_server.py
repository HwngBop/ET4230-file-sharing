"""Exercise the server through real loopback TCP connections."""

import io
import json
import logging
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from common.protocol import Connection, MAX_HEADER_BYTES, encode_header
from server.config import ServerConfig, load_config
from server.logging_config import EventFormatter
from server.server import FileServer


class Client:
    def __init__(self, address):
        self.socket = socket.create_connection(address, timeout=3)
        self.stream = self.socket.makefile("rb")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()
        self.socket.close()

    def send(self, command, **values):
        self.socket.sendall(encode_header({"command": command, **values}))

    def receive(self):
        line = self.stream.readline()
        if not line:
            raise EOFError("Server closed the connection")
        return json.loads(line)

    def upload(self, filename, data):
        self.send("UPLOAD", filename=filename, file_size=len(data))
        response = self.receive()
        if response["status"] != "READY":
            raise AssertionError(response)
        self.socket.sendall(data)
        return self.receive()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.log_output = io.StringIO()
        self.logger = logging.Logger(self.id())
        handler = logging.StreamHandler(self.log_output)
        handler.setFormatter(EventFormatter())
        self.logger.addHandler(handler)
        self.server = FileServer(ServerConfig(
            host="127.0.0.1", port=0,
            storage_dir=self.root / "storage", log_file=self.root / "server.log",
            chunk_size=1024, max_file_size=1024 * 1024, client_timeout=0.4,
        ), self.logger)
        self.server.start()
        self.address = self.server.address
        self.server_errors = []

        def run_server():
            try:
                self.server.serve_forever()
            except BaseException as exc:
                self.server_errors.append(exc)

        self.thread = threading.Thread(target=run_server, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.close()
        self.thread.join(timeout=3)
        try:
            self.assertFalse(self.thread.is_alive(), "Server thread did not stop")
            self.assertEqual(self.server_errors, [])
        finally:
            self.temporary.cleanup()

    def assert_server_available(self):
        with Client(self.address) as client:
            client.send("LIST")
            self.assertEqual(client.receive()["status"], "OK")

    def test_upload_download_binary_and_empty_files(self):
        with Client(self.address) as client:
            for filename, data in (("sample.bin", bytes(range(256)) * 1025), ("empty.txt", b"")):
                with self.subTest(filename=filename):
                    result = client.upload(filename, data)
                    self.assertEqual(result["status"], "SUCCESS")
                    self.assertEqual(result["file_size"], len(data))
                    self.assertEqual((self.root / "storage" / filename).read_bytes(), data)
                    client.send("DOWNLOAD", filename=filename)
                    header = client.receive()
                    self.assertEqual(header["status"], "OK")
                    self.assertEqual(header["file_size"], len(data))
                    self.assertEqual(client.stream.read(header["file_size"]), data)
                    self.assertEqual(client.receive()["status"], "SUCCESS")
            client.send("LIST")
            self.assertEqual(client.receive()["files"], ["empty.txt", "sample.bin"])
            client.send("QUIT")
            self.assertEqual(client.receive(), {"status": "OK", "command": "QUIT"})
            self.assertEqual(client.stream.read(1), b"")

    def test_multiple_requests_in_one_tcp_write(self):
        with Client(self.address) as client:
            client.socket.sendall(encode_header({"command": "LIST"}) + encode_header({"command": "QUIT"}))
            self.assertEqual(client.receive()["command"], "LIST")
            self.assertEqual(client.receive()["command"], "QUIT")

    def test_upload_payload_and_next_request_in_one_tcp_write(self):
        with Client(self.address) as client:
            client.send("UPLOAD", filename="combined.bin", file_size=4)
            self.assertEqual(client.receive()["status"], "READY")
            client.socket.sendall(b"\x00\xff\nX" + encode_header({"command": "LIST"}))
            self.assertEqual(client.receive()["status"], "SUCCESS")
            self.assertEqual(client.receive()["files"], ["combined.bin"])

    def test_missing_file_and_unknown_command_are_recoverable(self):
        with Client(self.address) as client:
            client.send("DOWNLOAD", filename="missing.bin")
            self.assertEqual(client.receive()["code"], "FILE_NOT_FOUND")
            client.send("DELETE")
            self.assertEqual(client.receive()["code"], "INVALID_COMMAND")
            client.send("LIST")
            self.assertEqual(client.receive()["files"], [])

    def test_invalid_filenames(self):
        invalid = [None, "", ".", "..", "../escape", "..\\escape", "/absolute", "C:\\file",
                   "bad\x00name", "bad\nname", "file:stream", "CON", "NUL.txt", "COM1", "COM¹.txt",
                   "trailing.", "trailing ", ".uploads", "x" * 256, "\ud800"]
        with Client(self.address) as client:
            for filename in invalid:
                for command in ("UPLOAD", "DOWNLOAD"):
                    with self.subTest(filename=filename, command=command):
                        client.send(command, filename=filename, file_size=0)
                        self.assertEqual(client.receive()["code"], "INVALID_FILENAME")
            client.send("LIST")
            self.assertEqual(client.receive()["files"], [])

    def test_invalid_sizes(self):
        with Client(self.address) as client:
            for size in (None, -1, "10", 1.5, True):
                with self.subTest(size=size):
                    client.send("UPLOAD", filename="file.bin", file_size=size)
                    self.assertEqual(client.receive()["code"], "INVALID_FILE_SIZE")
            client.send("UPLOAD", filename="file.bin", file_size=1024 * 1024 + 1)
            self.assertEqual(client.receive()["code"], "FILE_TOO_LARGE")

    def test_partial_upload_preserves_original_and_cleans_temporary_file(self):
        target = self.root / "storage/existing.bin"
        target.write_bytes(b"original")
        with Client(self.address) as client:
            client.send("UPLOAD", filename="existing.bin", file_size=20)
            self.assertEqual(client.receive()["status"], "READY")
            client.socket.sendall(b"partial")
            client.socket.shutdown(socket.SHUT_WR)
            self.assertEqual(client.stream.read(), b"")
        self.assert_server_available()
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(list(self.server.storage.staging.iterdir()), [])
        records = [json.loads(line) for line in self.log_output.getvalue().splitlines()]
        transfer = next(record for record in records if record["status"] == "INCOMPLETE")
        self.assertEqual(transfer["transferred_bytes"], 7)
        self.assertEqual(transfer["file_size"], 20)

    def test_successful_upload_replaces_existing_file(self):
        with Client(self.address) as client:
            client.upload("same.txt", b"old contents")
            self.assertEqual(client.upload("same.txt", b"new")["status"], "SUCCESS")
        self.assertEqual((self.root / "storage/same.txt").read_bytes(), b"new")

    def test_list_hides_directories_and_staging(self):
        (self.root / "storage/folder").mkdir()
        (self.root / "storage/.gitkeep").touch()
        (self.server.storage.staging / "incomplete.part").write_bytes(b"partial")
        (self.root / "storage/b.txt").write_bytes(b"b")
        (self.root / "storage/a.txt").write_bytes(b"a")
        with Client(self.address) as client:
            client.send("LIST")
            self.assertEqual(client.receive()["files"], ["a.txt", "b.txt"])

    def test_malformed_and_oversized_headers_close_only_the_client(self):
        for payload, code in ((b"not json\n", "INVALID_HEADER"), (b"[]\n", "INVALID_HEADER"),
                              (b"\xff\n", "INVALID_HEADER"), (b"x" * MAX_HEADER_BYTES, "HEADER_TOO_LARGE")):
            with self.subTest(code=code), Client(self.address) as client:
                client.socket.sendall(payload)
                self.assertEqual(client.receive()["code"], code)
                self.assertEqual(client.stream.read(1), b"")
        self.assert_server_available()

    def test_clean_and_mid_header_disconnect_do_not_crash_server(self):
        with Client(self.address):
            pass
        with Client(self.address) as client:
            client.socket.sendall(b'{"comm')
        self.assert_server_available()

    def test_timeout_cleans_partial_upload_and_accepts_next_client(self):
        with Client(self.address) as client:
            client.send("UPLOAD", filename="timeout.bin", file_size=100)
            self.assertEqual(client.receive()["status"], "READY")
            client.socket.sendall(b"a")
            self.assertEqual(client.receive()["code"], "TIMEOUT")
            self.assertEqual(client.stream.read(1), b"")
        self.assert_server_available()
        self.assertFalse((self.root / "storage/timeout.bin").exists())
        self.assertEqual(list(self.server.storage.staging.iterdir()), [])

    def test_log_contains_required_transfer_fields(self):
        with Client(self.address) as client:
            client_port = client.socket.getsockname()[1]
            client.upload("logged.bin", b"1234")
            client.send("QUIT")
            client.receive()
        self.assert_server_available()
        records = [json.loads(line) for line in self.log_output.getvalue().splitlines()]
        transfer = next(record for record in records if record["command"] == "UPLOAD")
        self.assertTrue(transfer["timestamp"])
        self.assertEqual(transfer["client_ip"], "127.0.0.1")
        self.assertEqual(transfer["client_port"], client_port)
        self.assertEqual(transfer["filename"], "logged.bin")
        self.assertEqual(transfer["file_size"], 4)
        self.assertEqual(transfer["transferred_bytes"], 4)
        self.assertEqual(transfer["status"], "SUCCESS")

    def test_file_io_error_does_not_crash_server(self):
        with patch.object(self.server.storage, "create_upload", side_effect=OSError("Disk full")):
            with Client(self.address) as client:
                client.send("UPLOAD", filename="disk.bin", file_size=1)
                self.assertEqual(client.receive()["code"], "CONNECTION_OR_IO_ERROR")
                self.assertEqual(client.stream.read(1), b"")
        self.assert_server_available()


class ProtocolTests(unittest.TestCase):
    def test_fragmented_header_and_buffered_payload(self):
        class FragmentedSocket:
            def __init__(self):
                self.fragments = iter([b'{"comm', b'and":"UPLOAD",', b'"file_size":3}\nABC'])

            def recv(self, maximum):
                return next(self.fragments, b"")

        connection = Connection(FragmentedSocket())
        self.assertEqual(connection.receive_header(), {"command": "UPLOAD", "file_size": 3})
        self.assertEqual(connection.receive_chunk(2), b"AB")
        self.assertEqual(connection.receive_chunk(2), b"C")
        self.assertIsNone(connection.receive_header())


class ConfigTests(unittest.TestCase):
    def test_cli_overrides_json_and_resolves_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_file = root / "server.json"
            config_file.write_text(json.dumps({"port": 1234, "storage_dir": "data"}), encoding="utf-8")
            config = load_config(["--config", str(config_file), "--host", "127.0.0.1", "--port", "4321"])
            self.assertEqual(config.host, "127.0.0.1")
            self.assertEqual(config.port, 4321)
            self.assertEqual(config.storage_dir, root / "data")

    def test_invalid_configuration_is_rejected(self):
        for setting in ({"port": -1}, {"port": True}, {"chunk_size": 0},
                        {"max_file_size": -1}, {"client_timeout": 0}, {"client_timeout": float("nan")}):
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                ServerConfig(**setting)


if __name__ == "__main__":
    unittest.main()
