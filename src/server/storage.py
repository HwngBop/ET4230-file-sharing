"""Validate shared filenames and manage atomic uploads."""

import os
import re
import tempfile
from pathlib import Path

from common.protocol import ProtocolError


RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"
}


class FileStorage:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.staging = self.directory / ".uploads"
        if self.staging.is_symlink():
            raise ValueError("Upload staging directory must not be a symbolic link")
        self.staging.mkdir(exist_ok=True)

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
    def commit_upload(temporary_path, target):
        os.replace(temporary_path, target)

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
