"""Additional regression tests for src/common/transfer.py.

Run from repository root: PYTHONPATH=src python -m pytest -q tests/test_transfer_review.py
"""
import hashlib
import tempfile
import unittest
from pathlib import Path

from common.protocol import PeerDisconnected
from common.transfer import (
    MATCH, MISMATCH, calculate_sha256, compare_checksums,
    receive_file_data, send_file_data,
)

class FakeReceiver:
    def __init__(self, data):
        self.data = bytes(data)
        self.at = 0
    def recv(self, maximum):
        fragment = self.data[self.at:self.at+maximum]
        self.at += len(fragment)
        return fragment

class FakeSender:
    def __init__(self):
        self.sent = bytearray()
    def sendall(self, data):
        self.sent.extend(data)

class TransferReviewTests(unittest.TestCase):
    def test_invalid_checksums_never_match(self):
        self.assertEqual(compare_checksums(None, None), MISMATCH)
        self.assertEqual(compare_checksums("abc", "abc"), MISMATCH)
        self.assertEqual(compare_checksums("a"*64, "A"*64), MATCH)

    def test_partial_receive_preserves_old_target(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"original.bin"
            p.write_bytes(b"ORIGINAL")
            with self.assertRaises(PeerDisconnected):
                receive_file_data(FakeReceiver(b"part"), p, 10, chunk_size=2)
            self.assertEqual(p.read_bytes(), b"ORIGINAL")
            self.assertEqual(list(Path(td).glob("*.part")), [])

    def test_wrong_hash_preserves_old_target(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"original.bin"
            p.write_bytes(b"ORIGINAL")
            with self.assertRaisesRegex(ValueError, "CHECKSUM_MISMATCH"):
                receive_file_data(
                    FakeReceiver(b"evil"), p, 4, chunk_size=2,
                    expected_sha256=hashlib.sha256(b"good").hexdigest(),
                )
            self.assertEqual(p.read_bytes(), b"ORIGINAL")

    def test_sent_bytes_equal_metadata_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"file.bin"
            p.write_bytes(b"ABCDEF")
            out = FakeSender()
            with self.assertRaisesRegex(OSError, "larger"):
                send_file_data(out, p, chunk_size=2, expected_size=4)
            self.assertEqual(bytes(out.sent), b"ABCD")
            with self.assertRaisesRegex(OSError, "shorter"):
                send_file_data(FakeSender(), p, chunk_size=2, expected_size=7)

    def test_receive_success_commits(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"file.bin"
            p.write_bytes(b"ORIGINAL")
            payload=b"new-binary-data"
            expected=hashlib.sha256(payload).hexdigest()
            got=receive_file_data(FakeReceiver(payload),p,len(payload),chunk_size=3,expected_sha256=expected)
            self.assertEqual(got,expected)
            self.assertEqual(p.read_bytes(),payload)
