"""Concurrent transfer acceptance runner. Each worker owns one socket and CSV."""
import argparse
import csv
import hashlib
import ipaddress
import json
import math
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from client.client import FileClient
from common.csv_logger import CONCURRENT_FIELDS
from common.environment import NETWORK_TYPES, collect_host, read_host


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_worker_rows(rows, expected_pairs, *, client_id, session_id,
                         environment_id, num_clients):
    """Reject CSVs that could otherwise hide a client integration mismatch."""
    errors = []
    pairs = [(row.get("direction"), row.get("file_name")) for row in rows]
    if len(pairs) != len(expected_pairs) or set(pairs) != set(expected_pairs):
        errors.append("Missing or duplicate planned transfer")
    for row in rows:
        expected = {"client_id": client_id, "session_id": session_id,
                    "environment_id": environment_id, "num_clients": str(num_clients),
                    "chunk_size_bytes": "65536"}
        if any(row.get(key) != value for key, value in expected.items()):
            errors.append("CSV client/session/environment/configuration mismatch")
        status = row.get("status")
        if status == "SUCCESS":
            try:
                size = int(row["file_size_bytes"])
                elapsed = float(row["transfer_time_s"])
                rate = float(row["throughput_mbps"])
                calculated = size * 8 / (elapsed * 1_000_000)
                valid = (size >= 0 and elapsed > 0 and math.isfinite(elapsed)
                         and math.isfinite(rate) and rate >= 0
                         and math.isclose(rate, calculated, rel_tol=1e-12, abs_tol=1e-12))
            except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
                valid = False
            if row.get("checksum_match") != "true" or not valid:
                errors.append("SUCCESS row lacks verified checksum or valid Mbps metric")
        elif status == "FAILED":
            if row.get("throughput_mbps") not in (None, ""):
                errors.append("FAILED row must not contain throughput")
        else:
            errors.append("Unknown transfer status")
    return sorted(set(errors))


class ReadyGate:
    """Prove dispatch overlap: all READY responses before any first payload."""
    def __init__(self, count, timeout):
        self.barrier = threading.Barrier(count)
        self.timeout = timeout
        self.lock = threading.Lock()
        self.ready = {}
        self.released = {}
        self.broken = False

    def wait(self, client_id):
        with self.lock:
            self.ready[client_id] = time.perf_counter()
        try:
            self.barrier.wait(self.timeout)
        except threading.BrokenBarrierError:
            with self.lock:
                self.broken = True
        with self.lock:
            self.released[client_id] = time.perf_counter()

    def abort(self):
        self.barrier.abort()
        with self.lock:
            self.broken = True

    def evidence(self, workers, count):
        first = {w["client_id"]: next((e for e in w["transfers"]
                 if e["direction"] == "upload"), None) for w in workers}
        first_ok = all(e and e["status"] == "SUCCESS" for e in first.values())
        ends = [e["transfer_end_s"] for e in first.values() if e and e["transfer_end_s"] is not None]
        ready = dict(self.ready)
        release = dict(self.released)
        complete = len(ready) == count and len(release) == count and len(ends) == count
        # First-upload intervals after READY through completion overlap for all workers.
        overlap_s = max(0.0, min(ends) - max(ready.values())) if complete else 0.0
        all_ready_before_payload = complete and max(ready.values()) <= min(release.values())
        payload_overlap_s = max(0.0, min(ends) - max(release.values())) if complete else 0.0
        passed = (first_ok and not self.broken and all_ready_before_payload
                  and overlap_s > 0 and payload_overlap_s > 0)
        return dict(status="PASS" if passed else "FAIL", applicable=count > 1,
                    method="first upload: READY-to-completion overlap and all READY before first payload",
                    all_ready_before_payload=all_ready_before_payload,
                    shared_processing_overlap_s=overlap_s,
                    shared_payload_completion_overlap_s=payload_overlap_s,
                    ready_gate_broken=self.broken,
                    ready_times_s=ready, payload_release_times_s=release,
                    clock="perf_counter on one runner process; not comparable across hosts",
                    note="Demonstrates concurrent application dispatch/waiting, not parallel CPU execution or wire-level packet overlap.")


class WorkerClient(FileClient):
    def __init__(self, *, gate, **kwargs):
        super().__init__(**kwargs)
        self.gate = gate
        self.first_ready = True
        self.transfers = []

    def read_response(self):
        header = super().read_response()
        if self.first_ready and header.get("status") == "READY" and header.get("command") == "UPLOAD":
            self.first_ready = False
            self.gate.wait(self.client_id)
        return header

    @contextmanager
    def measured_transfer(self, direction, filename):
        measurement = None
        try:
            with super().measured_transfer(direction, filename) as measurement:
                yield measurement
        finally:
            if measurement is not None:
                self.transfers.append(dict(
                    run_id=measurement.row["run_id"], direction=direction,
                    status=measurement.row["status"],
                    transfer_start_s=measurement.transfer_start,
                    transfer_end_s=measurement.transfer_end,
                ))

    def failed_attempt(self, direction, name, size, error):
        try:
            with self.measured_transfer(direction, name) as measurement:
                measurement.row["file_size_bytes"] = size
                raise RuntimeError(error)
        except RuntimeError:
            pass


