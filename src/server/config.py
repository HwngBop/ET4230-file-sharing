"""Load server settings from JSON and command-line overrides."""

import argparse
import json
from dataclasses import dataclass, fields
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 5000
    storage_dir: Path = PROJECT_ROOT / "src/server/storage"
    log_file: Path = PROJECT_ROOT / "logs/server.log"
    chunk_size: int = 65536
    client_timeout: float = 30.0
    max_file_size: int = 1073741824

    def __post_init__(self):
        if not isinstance(self.host, str) or not self.host:
            raise ValueError("host must be a nonempty string")
        for name, minimum, maximum in (
            ("port", 0, 65535),
            ("chunk_size", 1, 1048576),
            ("max_file_size", 0, 2**63 - 1),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
        if (
            type(self.client_timeout) not in (int, float)
            or not 0 < self.client_timeout <= 86400
        ):
            raise ValueError("client_timeout must be between 0 and 86400 seconds")
        for name in ("storage_dir", "log_file"):
            object.__setattr__(self, name, Path(getattr(self, name)).resolve())


def load_config(argv=None):
    parser = argparse.ArgumentParser(description="Sequential TCP file-sharing server")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/server.json")
    parser.add_argument("--host", help="Listening IP address")
    parser.add_argument("--port", type=int, help="Listening TCP port")
    parser.add_argument("--storage-dir", type=Path, help="Directory containing shared files")
    parser.add_argument("--log-file", type=Path, help="JSON Lines log file")
    parser.add_argument("--chunk-size", type=int, help="Transfer buffer size in bytes")
    parser.add_argument("--client-timeout", type=float, help="Socket inactivity timeout in seconds")
    parser.add_argument("--max-file-size", type=int, help="Maximum upload size in bytes")
    args = parser.parse_args(argv)
    try:
        with args.config.open(encoding="utf-8") as stream:
            values = json.load(stream)
        allowed = {field.name for field in fields(ServerConfig)}
        if not isinstance(values, dict) or set(values) - allowed:
            raise ValueError("configuration must be an object containing only known settings")
        for name in ("storage_dir", "log_file"):
            if name in values:
                if not isinstance(values[name], str) or not values[name]:
                    raise ValueError(f"{name} must be a nonempty path string")
                values[name] = args.config.resolve().parent / values[name]
        for name in allowed:
            override = getattr(args, name, None)
            if override is not None:
                values[name] = override
        return ServerConfig(**values)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(f"invalid server configuration: {exc}")
