"""Validate shared filenames, manage atomic uploads and per-file locking.

Phan cu (Sprint 1) giu nguyen: path_for, create_upload, commit_upload,
open_download, list_files.

Phan moi (CN21-12): khoa theo tung filename, UploadSession, DownloadHandle.
Chinh sach (gia dinh cho S2-01): moi thao tac tren CUNG filename (upload hoac
download) la doc quyen. Thao tac den sau nhan FileBusyError (ma FILE_BUSY),
KHONG cho doi nen khong the deadlock. File khac ten khong chan nhau.

Cach dung toi thieu trong server.py (giu nguyen code upload/download hien co,
chi boc them khoa quanh no):

    # _upload: dat TRUOC khi gui READY de client nhan FILE_BUSY thay vi READY
    with self.storage.locked(request.get("filename"), owner=client_id):
        ... code upload hien tai (create_upload, nhan chunk, commit_upload) ...

    # _download:
    with self.storage.locked(request.get("filename"), owner=client_id):
        ... code download hien tai ...

    # FileBusyError la ProtocolError("FILE_BUSY", ...) nen except ProtocolError
    # hien co se gui loi cho client va tiep tuc, khong can sua them.

    # Trong finally cua Worker (khi client ngat ket noi):
    self.storage.release_all(client_id)

Ngoai ra con begin_upload()/begin_download() neu muon storage lo luon viec
nhan byte, tinh SHA-256 va commit (khong bat buoc).
"""

import hashlib
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from common.protocol import ProtocolError


RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"
}

CHUNK_SIZE = 64 * 1024


# --------------------------------------------------------------------------- #
# Loi moi (deu la ProtocolError de Server xu ly dong nhat)
# --------------------------------------------------------------------------- #
class FileBusyError(ProtocolError):
    def __init__(self, filename=""):
        super().__init__("FILE_BUSY", "File is being used by another client")


class ChecksumMismatchError(ProtocolError):
    def __init__(self):
        super().__init__("CHECKSUM_MISMATCH", "SHA-256 of uploaded data does not match")


class SizeMismatchError(ProtocolError):
    def __init__(self, message="Uploaded size does not match declared size"):
        super().__init__("TRANSFER_INCOMPLETE", message)


# --------------------------------------------------------------------------- #
# Quan ly lock theo tung filename (non-blocking)
# --------------------------------------------------------------------------- #
class FileLockManager:
    """`_guard` chi giu trong vai thao tac dict, khong giu luc truyen file.
    Moi lan acquire co token rieng nen release muon (sau release_all) khong
    the nha nham lock cua client khac."""

    def __init__(self):
        self._guard = threading.Lock()
        self._held = {}  # key -> (token, owner)

    @staticmethod
    def _key(filename):
        return os.path.normcase(filename)  # Windows: khong phan biet hoa/thuong

    def try_acquire(self, filename, owner=""):
        key = self._key(filename)
        with self._guard:
            if key in self._held:
                return None
            token = uuid.uuid4().hex
            self._held[key] = (token, owner)
            return token

    def release(self, filename, token):
        key = self._key(filename)
        with self._guard:
            held = self._held.get(key)
            if held and held[0] == token:
                del self._held[key]
                return True
            return False

    def release_all(self, owner):
        with self._guard:
            keys = [k for k, (_, o) in self._held.items() if o == owner]
            for key in keys:
                del self._held[key]
            return len(keys)

    def is_locked(self, filename):
        with self._guard:
            return self._key(filename) in self._held

    def locked_count(self):
        with self._guard:
            return len(self._held)


# --------------------------------------------------------------------------- #
# Upload / download handles
# --------------------------------------------------------------------------- #
class UploadSession:
    """Mot phien upload. Dung voi `with`; neu khong commit thi tu abort
    (xoa file .part va nha lock)."""

    def __init__(self, storage, filename, token, target, expected_size, expected_sha256):
        self._storage = storage
        self.filename = filename
        self._token = token
        self._target = target
        self.expected_size = expected_size
        self.expected_sha256 = expected_sha256.lower() if expected_sha256 else None
        self._hasher = hashlib.sha256()
        self.received = 0
        self._done = False
        try:
            self._fh = storage.create_upload()
            self._tmp_path = Path(self._fh.name)
        except BaseException:
            storage._locks.release(filename, token)
            raise

    def write(self, data):
        if self._done:
            raise ValueError("Upload session already finished")
        self.received += len(data)
        if self.received > self.expected_size:
            self.abort()
            raise SizeMismatchError("Received more bytes than declared")
        self._fh.write(data)
        self._hasher.update(data)

    def commit(self):
        """Chi os.replace() khi da du byte va dung checksum."""
        if self._done:
            raise ValueError("Upload session already finished")
        try:
            if self.received != self.expected_size:
                raise SizeMismatchError(
                    f"Incomplete upload: received {self.received} of {self.expected_size} bytes"
                )
            if self.expected_sha256 is not None and self._hasher.hexdigest() != self.expected_sha256:
                raise ChecksumMismatchError()
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()
            FileStorage.commit_upload(self._tmp_path, self._target)
        except BaseException:
            self.abort()
            raise
        self._finish()

    def abort(self):
        """Idempotent: xoa staging va nha lock."""
        if self._done:
            return
        try:
            self._fh.close()
        except Exception:
            pass
        try:
            os.remove(self._tmp_path)
        except FileNotFoundError:
            pass
        finally:
            self._finish()

    def _finish(self):
        self._done = True
        self._storage._locks.release(self.filename, self._token)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.abort()  # khong lam gi neu da commit
        return False


