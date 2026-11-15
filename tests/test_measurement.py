"""Measurement tests use temporary directories, never the real baseline CSV."""
import csv
import hashlib
import io
import json
import logging
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from client.client import FileClient, ClientError, ServerError, ChecksumMismatch
from common.csv_logger import append_result, FIELDS
from common.measurement import Measurement, throughput_mbps
from common.environment import collect_host, save_environment
from generate_test_files import generate_files, SIZES
from server.config import ServerConfig
from server.server import FileServer


class MeasurementTests(unittest.TestCase):
    def test_formula_and_invalid_duration(self):
        self.assertEqual(throughput_mbps(10_000_000, 2), 40)
        for elapsed in (0, -1, float("nan"), float("inf"), None):
            with self.assertRaises(ValueError):
                throughput_mbps(10, elapsed)

    def test_clock_boundaries_and_unique_ids(self):
        one = Measurement("upload", "a", 65536)
        two = Measurement("upload", "a", 65536)
        self.assertNotEqual(one.row["run_id"], two.row["run_id"])
        one.row.update(file_size_bytes=10_000_000, checksum_match=True)
        with patch("common.measurement.time.perf_counter", side_effect=[100, 102]):
            one.start()
            one.finish()
        self.assertEqual((one.transfer_start, one.transfer_end), (100, 102))
        self.assertEqual(one.row["throughput_mbps"], 40)
        self.assertEqual(one.row["status"], "SUCCESS")

    def test_no_success_without_verified_checksum(self):
        m = Measurement("download", "a", 65536)
        m.start()
        with self.assertRaises(ValueError):
            m.finish()
        self.assertEqual(m.row["status"], "FAILED")
        self.assertIsNone(m.row["throughput_mbps"])

    def test_csv_append_and_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested/raw.csv"
            for _ in range(2):
                m = Measurement("upload", 'a,"b.bin', 65536)
                m.finish(OSError("failure, with comma\nand newline"))
                append_result(path, m.row)
            with path.open(newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["file_name"], 'a,"b.bin')
            self.assertNotEqual(rows[0]["run_id"], rows[1]["run_id"])
            self.assertEqual(list(rows[0]), FIELDS)
            path.write_text("wrong,schema\n")
            with self.assertRaises(ValueError):
                append_result(path, m.row)

    def test_generator_sizes_reproducibility_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            paths = generate_files(temp)
            hashes = []
            for p, size in zip(paths, SIZES):
                self.assertEqual(p.stat().st_size, size)
                with p.open("rb") as stream:
                    hashes.append(hashlib.file_digest(stream, "sha256").hexdigest())
            with self.assertRaises(FileExistsError):
                generate_files(temp)
            generate_files(temp, force=True)
            for path, expected in zip(paths, hashes):
                with path.open("rb") as stream:
                    self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), expected)

    def test_metadata_keeps_old_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            client = collect_host("client", "127.0.0.1", "loopback", 65536)
            server = collect_host("server", "127.0.0.1", "loopback", 65536)
            ids = [save_environment(client, server, 5000, temp) for _ in range(2)]
            self.assertNotEqual(*ids)
            for value in ids:
                self.assertTrue((Path(temp) / "environments" / f"{value}.json").exists())
            latest = json.loads((Path(temp) / "environment.json").read_text())
            self.assertEqual(latest["environment_id"], ids[-1])


class ClientLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server = FileServer(ServerConfig(host="127.0.0.1", port=0,
            storage_dir=self.root / "storage", client_timeout=2), logging.getLogger("measurement_test"))
        self.server.start()
        self.errors = []
        def run():
            try:
                self.server.serve_forever()
            except BaseException as exc:
                self.errors.append(exc)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        self.client = FileClient(csv_path=self.root / "raw.csv", auto_environment=False,
                                 environment_id="test-only", download_dir=self.root / "downloads")
        self.client.connect(*self.server.address)

    def tearDown(self):
        self.client.drop()
        self.server.close()
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.errors, [])
        self.temp.cleanup()

    def rows(self):
        with (self.root / "raw.csv").open(newline="") as stream:
            return list(csv.DictReader(stream))

    def source(self):
        path = self.root / "sample.bin"
        path.write_bytes(bytes(range(256)) * 300)
        return path

    def test_real_upload_download_success_and_list_quit_not_logged(self):
        path = self.source()
        self.client.upload(str(path))
        self.client.download(path.name)
        self.client.list_files()
        self.client.quit()
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["direction"] for r in rows], ["upload", "download"])
        self.assertEqual((self.root / "downloads" / path.name).read_bytes(), path.read_bytes())
        for row in rows:
            self.assertEqual((row["status"], row["checksum_match"]), ("SUCCESS", "true"))
            expected = throughput_mbps(int(row["file_size_bytes"]), float(row["transfer_time_s"]))
            self.assertEqual(float(row["throughput_mbps"]), expected)

    def test_upload_mismatch_logged_once(self):
        with patch("client.client.sha256_file", return_value="0" * 64):
            with self.assertRaises(ServerError):
                self.client.upload(str(self.source()))
        row, = self.rows()
        self.assertEqual((row["status"], row["checksum_match"], row["throughput_mbps"]),
                         ("FAILED", "false", ""))

    def test_download_mismatch_preserves_old_file(self):
        path = self.source()
        self.client.upload(str(path))
        self.client.download_dir.mkdir()
        target = self.client.download_dir / path.name
        target.write_bytes(b"old")
        with patch("client.client.verify_checksum", side_effect=ChecksumMismatch("CHECKSUM_MISMATCH")):
            with self.assertRaises(ChecksumMismatch):
                self.client.download(path.name)
        self.assertEqual(target.read_bytes(), b"old")
        self.assertFalse(target.with_suffix(".bin.part").exists())
        self.assertEqual(self.rows()[-1]["checksum_match"], "false")
        self.assertEqual(self.rows()[-1]["throughput_mbps"], "")

    def test_timeout_and_missing_file_are_failed(self):
        with patch.object(self.client, "read_response", side_effect=socket.timeout("test timeout")):
            with self.assertRaises(socket.timeout):
                self.client.upload(str(self.source()))
        with self.assertRaises(ClientError):
            self.client.upload(str(self.root / "missing.bin"))
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["status"], "FAILED")
            self.assertEqual(row["throughput_mbps"], "")
            self.assertEqual(row["checksum_match"], "")

    def test_invalid_checksum_unknown_and_csv_error_visible(self):
        with patch("client.client.verify_checksum", side_effect=ClientError("invalid SHA-256")):
            with self.assertRaises(ClientError):
                self.client.upload(str(self.source()))
        self.assertEqual(self.rows()[-1]["checksum_match"], "")
        with patch("client.client.append_result", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(ClientError, "CSV LOGGING FAILED"):
                self.client.upload(str(self.root / "missing.bin"))


if __name__ == "__main__":
    unittest.main()
