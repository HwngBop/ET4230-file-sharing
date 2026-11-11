"""Command-line client for the ET4230 TCP file-sharing system (Sprint 1).

From project root: python src/client/client.py
Commands: connect, upload, download, list, quit, help.
"""

import argparse
from contextlib import contextmanager
import hashlib
import re
import socket
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from common.protocol import Connection, PeerDisconnected, ProtocolError  # noqa: E402
from common.measurement import Measurement, throughput_mbps
from common.csv_logger import append_result
from common.environment import collect_host, save_environment

PROJECT_ROOT = SRC_DIR.parent
DOWNLOAD_DIR = PROJECT_ROOT / "client_data" / "downloads"
UPLOAD_DIR = PROJECT_ROOT / "client_data" / "uploads"

DEFAULT_PORT = 5000
SOCKET_TIMEOUT = 30
CHUNK_SIZE = 65536

FATAL_ERROR_CODES = {
    "INVALID_HEADER",
    "HEADER_TOO_LARGE",
    "TIMEOUT",
    "TRANSFER_INCOMPLETE",
    "CONNECTION_OR_IO_ERROR",
}

HELP_TEXT = """Commands:
  connect <ip> [port]   Connect to the server (default port 5000)
  upload <file>         Upload a local file (also looks in client_data/uploads/)
  download <filename>   Download into client_data/downloads/
  list                  List files on the server
  quit                  Disconnect and exit
  help                  Show this help"""


class ClientError(Exception):
    """A problem the user should be told about; the client keeps running."""


class ChecksumMismatch(ClientError):
    """A valid peer checksum differs from the local checksum."""


class ServerError(ClientError):
    """The server answered with status = ERROR."""

    def __init__(self, code, message):
        super().__init__(f"Server error {code}: {message}")
        self.code = code


