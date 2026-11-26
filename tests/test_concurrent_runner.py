"""Real TCP runner tests; temporary CSVs never touch Sprint 1 data.

Production concurrent Server/Storage are used by default. A deliberately
sequential fixture is only used as a negative concurrency control.
"""
import csv
from datetime import datetime, timezone
from uuid import uuid4
import importlib.util
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from server.server import FileServer
from server.config import ServerConfig
from run_concurrent import WorkerClient, ReadyGate, run_scenario, main, validate_worker_rows
from client.client import ServerError
from common.protocol import ProtocolError
from common.csv_logger import CONCURRENT_FIELDS, FIELDS
from common.environment import collect_host


class SequentialFileServer(FileServer):
    """Legacy sequential fixture: intentionally fails multi-client READY gates."""

    def serve_forever(self):
        listener = self.listener
        try:
            while not self.stopping:
                try:
                    sock, address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self.stopping:
                        break
                    raise
                with sock:
                    sock.settimeout(self.config.client_timeout)
                    self._handle_client(sock, address)
        finally:
            self.close()


def concurrent_server_class():
    dependency = os.environ.get("CONCURRENT_SERVER_FILE")
    if not dependency:
        return FileServer
    path = Path(dependency).resolve()
    spec = importlib.util.spec_from_file_location("server.concurrent_dependency", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FileServer


class ConcurrentRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.files = self.root / "fixtures"
        self.files.mkdir()
        (self.files / "a-test.bin").write_bytes(bytes(range(256)) * 16384)
        # A second file verifies gates are first-upload-only and IDs remain unique.
        (self.files / "second.bin").write_bytes(b"second-file" * 4096)
        self.server = None
        self.thread = None
        self.server_errors = []
        self.baseline = self.root / "results/raw/baseline.csv"
        self.baseline.parent.mkdir(parents=True)
        self.baseline.write_bytes(b"SPRINT 1 SENTINEL\r\n")

    def tearDown(self):
        if self.server:
            self.server.close()
        if self.thread:
            self.thread.join(5)
            self.assertFalse(self.thread.is_alive())
        self.assertEqual(self.server_errors, [])
        self.assertEqual(self.baseline.read_bytes(), b"SPRINT 1 SENTINEL\r\n")
        self.temp.cleanup()

    def start_server(self, sequential=False):
        config = ServerConfig(host="127.0.0.1", port=0, storage_dir=self.root / "storage",
                              log_file=self.root / "server.log", client_timeout=3)
        cls = SequentialFileServer if sequential else concurrent_server_class()
        self.server = cls(config, logging.getLogger("runner-test"))
        self.server.start()
        def serve():
            try:
                self.server.serve_forever()
            except BaseException as exc:
                self.server_errors.append(exc)
        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()

    def run_clients(self, count, **kwargs):
        return run_scenario(host="127.0.0.1", port=self.server.address[1], num_clients=count,
            files_dir=self.files, results_dir=self.root / "results", download=True,
            network_type="loopback", timeout=5, sync_timeout=1.5, **kwargs)

    def verify(self, summary, count):
        session = self.root / "results" / summary["session_id"]
        with (session / "all-transfers.csv").open(newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, CONCURRENT_FIELDS)
        self.assertEqual(len(rows), count * 4)
        self.assertEqual(len({r["run_id"] for r in rows}), len(rows))
        self.assertEqual(len({tuple(w["local_address"]) for w in summary["workers"]}), count)
        self.assertTrue(all(r["num_clients"] == str(count) for r in rows))
        self.assertEqual({r["environment_id"] for r in rows}, {summary["environment_id"]})
        self.assertEqual({r["session_id"] for r in rows}, {summary["session_id"]})
        self.assertEqual(len({r["client_id"] for r in rows}), count)
        meta = json.loads((session / "environment.json").read_text())
        self.assertEqual(meta["num_clients"], count)
        self.assertEqual(meta["chunk_size_bytes"], 65536)
        for worker in summary["workers"]:
            directory = session / worker["client_id"]
            csv_text = (directory / "transfers.csv").read_text()
            self.assertEqual(csv_text.count(",".join(CONCURRENT_FIELDS)), 1)
            for source in (directory / "uploads").glob("*.bin"):
                self.assertEqual(source.read_bytes(), (directory / "downloads" / source.name).read_bytes())
        for row in rows:
            self.assertEqual((row["status"], row["checksum_match"]), ("SUCCESS", "true"))
            self.assertGreater(float(row["throughput_mbps"]), 0)
        if count > 1:
            self.assertTrue(summary["concurrency"]["all_ready_before_payload"])
            self.assertGreater(summary["concurrency"]["shared_processing_overlap_s"], 0)
            self.assertGreater(summary["concurrency"]["shared_payload_completion_overlap_s"], 0)

    def test_tc01_one_client_upload_download(self):
        self.start_server(sequential=True)
        code, summary = self.run_clients(1)
        self.assertEqual(code, 0)
        self.assertEqual(summary["status"], "PASS")
        self.verify(summary, 1)

    def test_tc02_five_independent_clients_and_overlap(self):
        self.start_server()
        code, summary = self.run_clients(5)
        self.assertEqual(code, 0)
        self.assertEqual(summary["status"], "PASS")
        self.verify(summary, 5)

    def test_tc03_ten_clients(self):
        self.start_server()
        code, summary = self.run_clients(10)
        self.assertEqual(code, 0)
        self.verify(summary, 10)

    def test_tc04_failed_worker_does_not_stop_others_and_tc07_exit_failure(self):
        self.start_server()
        class FailingClient(WorkerClient):
            def connect(self, host, port):
                if self.client_id == "client-01":
                    raise OSError("injected worker connection failure")
                super().connect(host, port)
        code, summary = self.run_clients(5, client_factory=FailingClient)
        self.assertNotEqual(code, 0)
        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual([w["status"] for w in summary["workers"]], ["FAIL"] + ["PASS"] * 4)
        self.assertEqual(summary["actual_rows"], summary["expected_rows"])
        with (self.root / "results" / summary["session_id"] / "client-01/transfers.csv").open(newline="") as stream:
            failed = list(csv.DictReader(stream))
        self.assertEqual(len(failed), 4)
        self.assertTrue(all(r["status"] == "FAILED" and r["throughput_mbps"] == "" for r in failed))

    def test_tc05_csv_rerun_isolation_and_unchanged_sprint1_schema(self):
        self.start_server()
        for _ in range(2):
            code, summary = self.run_clients(5)
            self.assertEqual(code, 0)
            self.verify(summary, 5)
        sessions = [p for p in (self.root / "results").iterdir() if p.is_dir() and p.name != "raw"]
        self.assertEqual(len(sessions), 2)
        self.assertNotIn("client_id", FIELDS)
        self.assertNotIn("session_id", FIELDS)

    def test_tc06_exported_server_metadata(self):
        self.start_server()
        metadata = self.root / "server.json"
        metadata.write_text(json.dumps(collect_host("server", "127.0.0.1", "loopback", 65536)))
        code, summary = self.run_clients(1, server_metadata=metadata)
        self.assertEqual(code, 0)
        meta = json.loads((self.root / "results" / summary["session_id"] / "environment.json").read_text())
        self.assertTrue(meta["server_metadata_complete"])
        self.assertEqual(meta["server"]["role"], "server")
        self.assertTrue(meta["same_host"])

    def test_sequential_server_cannot_pass_concurrency_from_queued_requests(self):
        self.start_server(sequential=True)
        code, summary = run_scenario(host="127.0.0.1", port=self.server.address[1], num_clients=5,
            files_dir=self.files, results_dir=self.root / "results", timeout=5, sync_timeout=0.3)
        self.assertNotEqual(code, 0)
        self.assertEqual(summary["concurrency"]["status"], "FAIL")
        self.assertFalse(summary["concurrency"]["all_ready_before_payload"])

    def test_tc07_cli_refused_server_returns_nonzero_and_rows(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
            proc = subprocess.run([sys.executable, str(ROOT / "scripts/run_concurrent.py"),
                "--host", "127.0.0.1", "--port", str(port), "--num-clients", "1",
                "--files-dir", str(self.files), "--results-dir", str(self.root / "results"),
                "--timeout", "2", "--sync-timeout", "0.3"], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(proc.returncode, 0)
        summaries = list((self.root / "results").glob("*/summary.json"))
        self.assertEqual(len(summaries), 1)
        summary = json.loads(summaries[0].read_text())
        self.assertEqual(summary["actual_rows"], 2)
        self.assertEqual(summary["status"], "FAIL")

    def test_file_busy_logs_failure_and_allows_same_socket_retry(self):
        self.start_server()
        path = self.root / "busy.bin"
        path.write_bytes(b"retry-content" * 2048)
        client = WorkerClient(gate=ReadyGate(1, 1), client_id="client-01",
            session_id="busy-test", csv_fields=CONCURRENT_FIELDS,
            csv_path=self.root / "busy.csv", auto_environment=False,
            download_dir=self.root / "busy-downloads")
        upload = self.server._upload
        download = self.server._download
        blocked = {"upload": True, "download": True}
        def dispatch_upload(connection, request, context):
            if blocked["upload"]:
                blocked["upload"] = False
                raise ProtocolError("FILE_BUSY", "File is currently in use", fatal=False)
            return upload(connection, request, context)
        def dispatch_download(connection, request, context):
            if blocked["download"]:
                blocked["download"] = False
                raise ProtocolError("FILE_BUSY", "File is currently in use", fatal=False)
            return download(connection, request, context)
        try:
            client.connect(*self.server.address)
            with patch.object(self.server, "_upload", side_effect=dispatch_upload):
                with self.assertRaises(ServerError) as error:
                    client.upload(str(path))
                self.assertEqual(error.exception.code, "FILE_BUSY")
                self.assertTrue(client.connected)
                client.upload(str(path))
            with patch.object(self.server, "_download", side_effect=dispatch_download):
                with self.assertRaises(ServerError):
                    client.download(path.name)
                self.assertTrue(client.connected)
                client.download(path.name)
        finally:
            client.quit()
        with (self.root / "busy.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([r["status"] for r in rows], ["FAILED", "SUCCESS", "FAILED", "SUCCESS"])
        self.assertTrue(all(r["throughput_mbps"] == "" for r in rows if r["status"] == "FAILED"))
        self.assertEqual(path.read_bytes(), (client.download_dir / path.name).read_bytes())

    def test_wrong_num_clients_from_client_integration_cannot_pass(self):
        self.start_server()
        class WrongConfigurationClient(WorkerClient):
            def upload(self, path):
                result = super().upload(path)
                if self.client_id == "client-01":
                    with self.csv_path.open(newline="") as stream:
                        rows = list(csv.DictReader(stream))
                    for row in rows:
                        row["num_clients"] = "1"
                    with self.csv_path.open("w", newline="") as stream:
                        writer = csv.DictWriter(stream, fieldnames=CONCURRENT_FIELDS)
                        writer.writeheader()
                        writer.writerows(rows)
                return result
        code, summary = self.run_clients(5, client_factory=WrongConfigurationClient)
        self.assertNotEqual(code, 0)
        self.assertEqual(summary["workers"][0]["status"], "FAIL")
        self.assertEqual([w["status"] for w in summary["workers"][1:]], ["PASS"] * 4)
        self.assertTrue(any("configuration mismatch" in e for e in summary["workers"][0]["errors"]))

    def test_bad_success_metric_from_client_integration_cannot_pass(self):
        self.start_server()
        class WrongMetricClient(WorkerClient):
            def upload(self, path):
                result = super().upload(path)
                with self.csv_path.open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                rows[-1]["throughput_mbps"] = "nan"
                with self.csv_path.open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=CONCURRENT_FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
                return result
        code, summary = self.run_clients(1, client_factory=WrongMetricClient)
        self.assertNotEqual(code, 0)
        self.assertEqual(summary["workers"][0]["status"], "FAIL")
        self.assertTrue(any("Mbps metric" in e for e in summary["workers"][0]["errors"]))

    def test_wrong_file_size_with_consistent_mbps_cannot_pass(self):
        self.start_server()
        class WrongSizeClient(WorkerClient):
            def upload(self, path):
                result = super().upload(path)
                with self.csv_path.open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                row = rows[-1]
                row["file_size_bytes"] = "1"
                row["throughput_mbps"] = str(8 / (float(row["transfer_time_s"]) * 1_000_000))
                with self.csv_path.open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=CONCURRENT_FIELDS)
                    writer.writeheader()
                    writer.writerows(rows)
                return result
        code, summary = self.run_clients(1, client_factory=WrongSizeClient)
        self.assertNotEqual(code, 0)
        self.assertEqual(summary["workers"][0]["status"], "FAIL")
        self.assertTrue(any("differs from source fixture" in e for e in summary["workers"][0]["errors"]))

    def test_invalid_input_and_no_fixtures(self):
        with self.assertRaises(ValueError):
            run_scenario(host="not-an-IP")
        with self.assertRaises(ValueError):
            run_scenario(host="127.0.0.1", num_clients=0)
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(main(["--host", "127.0.0.1", "--files-dir", str(empty)]), 1)


class WorkerCsvValidationTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(run_id=str(uuid4()), timestamp=datetime.now(timezone.utc).isoformat(),
            direction="upload", file_name="fixture.bin", file_size_bytes="1000000",
            client_id="client-01", session_id="session", environment_id="environment",
            num_clients="5", chunk_size_bytes="65536", status="SUCCESS",
            checksum_match="true", transfer_time_s="2", throughput_mbps="4", error_message="")

    def check_rows(self, rows):
        return validate_worker_rows(rows, [("upload", "fixture.bin")],
            client_id="client-01", session_id="session", environment_id="environment",
            num_clients=5, expected_sizes={("upload", "fixture.bin"): 1_000_000})

    def test_valid_row_and_failed_attempt_without_known_size(self):
        self.assertEqual(self.check_rows([self.row]), [])
        row = dict(self.row, status="FAILED", checksum_match="", file_size_bytes="",
                   transfer_time_s="", throughput_mbps="", error_message="source could not be opened")
        self.assertEqual(self.check_rows([row]), [])

    def test_invalid_uuid_or_timezone_is_rejected(self):
        for change in ({"run_id": ""}, {"run_id": "not-a-uuid"},
                       {"timestamp": "2026-11-23T12:00:00"}, {"timestamp": "invalid"}):
            with self.subTest(change=change):
                errors = self.check_rows([dict(self.row, **change)])
                self.assertTrue(any("timestamp" in e for e in errors))

    def test_wrong_size_is_rejected_even_when_mbps_formula_matches(self):
        errors = self.check_rows([dict(self.row, file_size_bytes="1", throughput_mbps="0.000004")])
        self.assertTrue(any("source fixture" in e for e in errors))

    def test_failed_row_requires_reason_and_no_throughput(self):
        errors = self.check_rows([dict(self.row, status="FAILED", checksum_match="false")])
        self.assertTrue(any("error_message" in e for e in errors))
        self.assertTrue(any("must not contain throughput" in e for e in errors))

    def test_missing_or_duplicate_planned_operation_is_rejected(self):
        for rows in ([], [self.row, dict(self.row, run_id=str(uuid4()))]):
            with self.subTest(count=len(rows)):
                self.assertTrue(any("planned transfer" in e for e in self.check_rows(rows)))


if __name__ == "__main__":
    unittest.main()
