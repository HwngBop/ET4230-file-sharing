"""A bounded thread-per-connection TCP server supporting concurrent clients."""

from contextlib import contextmanager
import hashlib
import logging
import os
import re
import socket
import sys
import threading
from pathlib import Path

from common.protocol import Connection, PeerDisconnected, ProtocolError

from .config import load_config
from .logging_config import configure_logging
from .storage import FileStorage


class FileServer:
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger if logger is not None else logging.getLogger("file_server")
        self.storage = FileStorage(config.storage_dir)
        self.listener = None
        self.client = None
        self.stopping = False
        self._lock = threading.Lock()
        self._connection_seq = 0
        self._active_clients = {}
        self._workers = {}

    @property
    def address(self):
        if self.listener is None:
            raise RuntimeError("Server is not listening")
        return self.listener.getsockname()

    @property
    def active_client_count(self):
        with self._lock:
            return len(self._active_clients)

    @property
    def active_workers(self):
        with self._lock:
            return [worker for worker in self._workers.values() if worker.is_alive()]

    @property
    def active_sockets(self):
        with self._lock:
            return list(self._active_clients.values())

    def _next_connection_id(self):
        with self._lock:
            self._connection_seq += 1
            return f"conn-{self._connection_seq}"

    def start(self):
        if self.listener is not None:
            raise RuntimeError("Server is already listening")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.config.host, self.config.port))
            listener.listen(max(16, self.config.max_clients * 2))
            listener.settimeout(0.5)
        except BaseException:
            listener.close()
            raise
        self.listener = listener
        self.stopping = False
        self._log({}, "LISTENING", f"Listening on {self.address[0]}:{self.address[1]}")

    def serve_forever(self):
        if self.listener is None:
            self.start()
        listener = self.listener
        try:
            while not self.stopping:
                try:
                    client, address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self.stopping:
                        break
                    raise
                self._accept_client(client, address)
        finally:
            self.close()

    def _accept_client(self, client, address):
        with self._lock:
            self._connection_seq += 1
            connection_id = f"conn-{self._connection_seq}"
            if self.stopping:
                try:
                    client.close()
                except OSError:
                    pass
                return
            if len(self._active_clients) >= self.config.max_clients:
                busy = True
                worker = None
            else:
                busy = False
                self._active_clients[connection_id] = client
                worker = threading.Thread(
                    target=self._client_worker,
                    args=(client, address, connection_id),
                    name=f"client-worker-{connection_id}",
                    daemon=True,
                )
                self._workers[connection_id] = worker
        if busy:
            self._reject_busy_client(client, address, connection_id)
            return
        try:
            worker.start()
        except BaseException:
            with self._lock:
                self._active_clients.pop(connection_id, None)
                self._workers.pop(connection_id, None)
            try:
                client.close()
            except OSError:
                pass
            raise

    def _reject_busy_client(self, client, address, connection_id):
        peer = {
            "connection_id": connection_id,
            "client_ip": address[0],
            "client_port": address[1],
        }
        try:
            client.settimeout(0.2)
            connection = Connection(client)
            self._send_error(
                connection,
                "SERVER_BUSY",
                "Server has reached max_clients limit",
            )
            try:
                client.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            try:
                client.settimeout(0.05)
                client.recv(4096)
            except OSError:
                pass
        except OSError:
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass
            self._log(
                {**peer, "command": "CONNECT"},
                "SERVER_BUSY",
                "Connection rejected: server reached max_clients limit",
            )

    def _client_worker(self, client, address, connection_id):
        try:
            with client:
                client.settimeout(self.config.client_timeout)
                self._handle_client(client, address, connection_id)
        except OSError:
            pass
        finally:
            with self._lock:
                self._active_clients.pop(connection_id, None)
                self._workers.pop(connection_id, None)

    def close(self):
        self.stopping = True
        listener = self.listener
        self.listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        with self._lock:
            clients = list(self._active_clients.values())
            workers = list(self._workers.values())
            legacy_client = self.client
            self.client = None
        if legacy_client is not None and legacy_client not in clients:
            clients.append(legacy_client)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
        current = threading.current_thread()
        for worker in workers:
            if worker is not current and worker.is_alive():
                worker.join(timeout=5.0)

    @contextmanager
    def _acquire_file_lock(self, filename):
        try_lock_file = getattr(self.storage, "try_lock_file", None)
        if try_lock_file is None:
            yield
            return
        with try_lock_file(filename) as acquired:
            if not acquired:
                raise ProtocolError("FILE_BUSY", "File is currently in use", fatal=False)
            yield

    def _log(self, context, status, message):
        self.logger.info(
            message,
            extra={"event": {"connection_id": None, **context, "status": status}},
        )

    @staticmethod
    def _send_error(connection, code, message):
        if connection.sending_payload:
            return
        try:
            connection.send_header({"status": "ERROR", "code": code, "message": message})
        except (OSError, ProtocolError):
            pass

    def _handle_client(self, client, address, connection_id=None):
        if connection_id is None:
            connection_id = self._next_connection_id()
        connection = Connection(client)
        peer = {
            "connection_id": connection_id,
            "client_ip": address[0],
            "client_port": address[1],
        }
        self._log({**peer, "command": "CONNECT"}, "CONNECTED", "Client connected")
        while not self.stopping:
            context = {**peer, "command": None, "filename": None, "file_size": None}
            try:
                request = connection.receive_header()
                if request is None:
                    self._log({**peer, "command": "DISCONNECT"}, "DISCONNECTED", "Client closed connection")
                    break
                context.update({key: request.get(key) for key in ("command", "filename", "file_size")})
                command = request.get("command")
                if not isinstance(command, str) or command not in ("UPLOAD", "DOWNLOAD", "LIST", "QUIT"):
                    raise ProtocolError("INVALID_COMMAND", "Expected UPLOAD, DOWNLOAD, LIST or QUIT")
                if command == "UPLOAD":
                    self._upload(connection, request, context)
                elif command == "DOWNLOAD":
                    self._download(connection, request, context)
                elif command == "LIST":
                    connection.send_header({"status": "OK", "command": "LIST", "files": self.storage.list_files()})
                else:
                    connection.send_header({"status": "OK", "command": "QUIT"})
                self._log(context, "SUCCESS", f"{command} completed")
                if command == "QUIT":
                    break
            except ProtocolError as exc:
                self._send_error(connection, exc.code, str(exc))
                self._log(context, exc.code, str(exc))
                if exc.fatal:
                    break
            except socket.timeout:
                self._send_error(connection, "TIMEOUT", "Client inactivity timeout")
                self._log(context, "TIMEOUT", "Client inactivity timeout")
                break
            except PeerDisconnected as exc:
                self._log(context, "INCOMPLETE", str(exc))
                break
            except OSError as exc:
                if self.stopping and context["command"] is None:
                    self._log({**peer, "command": "DISCONNECT"}, "DISCONNECTED", "Connection closed on server shutdown")
                    break
                self._send_error(connection, "CONNECTION_OR_IO_ERROR", "Connection or file operation failed")
                self._log(context, "CONNECTION_OR_IO_ERROR", str(exc))
                break

    def _upload(self, connection, request, context):
        target = self.storage.path_for(request.get("filename"))
        file_size = request.get("file_size")
        if type(file_size) is not int or file_size < 0:
            raise ProtocolError("INVALID_FILE_SIZE", "file_size must be a nonnegative integer")
        if file_size > self.config.max_file_size:
            raise ProtocolError("FILE_TOO_LARGE", "Upload exceeds configured max_file_size")
        expected_sha256 = request.get("sha256")
        if expected_sha256 is not None and (
            not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256)
        ):
            raise ProtocolError("INVALID_CHECKSUM", "sha256 must be 64 hexadecimal characters")

        with self._acquire_file_lock(target.name):
            temporary_path = None
            context["transferred_bytes"] = 0
            digest = hashlib.sha256()
            try:
                with self.storage.create_upload() as stream:
                    temporary_path = Path(stream.name)
                    connection.send_header({"status": "READY", "command": "UPLOAD", "filename": target.name, "file_size": file_size})
                    remaining = file_size
                    while remaining:
                        chunk = connection.receive_chunk(min(remaining, self.config.chunk_size))
                        written = stream.write(chunk)
                        if written != len(chunk):
                            raise OSError("Short write while saving uploaded file")
                        digest.update(chunk)
                        remaining -= written
                        context["transferred_bytes"] += written
                    stream.flush()
                    if stream.tell() != file_size:
                        raise ProtocolError("TRANSFER_INCOMPLETE", "Uploaded byte count does not match metadata", fatal=True)

                actual_sha256 = digest.hexdigest()
                context["sha256"] = actual_sha256
                if expected_sha256 is not None and actual_sha256 != expected_sha256.lower():
                    # Do not publish the temporary upload or overwrite an existing file.
                    raise ProtocolError("CHECKSUM_MISMATCH", "Uploaded SHA-256 does not match source checksum")
                self.storage.commit_upload(temporary_path, target)
                connection.send_header({
                    "status": "SUCCESS", "command": "UPLOAD", "filename": target.name,
                    "file_size": file_size, "sha256": actual_sha256,
                })
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

    def _download(self, connection, request, context):
        target = self.storage.path_for(request.get("filename"))
        with self._acquire_file_lock(target.name):
            with self.storage.open_download(target.name) as stream:
                file_size = os.fstat(stream.fileno()).st_size
                context["file_size"] = file_size
                context["transferred_bytes"] = 0
                connection.send_header({
                    "status": "OK", "command": "DOWNLOAD",
                    "filename": request["filename"], "file_size": file_size,
                })
                connection.sending_payload = True
                digest = hashlib.sha256()
                remaining = file_size
                while remaining:
                    chunk = stream.read(min(remaining, self.config.chunk_size))
                    if not chunk:
                        raise PeerDisconnected("Download source changed before all file bytes were sent")
                    connection.sock.sendall(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                    context["transferred_bytes"] += len(chunk)
                connection.sending_payload = False
                actual_sha256 = digest.hexdigest()
                context["sha256"] = actual_sha256
                connection.send_header({
                    "status": "SUCCESS", "command": "DOWNLOAD",
                    "filename": request["filename"], "file_size": file_size,
                    "sha256": actual_sha256,
                })


def main(argv=None):
    config = load_config(argv)
    server = None
    logger = None
    try:
        logger = configure_logging(config.log_file)
        server = FileServer(config, logger)
        server.serve_forever()
    except KeyboardInterrupt:
        if logger is not None:
            logger.info("Server stopped", extra={"event": {"status": "STOPPED"}})
    except (OSError, ValueError) as exc:
        if logger is not None:
            logger.error(str(exc), extra={"event": {"status": "STARTUP_OR_SERVER_ERROR"}})
        else:
            print(f"Cannot start server: {exc}", file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