def format_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def print_result(elapsed, num_bytes):
    # Network throughput: 1 Mbps = 1,000,000 bits/s (not MB/s).
    mbps = throughput_mbps(num_bytes, elapsed)
    print(f"Time: {elapsed:.3f} s, Application throughput: {mbps:.2f} Mbps")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(value, expected):
    """Raise ClientError if the server's checksum is absent/invalid/mismatched."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ClientError("Server did not return a valid SHA-256 checksum")
    if value.lower() != expected:
        raise ChecksumMismatch("CHECKSUM_MISMATCH: received file bytes differ from expected SHA-256")


class FileClient:
    def __init__(self, csv_path=PROJECT_ROOT / "results/raw/baseline.csv",
                 environment_id=None, chunk_size=CHUNK_SIZE, download_dir=None,
                 auto_environment=True, results_dir=PROJECT_ROOT / "results"):
        if type(chunk_size) is not int or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        self.sock = None
        self.conn = None
        self.csv_path = Path(csv_path)
        self.environment_id = environment_id
        self.chunk_size = chunk_size
        self.download_dir = Path(download_dir) if download_dir else DOWNLOAD_DIR
        self.auto_environment = auto_environment
        self._provided_environment = environment_id is not None
        self.results_dir = Path(results_dir)
        self.last_result = None

    @contextmanager
    def measured_transfer(self, direction, filename):
        measurement = Measurement(direction, str(filename), self.chunk_size, self.environment_id)
        self.last_result = measurement.row
        try:
            yield measurement
            measurement.finish()
        except BaseException as exc:
            # A missing/malformed checksum remains unknown, not a mismatch.
            if isinstance(exc, ChecksumMismatch) or getattr(exc, "code", None) == "CHECKSUM_MISMATCH":
                measurement.row["checksum_match"] = False
            measurement.finish(exc)
            if (measurement.transfer_start is not None
                    and not (isinstance(exc, ServerError) and exc.code not in FATAL_ERROR_CODES)):
                self.drop()
            raise
        finally:
            try:
                append_result(self.csv_path, measurement.row)
            except (OSError, ValueError, TypeError) as exc:
                raise ClientError(f"CSV LOGGING FAILED ({self.csv_path}): {exc}") from exc
        print("Transfer completed; SHA-256 MATCH.")
        print_result(measurement.row["transfer_time_s"], measurement.row["file_size_bytes"])
        print(f"run_id: {measurement.row['run_id']}; CSV: {self.csv_path}")

    @property
    def connected(self):
        return self.sock is not None

    def connect(self, host, port):
        if self.connected:
            raise ClientError("Already connected. Use 'quit' to disconnect first.")
        try:
            sock = socket.create_connection((host, port), timeout=SOCKET_TIMEOUT)
        except socket.gaierror:
            raise ClientError(f"Invalid or unknown server address: {host}")
        except socket.timeout:
            raise ClientError(f"Server not reachable: connection to {host}:{port} timed out")
        except ConnectionRefusedError:
            raise ClientError(f"Server not reachable: {host}:{port} refused the connection")
        except OSError as exc:
            raise ClientError(f"Server not reachable: {exc}")
        sock.settimeout(SOCKET_TIMEOUT)
        self.sock = sock
        self.conn = Connection(sock)
        try:
            if self.auto_environment and not self._provided_environment:
                client = collect_host("client", sock.getsockname()[0], chunk_size_bytes=self.chunk_size)
                server = dict(role="server", ip=sock.getpeername()[0], os="unknown",
                              python_version="unknown", cpu="unknown", ram_bytes=None,
                              logical_cpu_count=None, network_type="unknown", chunk_size_bytes=None)
                self.environment_id = save_environment(client, server, port, self.results_dir)
        except (OSError, ValueError):
            self.drop()
            raise
        print("Connected to server.")

    def drop(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.conn = None

    def require_connection(self):
        if not self.connected:
            raise ClientError("Not connected. Use: connect <ip> [port]")

    def read_response(self):
        """Read one bounded response JSON header; raise ServerError on ERROR."""
        header = self.conn.receive_header()  # Enforce MAX_HEADER_BYTES (no unbounded reads)
        if header is None:
            raise PeerDisconnected("Server closed the connection")
        if header.get("status") == "ERROR":
            code = header.get("code", "UNKNOWN")
            message = header.get("message", "")
            if code in FATAL_ERROR_CODES:
                self.drop()
            raise ServerError(code, message)
        return header

    @staticmethod
    def expect(header, status, command):
        if header.get("status") != status or header.get("command") != command:
            raise ProtocolError("INVALID_HEADER", f"Unexpected response (wanted {status}/{command}): {header}")

    def list_files(self):
        self.require_connection()
        self.conn.send_header({"command": "LIST"})
        header = self.read_response()
        self.expect(header, "OK", "LIST")
        files = header.get("files", [])
        if not isinstance(files, list) or any(not isinstance(f, str) for f in files):
            raise ProtocolError("INVALID_HEADER", "LIST must return a list of filenames")
        if not files:
            print("Server has no files.")
        else:
            print(f"Files on server ({len(files)}):")
            for name in files:
                print(f"  {name}")

    def upload(self, raw_path):
        with self.measured_transfer("upload", Path(raw_path).name) as measurement:
            self._upload(raw_path, measurement)
        return self.last_result

    def _upload(self, raw_path, measurement):
        self.require_connection()
        path = self.find_local_file(raw_path)
        file_size = path.stat().st_size
        filename = path.name
        measurement.row.update(file_name=filename, file_size_bytes=file_size)
        source_sha256 = sha256_file(path)
        print(f"Uploading {filename}")
        print(f"Size: {format_size(file_size)}")

        measurement.start()
        self.conn.send_header({
            "command": "UPLOAD", "filename": filename,
            "file_size": file_size, "sha256": source_sha256,
        })
        self.expect(self.read_response(), "READY", "UPLOAD")

        sent = 0
        with open(path, "rb") as stream:
            while sent < file_size:
                chunk = stream.read(min(self.chunk_size, file_size - sent))
                if not chunk:
                    self.drop()
                    raise ClientError("Local file changed during upload. Connection closed.")
                self.sock.sendall(chunk)
                sent += len(chunk)

        confirmation = self.read_response()
        self.expect(confirmation, "SUCCESS", "UPLOAD")
        try:
            verify_checksum(confirmation.get("sha256"), source_sha256)
        except ClientError:
            self.drop()
            raise
        measurement.row["checksum_match"] = True

    def download(self, filename):
        with self.measured_transfer("download", filename) as measurement:
            self._download(filename, measurement)
        return self.last_result

    def _download(self, filename, measurement):
        self.require_connection()
        if not filename or Path(filename).name != filename or filename in (".", ".."):
            raise ClientError("Invalid filename: give only a file name, without a path.")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        target = self.download_dir / filename
        partial = self.download_dir / (filename + ".part")

        print(f"Downloading {filename}")
        measurement.start()
        self.conn.send_header({"command": "DOWNLOAD", "filename": filename})
        header = self.read_response()
        self.expect(header, "OK", "DOWNLOAD")
        file_size = header.get("file_size")
        if type(file_size) is not int or file_size < 0:
            self.drop()
            raise ClientError("Server sent an invalid file_size. Connection closed.")
        measurement.row["file_size_bytes"] = file_size

        try:
            received = 0
            digest = hashlib.sha256()
            with open(partial, "wb") as stream:
                while received < file_size:
                    chunk = self.conn.receive_chunk(min(self.chunk_size, file_size - received))
                    written = stream.write(chunk)
                    if written != len(chunk):
                        raise OSError("Short write while saving downloaded file")
                    digest.update(chunk)
                    received += written
            confirmation = self.read_response()
            self.expect(confirmation, "SUCCESS", "DOWNLOAD")
            verify_checksum(confirmation.get("sha256"), digest.hexdigest())
            measurement.row["checksum_match"] = True
            partial.replace(target)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise


    def quit(self):
        if not self.connected:
            return
        try:
            self.conn.send_header({"command": "QUIT"})
            header = self.read_response()
            self.expect(header, "OK", "QUIT")
            print("Disconnected from server.")
        except (ClientError, ProtocolError, PeerDisconnected, OSError):
            print("Connection closed (server did not confirm QUIT).")
        finally:
            self.drop()

    @staticmethod
    def find_local_file(raw_path):
        if not raw_path:
            raise ClientError("Usage: upload <file>")
        candidates = [Path(raw_path).expanduser(), UPLOAD_DIR / raw_path]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise ClientError(f"Local file does not exist: {raw_path}")


def unquote(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text


def handle_command(client, line):
    parts = line.strip().split(None, 1)
    if not parts:
        return True
    command = parts[0].lower()
    argument = unquote(parts[1]) if len(parts) > 1 else ""

    if command == "help":
        print(HELP_TEXT)
    elif command == "connect":
        args = argument.split()
        if not args or len(args) > 2:
            raise ClientError("Usage: connect <ip> [port]")
        port = DEFAULT_PORT
        if len(args) == 2:
            if not args[1].isdigit() or not 1 <= int(args[1]) <= 65535:
                raise ClientError("Port must be a number between 1 and 65535.")
            port = int(args[1])
        client.connect(args[0], port)
    elif command == "upload":
        client.upload(argument)
    elif command == "download":
        if not argument:
            raise ClientError("Usage: download <filename>")
        client.download(argument)
    elif command == "list":
        client.list_files()
    elif command in ("quit", "exit"):
        client.quit()
        return False
    else:
        raise ClientError(f"Invalid command: {command}. Type 'help' for the list of commands.")
    return True


def run_safely(client, line):
    try:
        return handle_command(client, line)
    except ServerError as exc:
        print(f"Error: {exc}")
    except ClientError as exc:
        print(f"Error: {exc}")
    except socket.timeout:
        client.drop()
        print("Error: Server did not respond in time. Connection closed.")
    except PeerDisconnected as exc:
        client.drop()
        print(f"Error: {exc}. Connection closed.")
    except ProtocolError as exc:
        client.drop()
        print(f"Error: Protocol violation from server ({exc}). Connection closed.")
    except OSError as exc:
        client.drop()
        print(f"Error: Connection or file problem ({exc}). Connection closed.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=PROJECT_ROOT / "results/raw/baseline.csv")
    parser.add_argument("--environment", type=Path, help="Existing merged environment JSON")
    args = parser.parse_args()
    environment_id = None
    if args.environment:
        import json
        try:
            document = json.loads(args.environment.read_text(encoding="utf-8"))
            environment_id = document["environment_id"]
            if document.get("chunk_size_bytes") != CHUNK_SIZE:
                raise ValueError("Environment chunk_size_bytes differs from client")
        except (OSError, ValueError, KeyError) as exc:
            parser.error(f"Invalid environment: {exc}")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    client = FileClient(csv_path=args.csv, environment_id=environment_id)
    print("ET4230 File Sharing Client. Type 'help' for commands.")
    try:
        while True:
            try:
                line = input("> ")
            except EOFError:
                client.quit()
                break
            if not run_safely(client, line):
                break
    except KeyboardInterrupt:
        print()
        client.quit()
    finally:
        client.drop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
