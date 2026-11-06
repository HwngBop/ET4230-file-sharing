"""Command-line client for the ET4230 file sharing server (Sprint 1).

Run from the project root:
    python src/client/client.py
or:
    cd src && python -m client.client

Commands: connect, upload, download, list, quit (plus help).
"""

import socket
import sys
import time
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from common.protocol import Connection, PeerDisconnected, ProtocolError  # noqa: E402

PROJECT_ROOT = SRC_DIR.parent
DOWNLOAD_DIR = PROJECT_ROOT / "client_data" / "downloads"
UPLOAD_DIR = PROJECT_ROOT / "client_data" / "uploads"

DEFAULT_PORT = 5000
SOCKET_TIMEOUT = 30
CHUNK_SIZE = 65536

# Per protocol.md, the server closes the connection after these errors.
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
  download <filename>   Download a file into client_data/downloads/
  list                  List files on the server
  quit                  Disconnect and exit
  help                  Show this help"""


class ClientError(Exception):
    """A problem the user should be told about; the client keeps running."""


class ServerError(ClientError):
    """The server answered with status = ERROR."""

    def __init__(self, code, message):
        super().__init__(f"Server error {code}: {message}")
        self.code = code


def format_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def print_result(elapsed, num_bytes):
    speed = num_bytes / elapsed / (1024 * 1024) if elapsed > 0 else 0.0
    print(f"Time: {elapsed:.2f} s, Speed: {speed:.2f} MB/s")


class FileClient:
    def __init__(self):
        self.sock = None
        self.conn = None

    @property
    def connected(self):
        return self.sock is not None

    # ---------- connection handling ----------

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
        print("Connected to server.")

    def drop(self):
        """Close the socket without talking to the server."""
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
        """Read one response header; raise ServerError for status = ERROR."""
        header = self.conn.receive_header(max_bytes=None)
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
            raise ProtocolError(
                "INVALID_HEADER",
                f"Unexpected response (wanted {status}/{command}): {header}",
            )

    # ---------- commands ----------

    def list_files(self):
        self.require_connection()
        self.conn.send_header({"command": "LIST"})
        header = self.read_response()
        self.expect(header, "OK", "LIST")
        files = header.get("files", [])
        if not files:
            print("Server has no files.")
        else:
            print(f"Files on server ({len(files)}):")
            for name in files:
                print(f"  {name}")

    def upload(self, raw_path):
        self.require_connection()
        path = self.find_local_file(raw_path)
        file_size = path.stat().st_size
        filename = path.name
        print(f"Uploading {filename}")
        print(f"Size: {format_size(file_size)}")

        start = time.perf_counter()
        self.conn.send_header({"command": "UPLOAD", "filename": filename, "file_size": file_size})
        self.expect(self.read_response(), "READY", "UPLOAD")

        sent = 0
        with open(path, "rb") as stream:
            while sent < file_size:
                chunk = stream.read(min(CHUNK_SIZE, file_size - sent))
                if not chunk:
                    # File shrank while uploading; the server is waiting for more bytes.
                    self.drop()
                    raise ClientError("Local file changed during upload. Connection closed.")
                self.sock.sendall(chunk)
                sent += len(chunk)

        self.expect(self.read_response(), "SUCCESS", "UPLOAD")
        print("Transfer completed.")
        print_result(time.perf_counter() - start, file_size)

    def download(self, filename):
        self.require_connection()
        if not filename or Path(filename).name != filename or filename in (".", ".."):
            raise ClientError("Invalid filename: give only a file name, without a path.")
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        target = DOWNLOAD_DIR / filename
        partial = DOWNLOAD_DIR / (filename + ".part")

        print(f"Downloading {filename}")
        start = time.perf_counter()
        self.conn.send_header({"command": "DOWNLOAD", "filename": filename})
        header = self.read_response()  # FILE_NOT_FOUND etc. raise ServerError here
        self.expect(header, "OK", "DOWNLOAD")
        file_size = header.get("file_size")
        if type(file_size) is not int or file_size < 0:
            self.drop()
            raise ClientError("Server sent an invalid file_size. Connection closed.")
        print(f"Size: {format_size(file_size)}")

        try:
            received = 0
            with open(partial, "wb") as stream:
                while received < file_size:
                    chunk = self.conn.receive_chunk(min(CHUNK_SIZE, file_size - received))
                    stream.write(chunk)
                    received += len(chunk)
            self.expect(self.read_response(), "SUCCESS", "DOWNLOAD")
            partial.replace(target)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise

        print("Transfer completed.")
        print(f"Saved to: {target}")
        print_result(time.perf_counter() - start, file_size)

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

    # ---------- helpers ----------

    @staticmethod
    def find_local_file(raw_path):
        if not raw_path:
            raise ClientError("Usage: upload <file>")
        candidates = [Path(raw_path).expanduser(), UPLOAD_DIR / raw_path]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        raise ClientError(f"Local file does not exist: {raw_path}")


# ---------- CLI ----------

def unquote(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text


def handle_command(client, line):
    """Run one command line. Return False when the program should exit."""
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
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    client = FileClient()
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
