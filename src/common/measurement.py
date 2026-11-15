"""Application completion timing; timestamps and elapsed clocks are separate."""
import math
import time
from datetime import datetime, timezone
from uuid import uuid4


def throughput_mbps(file_size_bytes, transfer_time_s):
    if type(file_size_bytes) is not int or file_size_bytes < 0:
        raise ValueError("file_size_bytes must be a nonnegative integer")
    if (type(transfer_time_s) not in (int, float)
            or not math.isfinite(transfer_time_s) or transfer_time_s <= 0):
        raise ValueError("transfer_time_s must be finite and positive")
    return file_size_bytes * 8 / (transfer_time_s * 1_000_000)


class Measurement:
    def __init__(self, direction, file_name, chunk_size_bytes, environment_id=None):
        self.transfer_start = None
        self.transfer_end = None
        self.row = dict(
            run_id=str(uuid4()), timestamp=datetime.now(timezone.utc).isoformat(),
            direction=direction, file_name=file_name, file_size_bytes=None,
            chunk_size_bytes=chunk_size_bytes, num_clients=1,
            bandwidth_limit_mbps="unlimited", transfer_time_s=None,
            throughput_mbps=None, checksum_match=None, status="FAILED",
            environment_id=environment_id, error_message="",
        )

    def start(self):
        self.row["timestamp"] = datetime.now(timezone.utc).isoformat()
        self.transfer_start = time.perf_counter()

    def finish(self, error=None):
        if self.transfer_start is not None:
            self.transfer_end = time.perf_counter()
            elapsed = self.transfer_end - self.transfer_start
            if math.isfinite(elapsed) and elapsed > 0:
                self.row["transfer_time_s"] = elapsed
        if error is not None:
            self.row["error_message"] = str(error) or type(error).__name__
            return
        if self.row["checksum_match"] is not True:
            raise ValueError("Cannot mark transfer successful without verified checksum")
        self.row["throughput_mbps"] = throughput_mbps(
            self.row["file_size_bytes"], self.row["transfer_time_s"])
        self.row["status"] = "SUCCESS"
