"""Collect each host independently, then archive a metadata snapshot per session."""
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
NETWORK_TYPES = ("Wi-Fi", "Ethernet", "loopback", "unknown")
METHOD = ("Client perf_counter: before request through completion response, checksum "
          "verification and download .part rename. Upload source hashing, CSV writing, "
          "metadata and connection setup excluded. No fsync/durable-storage guarantee.")


def collect_host(role, ip="unknown", network_type="unknown", chunk_size_bytes=None):
    if role not in ("client", "server") or network_type not in NETWORK_TYPES:
        raise ValueError("Invalid role or network type")
    ram = None
    try:
        import psutil
        ram = psutil.virtual_memory().total
    except ImportError:
        try:
            ram = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (AttributeError, OSError, ValueError):
            pass
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL).strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = None, None
    cpu = platform.processor()
    if not cpu:
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
    return dict(role=role, collected_at=datetime.now(timezone.utc).isoformat(),
                os=platform.platform(), python_version=platform.python_version(),
                cpu=cpu or "unknown", logical_cpu_count=os.cpu_count(), ram_bytes=ram,
                hardware_scope="OS-visible resources; may describe a container/VM",
                ip=ip, network_type=network_type, chunk_size_bytes=chunk_size_bytes,
                commit_sha=commit, working_tree_dirty=dirty)


def read_host(path, role):
    host = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(host, dict) or host.get("role") != role:
        raise ValueError(f"Expected {role} metadata in {path}")
    return host


def save_environment(client, server=None, port=5000, results_dir=ROOT / "results"):
    environment_id = str(uuid4())
    document = dict(
        environment_id=environment_id, collected_at=datetime.now(timezone.utc).isoformat(),
        client=client, server=server or dict(role="server", os="unknown",
            python_version="unknown", cpu="unknown", logical_cpu_count=None,
            ram_bytes=None, ip="unknown", network_type="unknown", chunk_size_bytes=None),
        port=port, chunk_size_bytes=client.get("chunk_size_bytes"), num_clients=1,
        bandwidth_limit_mbps="unlimited", bytes_per_MB=1_000_000,
        timing_method=METHOD,
    )
    root = Path(results_dir)
    archive = root / "environments" / f"{environment_id}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    archive.write_text(payload, encoding="utf-8")
    (root / "environment.json").write_text(payload, encoding="utf-8")
    return environment_id
