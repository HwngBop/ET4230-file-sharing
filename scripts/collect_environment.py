"""Export local host metadata; run separately on client and server."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from common.environment import NETWORK_TYPES, collect_host, read_host, save_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("--role", choices=("client", "server"), required=True)
    collect.add_argument("--ip", default="unknown")
    collect.add_argument("--network-type", choices=NETWORK_TYPES, default="unknown")
    collect.add_argument("--chunk-size", type=int, default=65536)
    collect.add_argument("--output", type=Path, required=True)
    merge = commands.add_parser("merge")
    merge.add_argument("--client", type=Path, required=True)
    merge.add_argument("--server", type=Path, required=True)
    merge.add_argument("--port", type=int, default=5000)
    merge.add_argument("--results-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    try:
        if args.command == "collect":
            if args.chunk_size <= 0:
                raise ValueError("chunk-size must be positive")
            host = collect_host(args.role, args.ip, args.network_type, args.chunk_size)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(host, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(args.output)
        else:
            print(save_environment(read_host(args.client, "client"),
                                   read_host(args.server, "server"), args.port, args.results_dir))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Metadata error: {exc}\n")


if __name__ == "__main__":
    main()
