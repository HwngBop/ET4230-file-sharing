"""Append-only single-client CSV logging. Not a multi-process writer."""
import csv
from pathlib import Path

FIELDS = [
    "run_id", "timestamp", "direction", "file_name", "file_size_bytes",
    "chunk_size_bytes", "num_clients", "bandwidth_limit_mbps", "transfer_time_s",
    "throughput_mbps", "checksum_match", "status", "environment_id", "error_message",
]


def append_result(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", newline="", encoding="utf-8") as stream:
        stream.seek(0)
        header = next(csv.reader(stream), None)
        if header is not None and header != FIELDS:
            raise ValueError(f"CSV schema mismatch: {path}; choose a new output file")
        stream.seek(0, 2)
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if header is None:
            writer.writeheader()
        values = {k: (str(v).lower() if type(v) is bool else v) for k, v in row.items()}
        writer.writerow(values)
