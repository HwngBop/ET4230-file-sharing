"""Sequential Sprint 1 baseline using the project's FileClient."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from client.client import FileClient
from common.environment import NETWORK_TYPES, collect_host, read_host, save_environment
from generate_test_files import SIZES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--files-dir", type=Path, default=ROOT / "client_data/uploads")
    parser.add_argument("--csv", type=Path, default=ROOT / "results/raw/baseline.csv")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--server-metadata", type=Path,
                        help="JSON exported ON the actual server")
    parser.add_argument("--network-type", choices=NETWORK_TYPES, default="unknown")
    parser.add_argument("--download", action="store_true", help="Also download each uploaded file")
    args = parser.parse_args()
    client = FileClient(csv_path=args.csv, auto_environment=False)
    failed = False
    try:
        paths = [args.files_dir / f"test_{size // 1_000_000}MB.bin" for size in SIZES]
        for path, size in zip(paths, SIZES):
            if path.stat().st_size != size:
                raise ValueError(f"Wrong file size: {path}; expected {size}")
        if not args.server_metadata:
            raise ValueError("Export server metadata first and pass --server-metadata (also for localhost)")
        server = read_host(args.server_metadata, "server")
        if server.get("chunk_size_bytes") != 65536:
            raise ValueError("Server metadata must record chunk_size_bytes=65536; run server with this setting")
        client.connect(args.host, args.port)
        actual_server_ip = client.sock.getpeername()[0]
        declared_ip = server.get("ip")
        if declared_ip not in ("unknown", actual_server_ip):
            raise ValueError(f"Server metadata IP {declared_ip} differs from connected peer {actual_server_ip}")
        server["ip"] = actual_server_ip
        host = collect_host("client", client.sock.getsockname()[0], args.network_type, 65536)
        client.environment_id = save_environment(host, server, args.port, args.results_dir)
        print(f"Environment: {client.environment_id}; CSV: {args.csv}")
        for path in paths:
            if not client.connected:
                client.connect(args.host, args.port)
            try:
                client.upload(str(path))
                if args.download:
                    client.download(path.name)
            except Exception as exc:
                failed = True
                print(f"FAILED {path.name}: {exc}", file=sys.stderr)
        return 1 if failed else 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Baseline error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Baseline error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.quit()


if __name__ == "__main__":
    raise SystemExit(main())
