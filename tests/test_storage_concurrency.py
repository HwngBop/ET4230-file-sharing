"""Test race condition / integrity cho src/server/storage.py (CN21-12).

Dung threading.Barrier/Event de dieu phoi, KHONG dung sleep ngau nhien.
Chay tu thu muc goc project:
    python -m unittest tests.test_storage_concurrency -v
"""

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.protocol import ProtocolError  # noqa: E402
from server.storage import (  # noqa: E402
    ChecksumMismatchError, FileBusyError, FileStorage, SizeMismatchError,
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.storage = FileStorage(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def upload(self, name, data, owner="", chunk=65536):
        with self.storage.begin_upload(name, len(data), sha(data), owner) as up:
            for i in range(0, len(data), chunk):
                up.write(data[i:i + chunk])
            up.commit()

    def read(self, name):
        return (Path(self.tmp) / name).read_bytes()

    def parts(self):
        return list(self.storage.staging.glob("*.part"))


class TestBackwardCompat(Base):
    """API Sprint 1 van chay nhu cu."""

    def test_old_create_and_commit_upload(self):
        fh = self.storage.create_upload()
        fh.write(b"legacy")
        fh.close()
        FileStorage.commit_upload(fh.name, self.storage.path_for("old.txt"))
        self.assertEqual(self.read("old.txt"), b"legacy")
        self.assertEqual(self.storage.list_files(), ["old.txt"])
        with self.storage.open_download("old.txt") as f:
            self.assertEqual(f.read(), b"legacy")


class TestIntegrity(Base):
    def test_empty_file(self):
        self.upload("empty.bin", b"")
        self.assertEqual(self.read("empty.bin"), b"")

    def test_binary_file(self):
        data = bytes(range(256)) * 100
        self.upload("bin.dat", data)
        self.assertEqual(self.read("bin.dat"), data)

    def test_large_files_1mb_and_50mb(self):
        for mb in (1, 50):
            data = os.urandom(mb * 1024 * 1024)
            self.upload(f"big{mb}.bin", data, chunk=1024 * 1024)
            self.assertEqual(sha(self.read(f"big{mb}.bin")), sha(data))
        self.assertEqual(self.parts(), [])

    def test_download_roundtrip(self):
        data = os.urandom(300_000)
        self.upload("rt.bin", data)
        with self.storage.begin_download("rt.bin") as dl:
            self.assertEqual(dl.size, len(data))
            self.assertEqual(b"".join(dl.chunks(4096)), data)

    def test_download_missing_releases_lock(self):
        with self.assertRaises(ProtocolError):
            self.storage.begin_download("nope.txt")
        self.assertEqual(self.storage.locks.locked_count(), 0)

    def test_invalid_filename_rejected_without_lock(self):
        for bad in ("", "..", "../x", "a/b", "a\\b", "CON"):
            with self.assertRaises(ProtocolError):
                self.storage.begin_upload(bad, 0, sha(b""))
        self.assertEqual(self.storage.locks.locked_count(), 0)

    def test_short_upload_rejected(self):
        data = b"x" * 1000
        up = self.storage.begin_upload("s.bin", len(data), sha(data))
        up.write(data[:600])
        with self.assertRaises(SizeMismatchError):
            up.commit()
        self.assertFalse((Path(self.tmp) / "s.bin").exists())
        self.assertEqual(self.parts(), [])
        self.assertEqual(self.storage.locks.locked_count(), 0)

    def test_extra_bytes_rejected(self):
        up = self.storage.begin_upload("e.bin", 3, sha(b"abc"))
        with self.assertRaises(SizeMismatchError):
            up.write(b"abcd")
        self.assertEqual(self.parts(), [])
        self.assertEqual(self.storage.locks.locked_count(), 0)


class TestConcurrencyPolicy(Base):
    def test_tc01_same_filename_second_gets_busy(self):
        data = b"first"
        up1 = self.storage.begin_upload("a.txt", len(data), sha(data), "c1")
        with self.assertRaises(FileBusyError):
            self.storage.begin_upload("a.txt", 1, sha(b"x"), "c2")
        up1.write(data)
        up1.commit()
        self.upload("a.txt", b"again", "c2")  # het busy sau khi commit
        self.assertEqual(self.read("a.txt"), b"again")

    def test_tc02_upload_while_download_same_file(self):
        self.upload("f.txt", b"old content")
        dl = self.storage.begin_download("f.txt", "reader")
        with self.assertRaises(FileBusyError):
            self.storage.begin_upload("f.txt", 3, sha(b"new"), "writer")
        self.assertEqual(dl.read(), b"old content")
        dl.close()
        self.upload("f.txt", b"new", "writer")
        self.assertEqual(self.read("f.txt"), b"new")

    def test_tc02_download_while_upload_same_file(self):
        self.upload("f.txt", b"old")
        up = self.storage.begin_upload("f.txt", 3, sha(b"new"), "writer")
        up.write(b"ne")  # dang ghi do
        with self.assertRaises(FileBusyError):  # khong doc duoc du lieu do
            self.storage.begin_download("f.txt", "reader")
        up.write(b"w")
        up.commit()
        with self.storage.begin_download("f.txt") as dl:
            self.assertEqual(dl.read(), b"new")

    def test_tc03_different_files_do_not_block(self):
        # Ca hai upload cung "dang mo" cung luc: Barrier chi qua duoc khi
        # CA HAI thread dang giu lock cua minh.
        barrier = threading.Barrier(2, timeout=10)
        errors = []

        def worker(name, data):
            try:
                with self.storage.begin_upload(name, len(data), sha(data), name) as up:
                    up.write(data[: len(data) // 2])
                    barrier.wait()
                    up.write(data[len(data) // 2:])
                    up.commit()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        d1, d2 = os.urandom(10_000), os.urandom(10_000)
        threads = [threading.Thread(target=worker, args=("one.bin", d1)),
                   threading.Thread(target=worker, args=("two.bin", d2))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        self.assertEqual(errors, [])
        self.assertEqual(self.read("one.bin"), d1)
        self.assertEqual(self.read("two.bin"), d2)

    def test_same_filename_stress_no_corruption(self):
        n = 12
        payloads = [bytes([i]) * 200_000 for i in range(n)]
        barrier = threading.Barrier(n, timeout=15)
        results = [None] * n

        def worker(i):
            barrier.wait()
            try:
                self.upload("shared.bin", payloads[i], owner=f"c{i}", chunk=8192)
                results[i] = "ok"
            except FileBusyError:
                results[i] = "busy"

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertTrue(all(r in ("ok", "busy") for r in results), results)
        self.assertIn("ok", results)
        self.assertIn(self.read("shared.bin"), payloads)  # nguyen ven, khong tron lan
        self.assertEqual(self.parts(), [])
        self.assertEqual(self.storage.locks.locked_count(), 0)


class TestLockedContext(Base):
    """API toi thieu cho server.py: `with storage.locked(...)`."""

    def test_locked_blocks_same_file_not_others(self):
        with self.storage.locked("a.txt", owner="c1"):
            with self.assertRaises(FileBusyError):
                with self.storage.locked("a.txt", owner="c2"):
                    pass
            with self.storage.locked("b.txt", owner="c2"):  # file khac van duoc
                pass
        with self.storage.locked("a.txt", owner="c2"):  # het busy
            pass
        self.assertEqual(self.storage.locks.locked_count(), 0)

    def test_locked_released_on_exception(self):
        with self.assertRaises(RuntimeError):
            with self.storage.locked("a.txt"):
                raise RuntimeError("boom")
        self.assertEqual(self.storage.locks.locked_count(), 0)

    def test_locked_invalid_name_creates_no_lock(self):
        with self.assertRaises(ProtocolError):
            with self.storage.locked("../evil"):
                pass
        self.assertEqual(self.storage.locks.locked_count(), 0)

    def test_busy_is_protocol_error_not_fatal(self):
        with self.storage.locked("a.txt"):
            with self.assertRaises(ProtocolError) as ctx:
                with self.storage.locked("a.txt"):
                    pass
        self.assertEqual(ctx.exception.code, "FILE_BUSY")
        self.assertFalse(ctx.exception.fatal)

    def test_upload_without_checksum_allowed(self):
        with self.storage.begin_upload("n.bin", 3) as up:
            up.write(b"abc")
            up.commit()
        self.assertEqual(self.read("n.bin"), b"abc")


class TestFailureAndCleanup(Base):
    def test_tc04_bad_checksum_keeps_old_file(self):
        self.upload("keep.txt", b"OLD")
        up = self.storage.begin_upload("keep.txt", 3, sha(b"expected"))
        up.write(b"NEW")
        with self.assertRaises(ChecksumMismatchError):
            up.commit()
        self.assertEqual(self.read("keep.txt"), b"OLD")
        self.assertEqual(self.parts(), [])
        self.assertEqual(self.storage.locks.locked_count(), 0)

    def test_tc05_disconnect_mid_upload_cleans_staging(self):
        data = b"y" * 5000
        with self.assertRaises(ConnectionResetError):
            with self.storage.begin_upload("dc.bin", len(data), sha(data), "c1") as up:
                up.write(data[:2000])
                self.assertEqual(len(self.parts()), 1)  # staging dang ton tai
                raise ConnectionResetError("client disconnected")
        self.assertEqual(self.parts(), [])
        self.assertFalse((Path(self.tmp) / "dc.bin").exists())
        self.assertFalse(self.storage.locks.is_locked("dc.bin"))
        self.upload("dc.bin", data)  # dung lai duoc ngay

    def test_tc06_lock_released_after_exception_and_reusable(self):
        with self.assertRaises(RuntimeError):
            with self.storage.begin_upload("x.bin", 0, sha(b"")):
                raise RuntimeError("boom")
        self.upload("y.bin", b"data")
        with self.assertRaises(RuntimeError):
            with self.storage.begin_download("y.bin"):
                raise RuntimeError("boom khi dang download")
        self.assertEqual(self.storage.locks.locked_count(), 0)
        self.upload("x.bin", b"ok")
        self.assertEqual(self.read("x.bin"), b"ok")

    def test_release_all_on_disconnect_and_stale_token_safe(self):
        up = self.storage.begin_upload("z.bin", 1, sha(b"z"), owner="c1")
        self.assertEqual(self.storage.release_all("c1"), 1)
        up2 = self.storage.begin_upload("z.bin", 1, sha(b"z"), owner="c2")
        up.abort()  # release muon cua phien cu KHONG duoc nha lock cua c2
        self.assertTrue(self.storage.locks.is_locked("z.bin"))
        up2.write(b"z")
        up2.commit()
        self.assertEqual(self.read("z.bin"), b"z")

    def test_startup_cleans_orphan_part_files(self):
        (self.storage.staging / "orphan.part").write_bytes(b"junk")
        FileStorage(self.tmp)  # khoi dong lai server
        self.assertEqual(self.parts(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
