"""A blocking TCP server that handles one client at a time."""

import logging
import os
import socket
import sys
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

    @property
    def address(self):
        if self.listener is None:
            raise RuntimeError("Server is not listening")
        return self.listener.getsockname()

    def start(self):
        if self.listener is not None:
            raise RuntimeError("Server is already listening")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Windows exclusive binding avoids another process sharing the port.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.config.host, self.config.port))
            listener.listen(5)
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
                self.client = client
                with client:
                    client.settimeout(self.config.client_timeout)
                    self._handle_client(client, address)
                self.client = None
        finally:
            self.close()

    def close(self):
        self.stopping = True
        client = self.client
        listener = self.listener
        self.client = None
        self.listener = None
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()
        if listener is not None:
            listener.close()

    def _log(self, context, status, message):
        self.logger.info(message, extra={"event": {**context, "status": status}})

    @staticmethod
    def _send_error(connection, code, message):
        if connection.sending_payload:
            return
        try:
            connection.send_header({"status": "ERROR", "code": code, "message": message})
        except OSError:
            pass

    def _handle_client(self, client, address):
        connection = Connection(client)
        peer = {"client_ip": address[0], "client_port": address[1]}
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
        temporary_path = None
        context["transferred_bytes"] = 0
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
                    remaining -= written
                    context["transferred_bytes"] += written
                stream.flush()
                if stream.tell() != file_size:
                    raise ProtocolError("TRANSFER_INCOMPLETE", "Uploaded byte count does not match metadata", fatal=True)
            self.storage.commit_upload(temporary_path, target)
            connection.send_header({"status": "SUCCESS", "command": "UPLOAD", "filename": target.name, "file_size": file_size})
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _download(self, connection, request, context):
        with self.storage.open_download(request.get("filename")) as stream:
            file_size = os.fstat(stream.fileno()).st_size
            context["file_size"] = file_size
            context["transferred_bytes"] = 0
            connection.send_header({"status": "OK", "command": "DOWNLOAD", "filename": request["filename"], "file_size": file_size})
            connection.sending_payload = True
            remaining = file_size
            while remaining:
                chunk = stream.read(min(remaining, self.config.chunk_size))
                if not chunk:
                    # A partial payload cannot be followed by a JSON error frame.
                    raise PeerDisconnected("Download source changed before all file bytes were sent")
                connection.sock.sendall(chunk)
                remaining -= len(chunk)
                context["transferred_bytes"] += len(chunk)
            connection.sending_payload = False
            connection.send_header({"status": "SUCCESS", "command": "DOWNLOAD", "filename": request["filename"], "file_size": file_size})


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