class DownloadHandle:
    """Giu lock doc quyen cho den khi dong -> khong doc phai file ghi do."""

    def __init__(self, storage, filename, token, fh):
        self._storage = storage
        self.filename = filename
        self._token = token
        self._fh = fh
        self.size = os.fstat(fh.fileno()).st_size
        self._closed = False

    def read(self, size=CHUNK_SIZE):
        return self._fh.read(size)

    def chunks(self, chunk_size=CHUNK_SIZE):
        while True:
            data = self._fh.read(chunk_size)
            if not data:
                return
            yield data

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._fh.close()  # dong file TRUOC khi nha lock (quan trong tren Windows)
        finally:
            self._storage._locks.release(self.filename, self._token)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


# --------------------------------------------------------------------------- #
# FileStorage
# --------------------------------------------------------------------------- #
class FileStorage:
    def __init__(self, directory, clean_staging=True):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.staging = self.directory / ".uploads"
        if self.staging.is_symlink():
            raise ValueError("Upload staging directory must not be a symbolic link")
        self.staging.mkdir(exist_ok=True)
        self._locks = FileLockManager()
        if clean_staging:
            self.cleanup_staging()

    # ---- Sprint 1 API (giu nguyen) ---------------------------------------- #
    def path_for(self, filename):
        if (
            not isinstance(filename, str)
            or not filename
            or filename in (".", "..", ".uploads", ".gitkeep")
            or len(filename.encode("utf-8", errors="surrogatepass")) > 255
            or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f\ud800-\udfff]', filename)
            or filename.endswith((".", " "))
            or filename.split(".")[0].upper() in RESERVED_NAMES
        ):
            raise ProtocolError("INVALID_FILENAME", "Use a single portable filename without directory components")
        path = self.directory / filename
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ProtocolError("INVALID_FILENAME", "Target must be a regular file")
        return path

    def create_upload(self):
        return tempfile.NamedTemporaryFile(mode="wb", dir=self.staging, suffix=".part", delete=False)

    @staticmethod
    def commit_upload(temporary_path, target, attempts=5):
        # Retry ngan: tren Windows os.replace co the bi PermissionError thoang
        # qua (antivirus/indexer dang mo file dich).
        for attempt in range(attempts):
            try:
                os.replace(temporary_path, target)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def open_download(self, filename):
        path = self.path_for(filename)
        try:
            return path.open("rb")
        except FileNotFoundError as exc:
            raise ProtocolError("FILE_NOT_FOUND", "Requested file does not exist") from exc

    def list_files(self):
        filenames = []
        for path in self.directory.iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            try:
                self.path_for(path.name)
            except ProtocolError:
                continue
            filenames.append(path.name)
        return sorted(filenames)

    # ---- CN21-12: API moi (co lock) --------------------------------------- #
    @contextmanager
    def locked(self, filename, owner=""):
        """Khoa doc quyen theo filename trong khoi `with`; nha khoi khi thoat
        (ke ca khi co exception). Raise FileBusyError neu file dang ban."""
        self.path_for(filename)  # validate truoc, khong tao lock cho ten sai
        token = self._locks.try_acquire(filename, owner)
        if token is None:
            raise FileBusyError(filename)
        try:
            yield
        finally:
            self._locks.release(filename, token)

    def begin_upload(self, filename, expected_size, expected_sha256=None, owner=""):
        target = self.path_for(filename)
        if not isinstance(expected_size, int) or expected_size < 0:
            raise ProtocolError("INVALID_FILE_SIZE", "file_size must be a nonnegative integer")
        token = self._locks.try_acquire(filename, owner)
        if token is None:
            raise FileBusyError(filename)
        try:
            return UploadSession(self, filename, token, target, expected_size, expected_sha256)
        except BaseException:
            self._locks.release(filename, token)
            raise

    def begin_download(self, filename, owner=""):
        self.path_for(filename)
        token = self._locks.try_acquire(filename, owner)
        if token is None:
            raise FileBusyError(filename)
        try:
            return DownloadHandle(self, filename, token, self.open_download(filename))
        except BaseException:
            self._locks.release(filename, token)
            raise

    def release_all(self, owner):
        """Goi khi client ngat ket noi de chac chan khong con FILE_BUSY ma."""
        return self._locks.release_all(owner)

    def cleanup_staging(self):
        """Xoa moi .part bi bo lai. Chi nen goi luc khoi dong server."""
        removed = 0
        for path in self.staging.glob("*.part"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    @property
    def locks(self):
        return self._locks