def run_scenario(host, port=5000, num_clients=5, files_dir=ROOT / "client_data/uploads",
                 results_dir=ROOT / "results/sprint2", download=False,
                 server_metadata=None, network_type="unknown", timeout=30.0,
                 sync_timeout=5.0, client_factory=WorkerClient):
    """Return an exit code and summary; never writes Sprint 1 paths."""
    ipaddress.IPv4Address(host)
    if type(num_clients) is not int or not 1 <= num_clients <= 100:
        raise ValueError("num_clients must be between 1 and 100 (presets: 1, 5, 10)")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if not 0 < sync_timeout < timeout <= 86400:
        raise ValueError("Require 0 < sync_timeout < timeout <= 86400")
    if network_type not in NETWORK_TYPES:
        raise ValueError("Unknown network type")
    files = sorted(Path(files_dir).resolve().glob("*.bin"))
    if not files or any(not p.is_file() or p.stat().st_size == 0 for p in files):
        raise ValueError("files-dir must contain nonempty .bin files")
    source_sizes = {p.name: p.stat().st_size for p in files}
    if any(len(p.name.encode("utf-8")) > 180 for p in files):
        raise ValueError("Fixture names must be at most 180 UTF-8 bytes")
    if server_metadata:
        server = read_host(server_metadata, "server")
        if server.get("chunk_size_bytes") != 65536:
            raise ValueError("Server metadata must record chunk_size_bytes=65536")
        if server.get("ip") not in (None, "unknown", host):
            raise ValueError("Server metadata IP differs from --host")
    else:
        server = {"role": "server", "ip": host, "os": "unknown", "python_version": "unknown",
                  "cpu": "unknown", "ram_bytes": None, "network_type": "unknown",
                  "chunk_size_bytes": None, "commit_sha": None}
    session_id = str(uuid4())
    environment_id = str(uuid4())
    run_dir = Path(results_dir).resolve() / session_id
    run_dir.mkdir(parents=True, exist_ok=False)
    environment = dict(
        environment_id=environment_id, session_id=session_id,
        collected_at=datetime.now(timezone.utc).isoformat(),
        client=collect_host("client", "unknown", network_type, 65536), server=server,
        num_clients=num_clients, host=host, port=port, chunk_size_bytes=65536,
        bandwidth_limit_mbps="unlimited", bytes_per_MB=1_000_000,
        timing_method="Sprint 1 request-to-completion timing; first upload INCLUDES READY gate wait. Not an unmodified Sprint 1 performance baseline.",
        concurrency_method="All first-upload READY replies before payload release; READY-to-completion intervals must overlap.",
        timeout_s=timeout, sync_timeout_s=sync_timeout,
        same_host=network_type == "loopback" and ipaddress.ip_address(host).is_loopback,
        server_metadata_complete=bool(server_metadata),
        source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in [Path(__file__), ROOT / "src/client/client.py",
                                 ROOT / "src/common/measurement.py", ROOT / "src/common/csv_logger.py"]},
        source_files=[dict(file_name=p.name, file_size_bytes=source_sizes[p.name]) for p in files],
    )
    write_json(run_dir / "environment.json", environment)
    start = threading.Barrier(num_clients)
    gate = ReadyGate(num_clients, sync_timeout)

    def worker(index):
        client_id = f"client-{index:02d}"
        directory = run_dir / client_id
        directory.mkdir()
        csv_path = directory / "transfers.csv"
        client = client_factory(gate=gate, csv_path=csv_path, environment_id=environment_id,
            num_clients=num_clients, client_id=client_id, session_id=session_id,
            csv_fields=CONCURRENT_FIELDS, socket_timeout=timeout,
            download_dir=directory / "downloads", auto_environment=False)
        result = dict(client_id=client_id, session_id=session_id, status="FAIL", errors=[],
                      expected_rows=len(files) * (2 if download else 1),
                      local_address=None, server_address=None, transfers=[])
        setup_error = None
        try:
            uploads = directory / "uploads"
            uploads.mkdir()
            for source in files:
                name = f"s2_{session_id}_{client_id}_{source.name}"
                target = uploads / name
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copyfile(source, target)
            client.connect(host, port)
            result["local_address"] = list(client.sock.getsockname())
            result["server_address"] = list(client.sock.getpeername())
        except Exception as exc:
            setup_error = str(exc)
            result["errors"].append(setup_error)
        try:
            # Even a setup failure participates, so healthy workers are not stranded.
            try:
                start.wait(sync_timeout)
            except threading.BrokenBarrierError:
                result["errors"].append("Start barrier timed out")
                gate.abort()
            if setup_error:
                gate.abort()
            for source in files:
                name = f"s2_{session_id}_{client_id}_{source.name}"
                target = directory / "uploads" / name
                size = source_sizes[source.name]
                uploaded = False
                try:
                    if setup_error:
                        client.failed_attempt("upload", name, size, setup_error)
                    else:
                        client.upload(str(target))
                        uploaded = True
                except Exception as exc:
                    gate.abort()
                    result["errors"].append(str(exc))
                if download:
                    try:
                        if uploaded:
                            client.download(name)
                        else:
                            client.failed_attempt("download", name, size, "Skipped: upload did not succeed")
                    except Exception as exc:
                        result["errors"].append(str(exc))
        except Exception as exc:
            result["errors"].append(str(exc))
            gate.abort()
        finally:
            client.quit()
            result["transfers"] = client.transfers
        try:
            with csv_path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                rows = list(reader)
                if reader.fieldnames != CONCURRENT_FIELDS:
                    raise ValueError("Unexpected worker CSV schema")
            expected_pairs = [(direction, f"s2_{session_id}_{client_id}_{source.name}")
                              for source in files
                              for direction in (("upload", "download") if download else ("upload",))]
            result["errors"].extend(validate_worker_rows(rows, expected_pairs,
                client_id=client_id, session_id=session_id,
                environment_id=environment_id, num_clients=num_clients))
            result["row_count"] = len(rows)
            result["successful_transfers"] = sum(r["status"] == "SUCCESS" and r["checksum_match"] == "true" for r in rows)
            if len(rows) != result["expected_rows"]:
                result["errors"].append("Unexpected worker CSV row count")
            if any(r["status"] != "SUCCESS" or r["checksum_match"] != "true" for r in rows):
                result["errors"].append("One or more transfers failed")
            result["status"] = "PASS" if not result["errors"] else "FAIL"
        except (OSError, ValueError) as exc:
            result["errors"].append(f"CSV validation failed: {exc}")
        write_json(directory / "worker-result.json", result)
        return result

    workers = []
    with ThreadPoolExecutor(max_workers=num_clients) as pool:
        futures = {pool.submit(worker, index): index for index in range(1, num_clients + 1)}
        for future in as_completed(futures):
            try:
                workers.append(future.result())
            except Exception as exc:
                gate.abort()
                workers.append(dict(client_id=f"client-{futures[future]:02d}", status="FAIL",
                                    errors=[str(exc)], transfers=[]))
    workers.sort(key=lambda w: w["client_id"])
    addresses = [w["local_address"] for w in workers if w.get("local_address")]
    environment["client_socket_addresses"] = addresses
    client_ips = {address[0] for address in addresses}
    if len(client_ips) == 1:
        environment["client"]["ip"] = next(iter(client_ips))
    write_json(run_dir / "environment.json", environment)
    evidence = gate.evidence(workers, num_clients)
    merged = run_dir / "all-transfers.csv"
    errors = []
    all_rows = []
    for worker_result in workers:
        try:
            with (run_dir / worker_result["client_id"] / "transfers.csv").open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames != CONCURRENT_FIELDS:
                    raise ValueError("Unexpected worker schema")
                all_rows.extend(reader)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    expected = num_clients * len(files) * (2 if download else 1)
    if len(all_rows) != expected or len({row["run_id"] for row in all_rows}) != len(all_rows):
        errors.append("Missing or duplicate transfer rows")
    with merged.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CONCURRENT_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    passed = not errors and all(w["status"] == "PASS" for w in workers) and evidence["status"] == "PASS"
    summary = dict(session_id=session_id, environment_id=environment_id,
                   status="PASS" if passed else "FAIL", num_clients=num_clients,
                   expected_rows=expected, actual_rows=len(all_rows), errors=errors,
                   concurrency=evidence, workers=workers)
    write_json(run_dir / "summary.json", summary)
    (run_dir / "runner.log").write_text(
        "\n".join([f"{w['client_id']}: {w['status']}" for w in workers]
                  + [f"concurrency: {evidence['status']}", f"scenario: {summary['status']}"]) + "\n", encoding="utf-8")
    print(f"Scenario {summary['status']}; results: {run_dir}")
    return (0 if passed else 1), summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Server IPv4 (127.0.0.1 for loopback)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--num-clients", type=int, choices=(1, 5, 10), default=5)
    parser.add_argument("--files-dir", type=Path, default=ROOT / "client_data/uploads")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results/sprint2")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--server-metadata", type=Path)
    parser.add_argument("--network-type", choices=NETWORK_TYPES, default="unknown")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--sync-timeout", type=float, default=5)
    args = parser.parse_args(argv)
    try:
        code, _ = run_scenario(host=args.host, port=args.port, num_clients=args.num_clients,
            files_dir=args.files_dir, results_dir=args.results_dir, download=args.download,
            server_metadata=args.server_metadata, network_type=args.network_type,
            timeout=args.timeout, sync_timeout=args.sync_timeout)
        return code
    except (OSError, ValueError) as exc:
        print(f"Runner error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
